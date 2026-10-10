from aiogram import Bot
from aiogram.types import (
    BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats,
    BotCommandScopeChat, BotCommandScopeChatMember,
)

from app.config import Config


async def setup(bot: Bot, config: Config) -> None:
    """Publish Russian by default; limit operator commands to one chat member."""
    private = {
        "ru": [("start", "Поддержка Huld VPN"), ("language", "Изменить язык"),
               ("source", "Исходный проект"), ("id", "Мой Telegram ID")],
        "en": [("start", "Huld VPN support"), ("language", "Change language"),
               ("source", "Original project"), ("id", "My Telegram ID")],
    }
    operator = {
        "ru": [("ban", "Заблокировать или разблокировать пользователя"),
               ("silent", "Включить или выключить внутренние комментарии"),
               ("information", "Информация о пользователе"), ("id", "ID группы")],
        "en": [("ban", "Block or unblock user"), ("silent", "Toggle internal comments"),
               ("information", "User information"), ("id", "Group ID")],
    }
    for language in ("", "ru", "en"):
        # Remove command scopes left by the upstream version.
        await bot.delete_my_commands(scope=BotCommandScopeAllGroupChats(), language_code=language)
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=config.bot.DEV_ID),
                                     language_code=language)
        code = language or "ru"
        await bot.set_my_commands(
            commands=[BotCommand(command=c, description=d) for c, d in private[code]],
            scope=BotCommandScopeAllPrivateChats(), language_code=language,
        )
        await bot.set_my_commands(
            commands=[BotCommand(command=c, description=d) for c, d in operator[code]],
            scope=BotCommandScopeChatMember(chat_id=config.bot.GROUP_ID, user_id=config.bot.DEV_ID),
            language_code=language,
        )
