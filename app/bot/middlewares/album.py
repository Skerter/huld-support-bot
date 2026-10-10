from asyncio import sleep
from time import monotonic

from aiogram import BaseMiddleware
from aiogram.types import Message
from cachetools import TTLCache

from ..types.album import Album


class AlbumMiddleware(BaseMiddleware):
    """Collect album messages before serialization, preserving order and captions."""

    def __init__(self, latency: float = 0.5) -> None:
        self.latency = latency
        self.cache = TTLCache(maxsize=10_000, ttl=60)

    async def __call__(self, handler, event, data):
        if not isinstance(event, Message) or event.media_group_id is None:
            return await handler(event, data)
        key = (event.chat.id, event.media_group_id)
        if key in self.cache:
            batch = self.cache[key]
            if not batch["sent"]:
                batch["messages"].append(event)
                batch["last"] = monotonic()
                return None
            # A very late item is delivered separately instead of silently dropped.
            return await handler(event, data)
        batch = {"messages": [event], "last": monotonic(), "sent": False}
        self.cache[key] = batch
        while monotonic() - batch["last"] < self.latency:
            await sleep(self.latency)
        batch["sent"] = True
        messages = sorted(batch["messages"], key=lambda message: message.message_id)
        if len(messages) > 1:
            data["album"] = Album(messages=messages).as_(data["bot"])
        return await handler(event, data)
