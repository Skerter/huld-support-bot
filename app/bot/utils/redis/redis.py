import json

from redis.asyncio import Redis
from redis.exceptions import WatchError

from .models import UserData


class RedisStorage:
    """Persist users and their topic index in the original Redis key format."""

    NAME = "users"

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def user_lock(self, user_id: int):
        return self.redis.lock(f"support:user:{user_id}", timeout=300, blocking_timeout=15)

    def topic_lock(self, user_id: int):
        return self.redis.lock(f"support:topic:{user_id}", timeout=120, blocking_timeout=15)

    async def get_user(self, id_: int) -> UserData | None:
        data = await self.redis.hget(self.NAME, id_)
        return UserData(**json.loads(data)) if data is not None else None

    async def get_by_message_thread_id(self, message_thread_id: int | None) -> UserData | None:
        if message_thread_id is None:
            return None
        index_key = f"{self.NAME}_index_{message_thread_id}"
        # Validate legacy indices: ambiguous or stale indices must never misroute a reply.
        matches = []
        for user_id in await self.redis.hkeys(index_key):
            user = await self.get_user(int(user_id))
            if user is not None and user.message_thread_id == message_thread_id:
                matches.append(user)
        return matches[0] if len(matches) == 1 else None

    async def update_user(self, id_: int, data: UserData) -> None:
        if id_ != data.id:
            raise ValueError("User ID mismatch")
        await self._write(id_, data=data)

    async def update_fields(self, id_: int, **fields) -> UserData:
        """Patch current data without overwriting concurrent changes to other fields."""
        return await self._write(id_, fields=fields)

    async def _write(self, id_: int, data: UserData | None = None, fields=None) -> UserData:
        for _ in range(10):
            async with self.redis.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(self.NAME)
                    raw = await pipe.hget(self.NAME, id_)
                    previous = UserData(**json.loads(raw)) if raw is not None else None
                    current = data
                    if current is None:
                        if previous is None:
                            raise ValueError("User not found")
                        current = UserData(**(previous.to_dict() | fields))
                    if current.id != id_:
                        raise ValueError("User ID mismatch")
                    thread_id = current.message_thread_id
                    index_key = f"{self.NAME}_index_{thread_id}"
                    if thread_id is not None:
                        await pipe.watch(index_key)
                        for owner in await pipe.hkeys(index_key):
                            owner_id = int(owner)
                            owner_raw = await pipe.hget(self.NAME, owner_id)
                            if owner_id != id_ and owner_raw is not None:
                                if json.loads(owner_raw).get("message_thread_id") == thread_id:
                                    raise ValueError("Topic already belongs to another user")
                    pipe.multi()
                    if previous is not None and previous.message_thread_id != thread_id:
                        if previous.message_thread_id is not None:
                            pipe.hdel(f"{self.NAME}_index_{previous.message_thread_id}", id_)
                    pipe.delete(f"{self.NAME}_index_None")
                    pipe.hset(self.NAME, id_, json.dumps(current.to_dict()))
                    if thread_id is not None:
                        pipe.delete(index_key)
                        pipe.hset(index_key, id_, "1")
                    await pipe.execute()
                    return current
                except WatchError:
                    continue
        raise RuntimeError("Concurrent user update did not complete")

    async def allow_request(self, key: str, limit: int, seconds: int = 60) -> bool:
        """Count requests in a bounded window shared by all bot instances."""
        count = await self.redis.eval(
            "local n = redis.call('INCR', KEYS[1]); "
            "if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end; return n",
            1, f"support:rate:{key}", seconds,
        )
        return count <= limit
