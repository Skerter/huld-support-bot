import logging
from contextlib import suppress

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

from app.bot.utils.texts import TextMessage

router = Router()


@router.errors(F.exception.message.contains("query is too old"))
async def query_too_old(_: ErrorEvent) -> None:
    pass


@router.errors()
async def handle_error(event: ErrorEvent, bot: Bot) -> None:
    """Report only an update number and exception class; never export correspondence."""
    logging.error("Update %s failed: %s", event.update.update_id, type(event.exception).__name__)
    message = event.update.message or event.update.edited_message
    if message is not None and message.chat.type == "private":
        with suppress(TelegramAPIError):
            await bot.send_message(message.chat.id, TextMessage("ru").get("delivery_failed"))
