from unittest.mock import AsyncMock, patch

from aiogram import Dispatcher
from redis.asyncio import Redis

from app.__main__ import main
from app.config import BotConfig, Config, RedisConfig
from conftest import FakeSession, OPERATOR, GROUP


async def test_main_initializes_storage_and_runs_startup_without_network():
    """Exercise real storage construction before reaching the mocked polling boundary."""
    config = Config(BotConfig("42:" + "a" * 35, OPERATOR, GROUP), RedisConfig())
    api = FakeSession()
    connections = []

    async def polling(dispatcher, bot, **kwargs):
        connections.append(dispatcher.storage.redis.connection_pool.connection_kwargs)
        await dispatcher.emit_startup(bot=bot, **dispatcher.workflow_data)

    with (
        patch("app.__main__.load_config", return_value=config),
        patch("app.__main__.AiohttpSession", return_value=api),
        patch("app.__main__.include_routers"),
        patch.object(Redis, "ping", new=AsyncMock(return_value=True)),
        patch.object(Dispatcher, "start_polling", autospec=True, side_effect=polling) as poll,
    ):
        await main()

    poll.assert_awaited_once()
    assert connections[0]["socket_connect_timeout"] == 5
    assert connections[0]["socket_timeout"] == 5
    assert api.named("deleteWebhook")
    assert api.named("setMyCommands")
