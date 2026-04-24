from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils.time import utc_now


class DigestEvaluation(Base):
    __tablename__ = "digest_evaluations"
    __table_args__ = (UniqueConstraint("run_id", name="uq_digest_evaluations_run_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    correctness: Mapped[int] = mapped_column(Integer, default=0)
    groundedness: Mapped[int] = mapped_column(Integer, default=0)
    completeness: Mapped[int] = mapped_column(Integer, default=0)
    coverage_of_required_fields: Mapped[int] = mapped_column(Integer, default=0)
    source_consistency: Mapped[int] = mapped_column(Integer, default=0)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["AgentRun"] = relationship(back_populates="evaluation")
