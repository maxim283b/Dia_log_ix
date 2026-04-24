from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        with self.session.no_autoflush:
            result = await self.session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
            return result.scalar_one_or_none()

    async def get_or_create_from_payload(self, payload: object) -> User:
        telegram_user_id = int(getattr(payload, "id"))
        user = await self.get_by_telegram_id(telegram_user_id)
        if user:
            user.username = getattr(payload, "username", None)
            user.first_name = getattr(payload, "first_name", None)
            user.last_name = getattr(payload, "last_name", None)
            user.is_bot = bool(getattr(payload, "is_bot", False))
            return user
        user = User(
            telegram_user_id=telegram_user_id,
            username=getattr(payload, "username", None),
            first_name=getattr(payload, "first_name", None),
            last_name=getattr(payload, "last_name", None),
            is_bot=bool(getattr(payload, "is_bot", False)),
        )
        self.session.add(user)
        try:
            await self.session.flush()
            return user
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get_by_telegram_id(telegram_user_id)
            if existing is None:
                raise
            existing.username = getattr(payload, "username", None)
            existing.first_name = getattr(payload, "first_name", None)
            existing.last_name = getattr(payload, "last_name", None)
            existing.is_bot = bool(getattr(payload, "is_bot", False))
            return existing
