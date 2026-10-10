import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import CreateForumTopic, ForwardMessage, CopyMessage, SendMessage
from aiogram.types import (
    Chat, ChatMemberUpdated, ChatMemberMember, ChatMemberBanned,
    ForumTopicClosed, MessageEntity, PhotoSize, Update, User, Video,
)
from fakeredis.aioredis import FakeRedis

from app.bot import commands
from app.bot.middlewares.album import AlbumMiddleware
from app.bot.types.album import Album
from app.bot.utils.create_forum_topic import create_forum_topic, get_or_create_forum_topic
from app.bot.utils.exceptions import CreateForumTopicException
from app.bot.utils.redis import RedisStorage
from app.bot.utils.redis.models import UserData
from app.bot.utils.texts import TextMessage
from conftest import CLIENT, OPERATOR, GROUP, NOW, private, group


def user(thread=None, user_id=CLIENT):
    return UserData(thread, None, False, user_id, "Client", None)


async def test_start_does_not_create_topic(runtime):
    await runtime.feed(private("/start"))
    assert not runtime.api.named("createForumTopic")
    assert not runtime.api.named("forwardMessage")
    assert (await runtime.redis.get_user(CLIENT)).message_thread_id is None
    assert "Huld" in runtime.api.named("sendMessage")[-1].text


async def test_first_and_repeat_requests_use_same_topic(runtime):
    await runtime.feed(private())
    await runtime.feed(private("More details", message_id=2))
    assert len(runtime.api.named("createForumTopic")) == 1
    assert [m.message_thread_id for m in runtime.api.named("forwardMessage")] == [701, 701]
    assert (await runtime.redis.get_by_message_thread_id(701)).id == CLIENT
    assert not runtime.api.named("sendMessage")


async def test_operator_reply_routes_to_topic_owner(runtime):
    await runtime.feed(private())
    await runtime.feed(group())
    assert runtime.api.named("copyMessage")[-1].chat_id == CLIENT


@pytest.mark.parametrize("text", ["/ban", "/silent", "/information", "/id", "Answer"])
@pytest.mark.parametrize("user_id,chat_id", [(999, GROUP), (OPERATOR, -100999)])
async def test_unauthorized_operator_cannot_control_or_relay(runtime, text, user_id, chat_id):
    await runtime.redis.update_user(CLIENT, user(701))
    await runtime.feed(group(text, user_id=user_id, chat_id=chat_id))
    assert not runtime.api.calls
    current = await runtime.redis.get_user(CLIENT)
    assert not current.is_banned and not current.message_silent_mode


async def test_silent_toggles_delivery_and_survives_notification_failure(runtime):
    await runtime.redis.update_user(CLIENT, user(701))
    runtime.api.failures["sendMessage"].append(TelegramBadRequest(
        method=SendMessage(chat_id=GROUP, text="status"), message="not enough rights"))
    await runtime.feed(group("/silent"))
    assert (await runtime.redis.get_user(CLIENT)).message_silent_mode
    await runtime.feed(group("Internal comment"))
    assert not runtime.api.named("copyMessage")
    await runtime.feed(group("/silent"))
    await runtime.feed(group("Visible reply"))
    assert len(runtime.api.named("copyMessage")) == 1
    assert not (await runtime.redis.get_user(CLIENT)).message_silent_mode


async def test_ban_blocks_requests_and_unban_restores(runtime):
    await runtime.redis.update_user(CLIENT, user(701))
    await runtime.feed(group("/ban"))
    await runtime.feed(private())
    assert not runtime.api.named("forwardMessage")
    assert runtime.api.named("sendMessage")[-1].text == TextMessage("ru").get("request_blocked")
    await runtime.feed(group("/ban"))
    await runtime.feed(private())
    assert len(runtime.api.named("forwardMessage")) == 1


