from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from aiogram.types import Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.api.schemas import AgentRunResponse, AgentTraceResponse, HealthResponse
from app.models.agent_run import AgentRun
from app.models.agent_trace import AgentTrace

api_router = APIRouter()


@api_router.get("/health", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    return HealthResponse(status="ok")


@api_router.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict:
    bot = request.app.state.bot
    dispatcher = request.app.state.dispatcher
    payload = await request.json()
    update = Update.model_validate(payload)
    await dispatcher.feed_update(bot, update)
    return {"ok": True}


@api_router.get("/agent-runs", response_model=list[AgentRunResponse])
async def get_recent_runs(
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
) -> list[AgentRunResponse]:
    result = await session.execute(select(AgentRun).order_by(AgentRun.id.desc()).limit(limit))
    runs = result.scalars().all()
    return [
        AgentRunResponse.model_validate(run, from_attributes=True)
        for run in runs
    ]


@api_router.get("/agent-runs/{run_id}/trace", response_model=list[AgentTraceResponse])
async def get_run_trace(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[AgentTraceResponse]:
    result = await session.execute(
        select(AgentTrace).where(AgentTrace.run_id == run_id).order_by(AgentTrace.step_id.asc())
    )
    traces = result.scalars().all()
    if not traces:
        run_exists = await session.execute(select(AgentRun.id).where(AgentRun.id == run_id))
        if run_exists.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Run not found")
    return [AgentTraceResponse.model_validate(trace, from_attributes=True) for trace in traces]
