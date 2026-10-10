from collections import defaultdict
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, ForumTopic, Message, MessageId, Update, User
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

from app.bot.handlers import include_routers
from app.bot.middlewares import register_middlewares
from app.bot.utils.redis import RedisStorage
from app.config import Config, BotConfig, RedisConfig

CLIENT = 200
OPERATOR = 100
GROUP = -1001234567890
NOW = datetime.now(timezone.utc)


class FakeSession(BaseSession):
    """In-memory Bot API boundary: this class never opens a network connection."""

    def __init__(self):
        super().__init__()
        self.calls = []
        self.failures = defaultdict(list)
        self.topic_id = 700

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise AssertionError("Network access is forbidden in tests")
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        name = method.__api_method__
        if self.failures[name]:
            raise self.failures[name].pop(0)
        if name == "getMe":
            return User(id=42, is_bot=True, first_name="Support", username="test_support_bot")
        if name == "createForumTopic":
            self.topic_id += 1
            return ForumTopic(message_thread_id=self.topic_id, name=method.name, icon_color=0)
        if name in ("copyMessage", "forwardMessage"):
            return MessageId(message_id=len(self.calls))
        if name in ("sendMessage", "editMessageText"):
            return Message(
                message_id=len(self.calls), date=NOW,
                chat=Chat(id=method.chat_id, type="private" if method.chat_id > 0 else "supergroup"),
                text=method.text,
            ).as_(bot)
        if name == "sendMediaGroup":
            return [Message(message_id=i + 1, date=NOW, chat=Chat(id=method.chat_id, type="private"))
                    for i, _ in enumerate(method.media)]
        return True

    def named(self, name):
        return [call for call in self.calls if call.__api_method__ == name]


@pytest_asyncio.fixture
async def runtime():
    server = FakeServer()
    client = FakeRedis(server=server)
    config = Config(BotConfig("42:" + "a" * 35, OPERATOR, GROUP), RedisConfig())
    session = FakeSession()
    bot = Bot(config.bot.TOKEN, session=session, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage(), config=config)
    include_routers(dp)
    register_middlewares(dp, redis=client)
    rt = SimpleNamespace(dp=dp, bot=bot, api=session, redis=RedisStorage(client),
                         client=client, server=server, config=config, counter=0)

    async def feed(message, edited=False):
        rt.counter += 1
        return await dp.feed_update(bot, Update(update_id=rt.counter, **{
            "edited_message" if edited else "message": message,
        }))
    rt.feed = feed
    yield rt
    # Router objects are module-level in the upstream architecture; detach for the next test.
    for router in dp.sub_routers:
        router._parent_router = None
    dp.sub_routers.clear()
    await dp.storage.close()
    await client.aclose()
    await bot.session.close()


def private(text="Help", message_id=1, **fields):
    return Message(message_id=message_id, date=NOW, chat=Chat(id=CLIENT, type="private"),
                   from_user=User(id=CLIENT, is_bot=False, first_name="Client"), text=text, **fields)


def group(text="Answer", user_id=OPERATOR, chat_id=GROUP, thread_id=701, message_id=10, **fields):
    return Message(message_id=message_id, date=NOW,
                   chat=Chat(id=chat_id, type="supergroup"), message_thread_id=thread_id,
                   from_user=User(id=user_id, is_bot=False, first_name="Operator"), text=text, **fields)
