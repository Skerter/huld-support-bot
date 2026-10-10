from aiogram import BaseMiddleware
from redis.asyncio import Redis

from app.bot.utils.redis import RedisStorage
from app.bot.utils.redis.models import UserData


class RedisMiddleware(BaseMiddleware):
    """Serialize user events and operator changes; refresh records under the lock."""

    def __init__(self, redis: Redis) -> None:
        self.redis = RedisStorage(redis)

    async def __call__(self, handler, event, data):
        data["redis"] = self.redis
        data["user_data"] = None
        chat = data.get("event_chat")
        user = data.get("event_from_user")
        if chat is None or user is None:
            return await handler(event, data)
        if chat.type == "private":
            user_id = user.id
        else:
            owner = await self.redis.get_by_message_thread_id(getattr(event, "message_thread_id", None))
            if owner is None:
                return await handler(event, data)
            user_id = owner.id
        async with self.redis.user_lock(user_id):
            if chat.type == "private":
                current = await self.redis.get_user(user_id)
                if current is None:
                    current = UserData(
                        message_thread_id=None, message_silent_id=None,
                        message_silent_mode=False, id=user.id, full_name=user.full_name,
                        username=f"@{user.username}" if user.username else "-",
                        language_code="ru",
                    )
                    await self.redis.update_user(user_id, current)
                else:
                    current = await self.redis.update_fields(
                        user_id, full_name=user.full_name,
                        username=f"@{user.username}" if user.username else "-",
                    )
                data["user_data"] = current
            return await handler(event, data)
