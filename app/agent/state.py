from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AgentState:
    objective: str
    chat_id: int
    user_id: int
    start_message_id: int | None = None
    end_message_id: int | None = None
    collected_messages: list[dict] = field(default_factory=list)
    transcriptions: list[dict] = field(default_factory=list)
    participants: list[dict] = field(default_factory=list)
    grouped_topics: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    tasks: list[dict] = field(default_factory=list)
    open_questions: list[dict] = field(default_factory=list)
    final_digest: str | None = None
    status: str = "running"
    stop_reason: str | None = None
    history: list[dict] = field(default_factory=list)