@pytest.mark.parametrize("stage", ["createForumTopic", "forwardMessage"])
async def test_private_api_failure_has_no_success_confirmation(runtime, stage):
    method = CreateForumTopic(chat_id=GROUP, name="x") if stage == "createForumTopic" else ForwardMessage(
        chat_id=GROUP, from_chat_id=CLIENT, message_id=1)
    runtime.api.failures[stage].append(TelegramBadRequest(method=method, message="failure"))
    await runtime.feed(private())
    texts = [m.text for m in runtime.api.named("sendMessage")]
    assert texts == [TextMessage("ru").get("delivery_failed")]
    assert not runtime.api.named("deleteMessage")


@pytest.mark.parametrize("error", [TelegramBadRequest, TelegramForbiddenError])
async def test_operator_api_error_is_reported_as_failure(runtime, error):
    await runtime.redis.update_user(CLIENT, user(701))
    runtime.api.failures["copyMessage"].append(error(
        method=CopyMessage(chat_id=CLIENT, from_chat_id=GROUP, message_id=10), message="failure"))
    await runtime.feed(group())
    texts = [m.text for m in runtime.api.named("sendMessage")]
    assert TextMessage("ru").get("message_sent_to_user") not in texts
    assert texts[-1] == TextMessage("ru").get(
        "blocked_by_user" if error is TelegramForbiddenError else "message_not_sent")


async def test_no_none_index_and_index_moves_atomically(runtime):
    await runtime.client.hset("users_index_None", CLIENT, "1")
    await runtime.redis.update_user(CLIENT, user())
    assert not await runtime.client.exists("users_index_None")
    assert await runtime.redis.get_by_message_thread_id(None) is None
    await runtime.redis.update_fields(CLIENT, message_thread_id=701)
    await runtime.redis.update_fields(CLIENT, message_thread_id=702)
    assert await runtime.redis.get_by_message_thread_id(701) is None
    assert (await runtime.redis.get_by_message_thread_id(702)).id == CLIENT
    await runtime.redis.update_fields(CLIENT, message_thread_id=None)
    assert await runtime.redis.get_by_message_thread_id(702) is None


async def test_legacy_record_and_new_client_reuse_mapping(runtime):
    record = user(701).to_dict()
    await runtime.client.hset("users", CLIENT, json.dumps(record))
    await runtime.client.hset("users_index_701", CLIENT, "1")
    another = FakeRedis(server=runtime.server)
    try:
        storage = RedisStorage(another)
        assert (await storage.get_by_message_thread_id(701)).id == CLIENT
        await get_or_create_forum_topic(runtime.bot, storage, runtime.config, user())
        assert not runtime.api.named("createForumTopic")
    finally:
        await another.aclose()


async def test_collision_and_stale_index_cannot_misroute(runtime):
    await runtime.redis.update_user(CLIENT, user(701))
    with pytest.raises(ValueError, match="belongs"):
        await runtime.redis.update_user(201, user(701, user_id=201))
    await runtime.client.hset("users_index_999", CLIENT, "1")
    assert await runtime.redis.get_by_message_thread_id(999) is None
    assert (await runtime.redis.get_by_message_thread_id(701)).id == CLIENT


async def test_concurrent_requests_create_one_topic(runtime):
    await asyncio.gather(*(runtime.feed(private(f"Message {i}", message_id=i + 1)) for i in range(8)))
    assert len(runtime.api.named("createForumTopic")) == 1
    assert len(runtime.api.named("forwardMessage")) == 8
    assert {m.message_thread_id for m in runtime.api.named("forwardMessage")} == {701}


async def test_concurrent_helpers_on_two_clients_create_once(runtime):
    await runtime.redis.update_user(CLIENT, user())
    another = FakeRedis(server=runtime.server)
    try:
        storage = RedisStorage(another)
        ids = await asyncio.gather(
            get_or_create_forum_topic(runtime.bot, runtime.redis, runtime.config, user()),
            get_or_create_forum_topic(runtime.bot, storage, runtime.config, user()),
        )
        assert ids == [701, 701]
        assert len(runtime.api.named("createForumTopic")) == 1
    finally:
        await another.aclose()


