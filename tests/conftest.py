from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.chat import Chat
from app.models.message import Message
from app.models.user import User


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_async_engine(database_url, future=True, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session


async def seed_user_chat(session: AsyncSession, *, chat_id: int = 1001, user_id: int = 2001, bot: bool = False) -> tuple[Chat, User]:
    chat = Chat(telegram_chat_id=chat_id, title="Test chat", type="group")
    user = User(
        telegram_user_id=user_id,
        username="tester" if not bot else "bot",
        first_name="Test",
        last_name="User",
        is_bot=bot,
    )
    session.add_all([chat, user])
    await session.flush()
    return chat, user


async def seed_message(
    session: AsyncSession,
    *,
    chat: Chat,
    user: User,
    telegram_message_id: int,
    text: str | None = None,
    is_command: bool = False,
    message_type: str = "text",
) -> Message:
    message = Message(
        chat_id=chat.id,
        user_id=user.id,
        telegram_message_id=telegram_message_id,
        date=datetime.now(timezone.utc),
        message_type=message_type,
        text=text,
        file_id=None,
        transcribed_text=None,
        is_command=is_command,
        raw_json={},
    )
    session.add(message)
    await session.flush()
    return message
