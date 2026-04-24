from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_chat_telegram_msg", "chat_id", "telegram_message_id", unique=True),
        Index("ix_messages_chat_user_msg", "chat_id", "user_id", "telegram_message_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    message_type: Mapped[str] = mapped_column(String(32))
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    transcribed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_command: Mapped[bool] = mapped_column(default=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    chat: Mapped["Chat"] = relationship(back_populates="messages")
    user: Mapped["User | None"] = relationship(back_populates="messages")

