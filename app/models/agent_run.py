from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils.time import utc_now


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    chat_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    objective: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(32))
    start_message_id: Mapped[int | None] = mapped_column(nullable=True)
    end_message_id: Mapped[int | None] = mapped_column(nullable=True)
    collected_messages: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    transcriptions: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    grouped_topics: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    decisions: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    tasks: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    final_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    stop_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    history: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chat: Mapped["Chat"] = relationship(back_populates="runs")
    user: Mapped["User"] = relationship(back_populates="runs")
    traces: Mapped[list["AgentTrace"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    evaluation: Mapped["DigestEvaluation | None"] = relationship(back_populates="run", uselist=False)
