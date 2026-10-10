import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from app.config import Config
from .exceptions import CreateForumTopicException, NotEnoughRightsException, NotAForumException
from .redis import RedisStorage
from .redis.models import UserData


async def get_or_create_forum_topic(
    bot: Bot, redis: RedisStorage, config: Config, user_data: UserData,
    missing_thread_id: int | None = None,
) -> int:
    """Create once under a shared lock; replace only the known missing topic."""
    async with redis.topic_lock(user_data.id):
        current = await redis.get_user(user_data.id) or user_data
        if current.message_thread_id is None or (
            missing_thread_id is not None and current.message_thread_id == missing_thread_id
        ):
            if not await redis.allow_request("topics", config.bot.TOPICS_PER_MINUTE):
                raise CreateForumTopicException
            thread_id = await create_forum_topic(bot, config, current.full_name)
            if await redis.get_user(current.id) is None:
                current.message_thread_id = thread_id
                await redis.update_user(current.id, current)
            else:
                current = await redis.update_fields(current.id, message_thread_id=thread_id)
        user_data.message_thread_id = current.message_thread_id
        if current.message_thread_id is None:
            raise CreateForumTopicException
        return current.message_thread_id


async def create_forum_topic(bot: Bot, config: Config, name: str) -> int:
    """Create a topic with at most three attempts and bounded RetryAfter waits."""
    for attempt in range(3):
        try:
            topic = await bot.create_forum_topic(
                chat_id=config.bot.GROUP_ID, name=name[:128],
                icon_custom_emoji_id=config.bot.BOT_EMOJI_ID or None,
                request_timeout=15,
            )
            return topic.message_thread_id
        except TelegramRetryAfter as exc:
            if attempt == 2 or exc.retry_after > 15:
                raise CreateForumTopicException from exc
            await asyncio.sleep(exc.retry_after)
        except TelegramBadRequest as exc:
            if "not enough rights" in exc.message:
                raise NotEnoughRightsException from exc
            if "not a forum" in exc.message:
                raise NotAForumException from exc
            raise CreateForumTopicException from exc
    raise CreateForumTopicException