async def test_retry_after_is_bounded(runtime):
    method = CreateForumTopic(chat_id=GROUP, name="Client")
    runtime.api.failures["createForumTopic"] = [TelegramRetryAfter(
        method=method, message="slow down", retry_after=1) for _ in range(3)]
    with patch("app.bot.utils.create_forum_topic.asyncio.sleep", new=AsyncMock()) as sleep:
        with pytest.raises(CreateForumTopicException):
            await create_forum_topic(runtime.bot, runtime.config, "Client")
    assert len(runtime.api.named("createForumTopic")) == 3
    assert sleep.await_count == 2


async def test_large_retry_after_does_not_wait(runtime):
    runtime.api.failures["createForumTopic"] = [TelegramRetryAfter(
        method=CreateForumTopic(chat_id=GROUP, name="x"), message="limit", retry_after=60)]
    with patch("app.bot.utils.create_forum_topic.asyncio.sleep", new=AsyncMock()) as sleep:
        with pytest.raises(CreateForumTopicException):
            await create_forum_topic(runtime.bot, runtime.config, "Client")
    sleep.assert_not_awaited()


async def test_deleted_topic_is_replaced_and_old_index_removed(runtime):
    await runtime.redis.update_user(CLIENT, user(600))
    runtime.api.failures["forwardMessage"] = [TelegramBadRequest(
        method=ForwardMessage(chat_id=GROUP, from_chat_id=CLIENT, message_id=1),
        message="message thread not found")]
    await runtime.feed(private())
    assert await runtime.redis.get_by_message_thread_id(600) is None
    assert (await runtime.redis.get_by_message_thread_id(701)).id == CLIENT
    assert runtime.api.named("forwardMessage")[-1].message_thread_id == 701


async def test_bot_blocked_without_topic_is_recorded_without_group_message(runtime):
    event = ChatMemberUpdated(
        chat=Chat(id=CLIENT, type="private"), date=NOW,
        from_user=User(id=CLIENT, is_bot=False, first_name="Client"),
        old_chat_member=ChatMemberMember(user=User(id=42, is_bot=True, first_name="Support")),
        new_chat_member=ChatMemberBanned(user=User(id=42, is_bot=True, first_name="Support"), until_date=0),
    )
    await runtime.dp.feed_update(runtime.bot, Update(update_id=1, my_chat_member=event))
    current = await runtime.redis.get_user(CLIENT)
    assert current.message_thread_id is None and current.state == "kicked"
    assert not runtime.api.calls
    assert not await runtime.client.exists("users_index_None")


@pytest.mark.parametrize("service", ["closed", "pinned", "bot", "anonymous"])
async def test_service_bot_and_anonymous_messages_are_not_relayed(runtime, service):
    await runtime.redis.update_user(CLIENT, user(701))
    msg = group(text=None if service in ("closed", "pinned") else "Answer")
    if service == "closed":
        msg = msg.model_copy(update={"forum_topic_closed": ForumTopicClosed()})
    elif service == "pinned":
        msg = msg.model_copy(update={"pinned_message": private()})
    elif service == "bot":
        msg = msg.model_copy(update={"from_user": User(id=OPERATOR, is_bot=True, first_name="Bot")})
    else:
        msg = msg.model_copy(update={"sender_chat": Chat(id=GROUP, type="supergroup")})
    await runtime.feed(msg)
    assert not runtime.api.calls


async def test_edited_messages_are_not_relayed_or_creating_topics(runtime):
    await runtime.feed(private("Changed"), edited=True)
    await runtime.redis.update_fields(CLIENT, message_thread_id=701)
    await runtime.feed(group("Changed reply"), edited=True)
    assert not runtime.api.named("createForumTopic")
    assert not runtime.api.named("forwardMessage")
    assert not runtime.api.named("copyMessage")
    assert len(runtime.api.named("sendMessage")) == 2


