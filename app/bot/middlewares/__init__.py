from aiogram import Dispatcher

from .album import AlbumMiddleware
from .manager import ManagerMiddleware
from .redis import RedisMiddleware
from .throttling import ThrottlingMiddleware


def register_middlewares(dp: Dispatcher, **kwargs) -> None:
    """Aggregate albums before acquiring user locks or counting requests."""
    dp.message.middleware.register(AlbumMiddleware())
    for observer in (dp.message, dp.edited_message, dp.callback_query, dp.my_chat_member):
        observer.middleware.register(RedisMiddleware(kwargs["redis"]))
        observer.middleware.register(ManagerMiddleware())
    dp.message.middleware.register(ThrottlingMiddleware())


__all__ = ["register_middlewares"]
