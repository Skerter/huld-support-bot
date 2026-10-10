import logging
from contextlib import suppress

from aiogram import Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import Message

from app.bot.filters import Operator, SupportContent
from app.bot.manager import Manager
from app.bot.types.album import Album
from app.bot.utils.redis import RedisStorage

router = Router()
router.message.filter(Operator(require_topic=True), SupportContent())
router.edited_message.filter(Operator(require_topic=True), SupportContent())


@router.edited_message()
async def handle_edited_message(message: Message, manager: Manager) -> None:
    await message.reply(manager.text_message.get("message_edited"))


@router.message()
async def handle_operator_message(
    message: Message, manager: Manager, redis: RedisStorage, album: Album | None = None,
) -> None:
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if user_data is None or user_data.message_silent_mode:
        return
    try:
        if album is None:
            await message.copy_to(chat_id=user_data.id)
        else:
            await album.copy_to(chat_id=user_data.id)
    except TelegramAPIError as exc:
        logging.warning("Operator delivery failed: %s", type(exc).__name__)
        code = "blocked_by_user" if isinstance(exc, TelegramForbiddenError) else "message_not_sent"
        with suppress(TelegramAPIError):
            await message.reply(manager.text_message.get(code))
