from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class AgentRunResponse(BaseModel):
    id: int
    chat_id: int
    user_id: int
    objective: str
    mode: str
    status: str
    stop_reason: str | None = None
    final_digest: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class AgentTraceResponse(BaseModel):
    id: int
    run_id: int
    step_id: int
    action: str
    input_json: dict | None = None
    output_json: dict | None = None
    latency_ms: int
    status: str
    error: str | None = None
    reason_next_step: str | None = None
    created_at: datetime

