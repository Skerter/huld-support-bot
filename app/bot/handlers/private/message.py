import logging
from contextlib import suppress

from aiogram import Router, F
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import Message

from app.bot.manager import Manager
from app.bot.types.album import Album
from app.bot.utils.create_forum_topic import get_or_create_forum_topic
from app.bot.utils.redis import RedisStorage
from app.bot.utils.redis.models import UserData
from app.bot.utils.exceptions import CreateForumTopicException, NotEnoughRightsException, NotAForumException
from app.bot.filters import SupportContent

router = Router()
router.message.filter(F.chat.type == "private", F.from_user.is_bot == False, SupportContent())
router.edited_message.filter(F.chat.type == "private", F.from_user.is_bot == False, SupportContent())


@router.edited_message()
async def handle_edited_message(message: Message, manager: Manager) -> None:
    await message.reply(manager.text_message.get("message_edited"))


@router.message()
async def handle_incoming_message(
    message: Message, manager: Manager, redis: RedisStorage,
    user_data: UserData, album: Album | None = None,
) -> None:
    """Deliver real requests; retain originals and explicitly report failed delivery."""
    if user_data.is_banned:
        await message.reply(manager.text_message.get("request_blocked"))
        return

    async def deliver(thread_id: int):
        if album is None:
            await message.forward(chat_id=manager.config.bot.GROUP_ID, message_thread_id=thread_id)
        else:
            await album.copy_to(chat_id=manager.config.bot.GROUP_ID, message_thread_id=thread_id)

    try:
        thread_id = await get_or_create_forum_topic(message.bot, redis, manager.config, user_data)
        try:
            await deliver(thread_id)
        except TelegramBadRequest as exc:
            if "message thread not found" not in exc.message.lower():
                raise
            thread_id = await get_or_create_forum_topic(
                message.bot, redis, manager.config, user_data, missing_thread_id=thread_id,
            )
            await deliver(thread_id)
    except (TelegramAPIError, CreateForumTopicException, NotEnoughRightsException, NotAForumException) as exc:
        logging.warning("Request delivery failed: %s", type(exc).__name__)
        with suppress(TelegramAPIError):
            await message.reply(manager.text_message.get("delivery_failed"))
        return
