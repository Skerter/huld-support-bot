from contextlib import suppress

from aiogram import Router, F
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberUpdated
from aiogram.utils.markdown import hlink

from app.bot.manager import Manager
from app.bot.utils.redis import RedisStorage
from app.bot.utils.redis.models import UserData

router = Router()
router.my_chat_member.filter(F.chat.type == "private")


@router.my_chat_member()
async def handle_chat_member_update(
    update: ChatMemberUpdated, redis: RedisStorage, user_data: UserData, manager: Manager,
) -> None:
    current = await redis.update_fields(user_data.id, state=update.new_chat_member.status)
    if current.message_thread_id is None:
        return
    code = "user_restarted_bot" if current.state == ChatMemberStatus.MEMBER else "user_stopped_bot"
    username = (current.username or "").lstrip("@")
    url = f"https://t.me/{username}" if username and username != "-" else f"tg://user?id={current.id}"
    with suppress(TelegramAPIError):
        await update.bot.send_message(
            chat_id=manager.config.bot.GROUP_ID,
            text=manager.text_message.get(code).format(name=hlink(current.full_name, url)),
            message_thread_id=current.message_thread_id,
        )
