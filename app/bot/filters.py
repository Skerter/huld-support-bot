from aiogram.filters import Filter
from aiogram.types import Message

from app.config import Config


class Operator(Filter):
    """Allow only the configured operator in the configured support group."""

    def __init__(self, require_topic: bool = False) -> None:
        self.require_topic = require_topic

    async def __call__(self, message: Message, config: Config) -> bool:
        return bool(
            message.chat.type in ("group", "supergroup")
            and message.chat.id == config.bot.GROUP_ID
            and message.from_user is not None
            and not message.from_user.is_bot
            and message.from_user.id == config.bot.DEV_ID
            and message.sender_chat is None
            and (not self.require_topic or message.message_thread_id is not None)
        )


class SupportContent(Filter):
    """Whitelist user content so service events never enter the relay."""

    async def __call__(self, message: Message) -> bool:
        return message.content_type in {
            "text", "photo", "document", "video", "audio", "voice", "video_note",
            "animation", "sticker", "contact", "location", "venue", "dice", "poll",
        } and not (message.text and message.text.startswith("/"))
