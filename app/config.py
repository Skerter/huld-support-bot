from dataclasses import dataclass, field

from environs import Env


@dataclass
class BotConfig:
    TOKEN: str = field(repr=False)
    DEV_ID: int
    GROUP_ID: int
    BOT_EMOJI_ID: str = ""
    MESSAGES_PER_MINUTE: int = 30
    TOPICS_PER_MINUTE: int = 10


@dataclass
class RedisConfig:
    HOST: str = "valkey"
    PORT: int = 6379
    DB: int = 0

    def dsn(self) -> str:
        return f"redis://{self.HOST}:{self.PORT}/{self.DB}"


@dataclass
class Config:
    bot: BotConfig
    redis: RedisConfig


def load_config() -> Config:
    """Read local .env or container environment; validate without exposing values."""
    env = Env()
    env.read_env(".env", recurse=False)
    config = Config(
        bot=BotConfig(
            TOKEN=env.str("BOT_TOKEN"), DEV_ID=env.int("BOT_DEV_ID"),
            GROUP_ID=env.int("BOT_GROUP_ID"), BOT_EMOJI_ID=env.str("BOT_EMOJI_ID", ""),
            MESSAGES_PER_MINUTE=env.int("BOT_MESSAGES_PER_MINUTE", 30),
            TOPICS_PER_MINUTE=env.int("BOT_TOPICS_PER_MINUTE", 10),
        ),
        redis=RedisConfig(
            HOST=env.str("REDIS_HOST", "valkey"), PORT=env.int("REDIS_PORT", 6379),
            DB=env.int("REDIS_DB", 0),
        ),
    )
    if config.bot.DEV_ID <= 0 or config.bot.GROUP_ID >= 0:
        raise ValueError("BOT_DEV_ID must be positive; BOT_GROUP_ID must be negative")
    if min(config.bot.MESSAGES_PER_MINUTE, config.bot.TOPICS_PER_MINUTE) <= 0:
        raise ValueError("Rate limits must be positive")
    return config
