from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.chat import Chat
from app.repositories.base import BaseRepository


class ChatRepository(BaseRepository):
    async def get_by_telegram_id(self, telegram_chat_id: int) -> Chat | None:
        with self.session.no_autoflush:
            result = await self.session.execute(select(Chat).where(Chat.telegram_chat_id == telegram_chat_id))
            return result.scalar_one_or_none()

    async def get_or_create_from_payload(self, payload: object) -> Chat:
        telegram_chat_id = int(getattr(payload, "id"))
        chat = await self.get_by_telegram_id(telegram_chat_id)
        if chat:
            chat.title = getattr(payload, "title", None)
            chat.type = getattr(payload, "type", "group")
            return chat
        chat = Chat(
            telegram_chat_id=telegram_chat_id,
            title=getattr(payload, "title", None),
            type=getattr(payload, "type", "group"),
        )
        self.session.add(chat)
        try:
            await self.session.flush()
            return chat
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get_by_telegram_id(telegram_chat_id)
            if existing is None:
                raise
            existing.title = getattr(payload, "title", None)
            existing.type = getattr(payload, "type", "group")
            return existing
