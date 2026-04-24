from __future__ import annotations

from sqlalchemy import select

from app.models.agent_run import AgentRun
from app.repositories.base import BaseRepository
from app.utils.time import utc_now


class AgentRunRepository(BaseRepository):
    async def create(self, **values) -> AgentRun:
        run = AgentRun(**values)
        self.session.add(run)
        return run

    async def get_recent(self, chat_id: int | None = None, limit: int = 20) -> list[AgentRun]:
        stmt = select(AgentRun).order_by(AgentRun.id.desc()).limit(limit)
        if chat_id is not None:
            stmt = stmt.where(AgentRun.chat_id == chat_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, run_id: int) -> AgentRun | None:
        result = await self.session.execute(select(AgentRun).where(AgentRun.id == run_id))
        return result.scalar_one_or_none()

    async def get_latest_completed(self, chat_id: int) -> AgentRun | None:
        result = await self.session.execute(
            select(AgentRun)
            .where(AgentRun.chat_id == chat_id, AgentRun.status == "completed")
            .order_by(AgentRun.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_finished(self, run: AgentRun, status: str, stop_reason: str | None = None) -> AgentRun:
        run.status = status
        run.stop_reason = stop_reason
        run.finished_at = utc_now()
        return run
