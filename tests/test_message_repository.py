from __future__ import annotations

import pytest

from app.models.user import User
from app.repositories.messages import MessageRepository
from tests.conftest import seed_message, seed_user_chat


@pytest.mark.asyncio
async def test_last_user_message_before(session):
    chat, user = await seed_user_chat(session)
    other_chat, bot_user = await seed_user_chat(session, chat_id=2002, user_id=3002, bot=True)
    await seed_message(session, chat=chat, user=user, telegram_message_id=1, text="one")
    await seed_message(session, chat=chat, user=user, telegram_message_id=2, text="two")
    await seed_message(session, chat=chat, user=user, telegram_message_id=3, text="/digest", is_command=True)
    await seed_message(session, chat=chat, user=user, telegram_message_id=4, text="four")
    await seed_message(session, chat=other_chat, user=bot_user, telegram_message_id=5, text="bot", message_type="text")
    await session.commit()

    repo = MessageRepository(session)
    result = await repo.get_last_user_message_before(chat.id, user.id, before_telegram_message_id=5)

    assert result is not None
    assert result.telegram_message_id == 4


@pytest.mark.asyncio
async def test_get_messages_after_excludes_commands_and_bot_messages(session):
    chat, user = await seed_user_chat(session)
    bot_user = User(
        telegram_user_id=9999,
        username="bot",
        first_name="Bot",
        last_name="User",
        is_bot=True,
    )
    session.add(bot_user)
    await session.flush()
    await seed_message(session, chat=chat, user=user, telegram_message_id=1, text="start")
    await seed_message(session, chat=chat, user=user, telegram_message_id=2, text="first")
    await seed_message(session, chat=chat, user=bot_user, telegram_message_id=3, text="bot reply")
    await seed_message(session, chat=chat, user=user, telegram_message_id=4, text="/help", is_command=True)
    await seed_message(session, chat=chat, user=user, telegram_message_id=5, text="second")
    await session.commit()

    repo = MessageRepository(session)
    result = await repo.get_messages_after(chat.id, start_telegram_message_id=1, before_telegram_message_id=6)

    assert [message.telegram_message_id for message in result] == [2, 5]


@pytest.mark.asyncio
async def test_get_messages_from_includes_start_message(session):
    chat, user = await seed_user_chat(session)
    await seed_message(session, chat=chat, user=user, telegram_message_id=1, text="first")
    await seed_message(session, chat=chat, user=user, telegram_message_id=2, text="second")
    await seed_message(session, chat=chat, user=user, telegram_message_id=3, text="/digest", is_command=True)
    await session.commit()

    repo = MessageRepository(session)
    result = await repo.get_messages_from(chat.id, start_telegram_message_id=1, before_telegram_message_id=3)

    assert [message.telegram_message_id for message in result] == [1, 2]
