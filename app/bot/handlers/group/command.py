from contextlib import suppress
from html import escape

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.markdown import hcode

from app.bot.filters import Operator
from app.bot.manager import Manager
from app.bot.utils.redis import RedisStorage

router_id = Router()
router_id.message.filter(Operator())


@router_id.message(Command("id"))
async def handle_id(message: Message) -> None:
    await message.reply(hcode(message.chat.id))


router = Router()
router.message.filter(Operator(require_topic=True))


@router.message(Command("silent"))
async def handle_silent(message: Message, manager: Manager, redis: RedisStorage) -> None:
    """Persist the mode independently of optional notification and pin permissions."""
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if user_data is None:
        return
    enabled = not user_data.message_silent_mode
    old_pin = user_data.message_silent_id
    await redis.update_fields(user_data.id, message_silent_mode=enabled, message_silent_id=None)
    with suppress(TelegramAPIError):
        if not enabled and old_pin is not None:
            await message.bot.unpin_chat_message(chat_id=message.chat.id, message_id=old_pin)
    code = "silent_mode_enabled" if enabled else "silent_mode_disabled"
    with suppress(TelegramAPIError):
        notification = await message.reply(manager.text_message.get(code))
        if enabled:
            await notification.pin(disable_notification=True)
            await redis.update_fields(user_data.id, message_silent_id=notification.message_id)


@router.message(Command("information"))
async def handle_information(message: Message, manager: Manager, redis: RedisStorage) -> None:
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if user_data is None:
        return
    values = {key: escape(str(value)) for key, value in user_data.to_dict().items()}
    await message.reply(manager.text_message.get("user_information").format_map(values))


@router.message(Command("ban"))
async def handle_ban(message: Message, manager: Manager, redis: RedisStorage) -> None:
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if user_data is None:
        return
    banned = not user_data.is_banned
    await redis.update_fields(user_data.id, is_banned=banned)
    await message.reply(manager.text_message.get("user_blocked" if banned else "user_unblocked"))
