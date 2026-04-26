from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, delete, select
from sqlalchemy.orm import selectinload

from app.models.message import Message
from app.models.user import User
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository):
    async def create(self, **values: Any) -> Message:
        message = Message(**values)
        self.session.add(message)
        return message

    async def get_last_user_message_before(
        self,
        chat_id: int,
        user_id: int,
        before_telegram_message_id: int,
    ) -> Message | None:
        result = await self.session.execute(
            select(Message)
            .options(selectinload(Message.user))
            .join(User, Message.user_id == User.id, isouter=True)
            .where(
                Message.chat_id == chat_id,
                Message.user_id == user_id,
                Message.telegram_message_id < before_telegram_message_id,
                Message.is_command.is_(False),
                User.is_bot.is_(False),
            )
            .order_by(Message.telegram_message_id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_messages_after(
        self,
        chat_id: int,
        start_telegram_message_id: int,
        before_telegram_message_id: int | None = None,
    ) -> list[Message]:
        stmt: Select[tuple[Message]] = select(Message).where(
            Message.chat_id == chat_id,
            Message.telegram_message_id > start_telegram_message_id,
            Message.is_command.is_(False),
        )
        stmt = stmt.options(selectinload(Message.user))
        stmt = stmt.join(User, Message.user_id == User.id, isouter=True).where(User.is_bot.is_(False))
        if before_telegram_message_id is not None:
            stmt = stmt.where(Message.telegram_message_id < before_telegram_message_id)
        stmt = stmt.order_by(Message.telegram_message_id.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_messages_from(
        self,
        chat_id: int,
        start_telegram_message_id: int,
        before_telegram_message_id: int | None = None,
    ) -> list[Message]:
        stmt: Select[tuple[Message]] = select(Message).where(
            Message.chat_id == chat_id,
            Message.telegram_message_id >= start_telegram_message_id,
            Message.is_command.is_(False),
        )
        stmt = stmt.options(selectinload(Message.user))
        stmt = stmt.join(User, Message.user_id == User.id, isouter=True).where(User.is_bot.is_(False))
        if before_telegram_message_id is not None:
            stmt = stmt.where(Message.telegram_message_id < before_telegram_message_id)
        stmt = stmt.order_by(Message.telegram_message_id.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_messages_between(
        self,
        chat_id: int,
        start_telegram_message_id: int,
        end_telegram_message_id: int,
    ) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .options(selectinload(Message.user))
            .join(User, Message.user_id == User.id, isouter=True)
            .where(
                Message.chat_id == chat_id,
                Message.telegram_message_id > start_telegram_message_id,
                Message.telegram_message_id < end_telegram_message_id,
                Message.is_command.is_(False),
                User.is_bot.is_(False),
            )
            .order_by(Message.telegram_message_id.asc())
        )
        return list(result.scalars().all())

    async def get_or_create_by_telegram_message_id(self, chat_id: int, telegram_message_id: int) -> Message | None:
        result = await self.session.execute(
            select(Message).where(
                Message.chat_id == chat_id,
                Message.telegram_message_id == telegram_message_id,
            )
        )
        return result.scalar_one_or_none()

    async def delete_messages_before(self, chat_id: int, before_telegram_message_id: int) -> int:
        result = await self.session.execute(
            delete(Message).where(
                Message.chat_id == chat_id,
                Message.telegram_message_id < before_telegram_message_id,
            )
        )
        return int(result.rowcount or 0)