@pytest.mark.parametrize("direction", ["private", "operator"])
async def test_mixed_album_preserves_order_captions_and_one_request(runtime, direction):
    photo = PhotoSize(file_id="photo", file_unique_id="p", width=10, height=10)
    video = Video(file_id="video", file_unique_id="v", width=10, height=10, duration=1)
    build = private if direction == "private" else group
    if direction == "operator":
        await runtime.redis.update_user(CLIENT, user(701))
    msg1 = build(text=None, message_id=1, media_group_id="album", photo=[photo], caption="<first>",
                 caption_entities=[MessageEntity(type="bold", offset=0, length=7)])
    msg2 = build(text=None, message_id=2, media_group_id="album", video=video, caption="second")
    await asyncio.gather(runtime.feed(msg2), runtime.feed(msg1))
    sent = runtime.api.named("sendMediaGroup")
    assert len(sent) == 1
    assert sent[0].chat_id == (GROUP if direction == "private" else CLIENT)
    assert [m.media for m in sent[0].media] == ["photo", "video"]
    assert [m.caption for m in sent[0].media] == ["<first>", "second"]
    assert sent[0].media[0].caption_entities[0].type == "bold"
    assert all(m.parse_mode is None for m in sent[0].media)
    assert not runtime.api.named("sendMessage")
    if direction == "private":
        assert await runtime.client.get(f"support:rate:messages:{CLIENT}") == b"1"


async def test_rate_limit_is_explicit_and_does_not_delete_original(runtime):
    runtime.config.bot.MESSAGES_PER_MINUTE = 1
    await runtime.feed(private())
    await runtime.feed(private("Second", message_id=2))
    assert len(runtime.api.named("forwardMessage")) == 1
    assert runtime.api.named("sendMessage")[-1].text == TextMessage("ru").get("rate_limited")
    assert not runtime.api.named("deleteMessage")
    assert await runtime.client.ttl(f"support:rate:messages:{CLIENT}") > 0


async def test_global_topic_rate_limit(runtime):
    runtime.config.bot.TOPICS_PER_MINUTE = 1
    await runtime.redis.update_user(CLIENT, user())
    await get_or_create_forum_topic(runtime.bot, runtime.redis, runtime.config, user())
    await runtime.redis.update_user(201, user(user_id=201))
    with pytest.raises(CreateForumTopicException):
        await get_or_create_forum_topic(runtime.bot, runtime.redis, runtime.config, user(user_id=201))
    assert len(runtime.api.named("createForumTopic")) == 1


async def test_created_at_uses_factory():
    from datetime import datetime
    with patch("app.bot.utils.redis.models.datetime") as clock:
        clock.now.return_value = datetime(2026, 1, 1)
        first = user()
        clock.now.return_value = datetime(2026, 1, 2)
        second = user()
    assert first.created_at != second.created_at


async def test_commands_have_no_newsletter_and_are_scoped(runtime):
    await commands.setup(runtime.bot, runtime.config)
    setters = runtime.api.named("setMyCommands")
    assert setters
    assert all(c.command != "newsletter" for m in setters for c in m.commands)
    for method in setters:
        if any(c.command == "ban" for c in method.commands):
            assert method.scope.chat_id == GROUP and method.scope.user_id == OPERATOR
    assert runtime.api.named("deleteMyCommands")


async def test_private_id_and_unknown_command_do_not_create_topics(runtime):
    await runtime.feed(private("/id"))
    assert str(CLIENT) in runtime.api.named("sendMessage")[-1].text
    await runtime.feed(private("/newsletter"))
    assert not runtime.api.named("createForumTopic")
    assert not runtime.api.named("forwardMessage")


async def test_failure_logs_do_not_contain_private_payload(runtime, caplog):
    secret_text = "private_payload_that_must_not_be_logged"
    runtime.api.failures["forwardMessage"] = [TelegramBadRequest(
        method=ForwardMessage(chat_id=GROUP, from_chat_id=CLIENT, message_id=1), message=secret_text)]
    await runtime.feed(private(secret_text))
    assert secret_text not in caplog.text
    assert "TelegramBadRequest" in caplog.text
