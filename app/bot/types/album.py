from aiogram.methods import SendMediaGroup
from aiogram.types import (
    InputMediaAudio, InputMediaDocument, InputMediaPhoto, InputMediaVideo,
    Message, TelegramObject,
)
from pydantic import Field

INPUT_TYPES = {
    "photo": InputMediaPhoto, "video": InputMediaVideo,
    "audio": InputMediaAudio, "document": InputMediaDocument,
}


class Album(TelegramObject):
    """An ordered album retaining each item's caption and formatting entities."""

    messages: list[Message] = Field(default_factory=list)

    @property
    def as_media_group(self):
        media = []
        for message in self.messages:
            kind = message.content_type
            attachment = message.photo[-1] if kind == "photo" else getattr(message, kind)
            media.append(INPUT_TYPES[kind](
                media=attachment.file_id, caption=message.caption,
                caption_entities=message.caption_entities, parse_mode=None,
                **({"has_spoiler": message.has_media_spoiler} if kind in ("photo", "video") else {}),
            ))
        return media

    def copy_to(self, chat_id: int | str, message_thread_id: int | None = None) -> SendMediaGroup:
        return SendMediaGroup(
            chat_id=chat_id, message_thread_id=message_thread_id, media=self.as_media_group,
        ).as_(self.bot)
