from aiogram import BaseMiddleware
from aiogram.types import Message


class ThrottlingMiddleware(BaseMiddleware):
    """Reject excessive requests explicitly, leaving originals in the private chat."""

    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.chat.type == "private":
            if not await data["redis"].allow_request(
                f"messages:{event.chat.id}", data["config"].bot.MESSAGES_PER_MINUTE,
            ):
                await event.reply(data["manager"].text_message.get("rate_limited"))
                return None
        return await handler(event, data)
