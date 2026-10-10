import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from .bot import commands
from .bot.handlers import include_routers
from .bot.middlewares import register_middlewares
from .config import load_config, Config
from .logger import setup_logger


async def on_startup(config: Config, bot: Bot) -> None:
    await commands.setup(bot, config)


async def main() -> None:
    """Run one polling instance with independent persistent Valkey storage."""
    config = load_config()
    storage = RedisStorage.from_url(
        config.redis.dsn(),
        connection_kwargs={"socket_connect_timeout": 5, "socket_timeout": 5},
    )
    bot = Bot(token=config.bot.TOKEN, session=AiohttpSession(timeout=15),
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=storage, config=config)
    dp.startup.register(on_startup)
    include_routers(dp)
    register_middlewares(dp, redis=storage.redis)
    try:
        await storage.redis.ping()
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await storage.close()
        await bot.session.close()


if __name__ == "__main__":
    setup_logger()
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as exc:
        # Exception strings can contain tokens, request bodies, or connection details.
        logging.critical("Startup/polling failed: %s", type(exc).__name__)
        raise SystemExit(1) from None
