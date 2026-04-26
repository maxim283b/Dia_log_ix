from __future__ import annotations

import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.evaluator import DigestEvaluator
from app.agent.state import AgentState
from app.agent.tools import AgentTools
from app.models.agent_run import AgentRun
from app.models.agent_trace import AgentTrace
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.digests import DigestEvaluationRepository
from app.repositories.messages import MessageRepository
from app.utils.time import utc_now


logger = logging.getLogger(__name__)


class TraceRecorder:
    def __init__(self, session: AsyncSession, run: AgentRun) -> None:
        self.session = session
        self.run = run
        self.step_id = 0

    async def save(
        self,
        *,
        action: str,
        input_json: dict | None,
        output_json: dict | None,
        latency_ms: int,
        status: str,
        error: str | None = None,
        reason_next_step: str | None = None,
    ) -> AgentTrace:
        self.step_id += 1
        trace = AgentTrace(
            run_id=self.run.id,
            step_id=self.step_id,
            action=action,
            input_json=input_json,
            output_json=output_json,
            latency_ms=latency_ms,
            status=status,
            error=error,
            reason_next_step=reason_next_step,
        )
        self.session.add(trace)
        history = self.run.history or []
        history.append(
            {
                "step_id": self.step_id,
                "action": action,
                "status": status,
                "reason_next_step": reason_next_step,
            }
        )
        self.run.history = history
        return trace


class BaselineRunner:
    def __init__(
        self,
        *,
        session: AsyncSession,
        message_repository: MessageRepository,
        run_repository: AgentRunRepository,
        tools: AgentTools,
        evaluator: DigestEvaluator,
    ) -> None:
        self.session = session
        self.message_repository = message_repository
        self.run_repository = run_repository
        self.tools = tools
        self.evaluator = evaluator

    async def run(
        self,
        *,
        chat_id: int,
        chat_telegram_id: int | None = None,
        user_id: int,
        objective: str,
        start_message_id: int,
        end_message_id: int,
    ) -> AgentRun:
        logger.info(
            "Baseline run started: chat_id=%s chat_telegram_id=%s user_id=%s start_message_id=%s end_message_id=%s",
            chat_id,
            chat_telegram_id,
            user_id,
            start_message_id,
            end_message_id,
        )
        run = await self.run_repository.create(
            chat_id=chat_id,
            chat_telegram_id=chat_telegram_id,
            user_id=user_id,
            objective=objective,
            mode="baseline",
            start_message_id=start_message_id,
            end_message_id=end_message_id,
            status="running",
            history=[],
        )
        await self.session.flush()
        messages = await self.message_repository.get_messages_from(chat_id, max(0, start_message_id), end_message_id)
        logger.info("Baseline run collected messages: count=%s", len(messages))
        await self.tools.transcribe_media_messages(messages)
        if not messages:
            digest = (
                "Недостаточно данных для осмысленного дайджеста. "
                "В выбранном окне сообщений нет или они слишком короткие."
            )
            evaluation = await self._safe_evaluate(digest=digest, source_messages=[])
            run.collected_messages = []
            run.transcriptions = []
            run.final_digest = digest
            run.status = "completed"
            run.stop_reason = "insufficient_data"
            run.finished_at = utc_now()
            await self.session.flush()
            evaluation_repo = DigestEvaluationRepository(self.session)
            await evaluation_repo.upsert(
                run_id=run.id,
                correctness=evaluation.correctness,
                groundedness=evaluation.groundedness,
                completeness=evaluation.completeness,
                coverage_of_required_fields=evaluation.coverage_of_required_fields,
                source_consistency=evaluation.source_consistency,
                comment=evaluation.comment,
                raw_json=evaluation.raw_json,
            )
            return run
        logger.info("Baseline run generating digest")
        digest = await self.tools.generate_digest(
            state=AgentState(objective=objective, chat_id=chat_id, user_id=user_id),
            messages=messages,
        )
        evaluation = await self._safe_evaluate(
            digest=digest,
            source_messages=self.tools.serialize_messages(messages),
        )
        run.collected_messages = self.tools.serialize_messages(messages)
        run.transcriptions = [
            {"telegram_message_id": m.telegram_message_id, "transcribed_text": m.transcribed_text}
            for m in messages
            if m.transcribed_text
        ]
        run.final_digest = digest
        run.status = "completed"
        run.stop_reason = "completed"
        run.finished_at = utc_now()
        deleted = await self.message_repository.delete_messages_before(chat_id, end_message_id)
        logger.info("Baseline run cleaned up source messages: deleted=%s chat_id=%s before_message_id=%s", deleted, chat_id, end_message_id)
        await self.session.flush()
        logger.info("Baseline run completed: run_id=%s digest_len=%s", run.id, len(digest or ""))
        evaluation_repo = DigestEvaluationRepository(self.session)
        await evaluation_repo.upsert(
            run_id=run.id,
            correctness=evaluation.correctness,
            groundedness=evaluation.groundedness,
            completeness=evaluation.completeness,
            coverage_of_required_fields=evaluation.coverage_of_required_fields,
            source_consistency=evaluation.source_consistency,
            comment=evaluation.comment,
            raw_json=evaluation.raw_json,
        )
        return run

    async def _safe_evaluate(self, *, digest: str, source_messages: list[dict]) -> object:
        try:
            return await self.evaluator.evaluate(digest=digest, source_messages=source_messages)
        except Exception as exc:
            return type(
                "EvaluationFallback",
                (),
                {
                    "correctness": 0,
                    "groundedness": 0,
                    "completeness": 0,
                    "coverage_of_required_fields": 0,
                    "source_consistency": 0,
                    "comment": f"Evaluation skipped due to error: {exc}",
                    "raw_json": {"error": str(exc), "fallback": True},
                },
            )()


class AgentRunner:
    def __init__(
        self,
        *,
        session: AsyncSession,
        tools: AgentTools,
        run_repository: AgentRunRepository,
        evaluator: DigestEvaluator,
    ) -> None:
        self.session = session
        self.tools = tools
        self.run_repository = run_repository
        self.evaluator = evaluator

    async def run(
        self,
        *,
        chat_id: int,
        chat_telegram_id: int | None = None,
        user_id: int,
        objective: str,
        start_message_id: int,
        end_message_id: int,
    ) -> AgentRun:
        logger.info(
            "Agent run started: chat_id=%s chat_telegram_id=%s user_id=%s start_message_id=%s end_message_id=%s",
            chat_id,
            chat_telegram_id,
            user_id,
            start_message_id,
            end_message_id,
        )
        run = await self.run_repository.create(
            chat_id=chat_id,
            chat_telegram_id=chat_telegram_id,
            user_id=user_id,
            objective=objective,
            mode="agent",
            start_message_id=start_message_id,
            end_message_id=end_message_id,
            status="running",
            history=[],
        )
        await self.session.flush()
        tracer = TraceRecorder(self.session, run)
        state = AgentState(objective=objective, chat_id=chat_id, user_id=user_id, start_message_id=start_message_id, end_message_id=end_message_id)
        try:
            effective_start_message_id = max(0, start_message_id)
            t0 = time.perf_counter()
            last_message = await self.tools.get_last_user_message(
                chat_id=chat_id,
                user_id=user_id,
                before_message_id=end_message_id,
            )
            latency = int((time.perf_counter() - t0) * 1000)
            state.start_message_id = last_message.telegram_message_id if last_message else start_message_id
            logger.info(
                "Step get_last_user_message completed: run_pending=%s last_message_id=%s",
                run.id,
                getattr(last_message, "telegram_message_id", None),
            )
            await tracer.save(
                action="get_last_user_message",
                input_json={"chat_id": chat_id, "user_id": user_id, "before_message_id": end_message_id},
                output_json={"telegram_message_id": getattr(last_message, "telegram_message_id", None)},
                latency_ms=latency,
                status="ok",
                reason_next_step="collect_messages",
            )

            t0 = time.perf_counter()
            collected = await self.tools.get_messages_from(
                chat_id=chat_id,
                start_message_id=effective_start_message_id,
                before_message_id=end_message_id,
            )
            latency = int((time.perf_counter() - t0) * 1000)
            state.collected_messages = self.tools.serialize_messages(collected)
            state.participants = self.tools.serialize_participants(collected)
            logger.info("Step get_messages_from completed: count=%s participants=%s", len(collected), len(state.participants))
            await tracer.save(
                action="get_messages_from",
                input_json={"chat_id": chat_id, "start_message_id": state.start_message_id, "before_message_id": end_message_id},
                output_json={"count": len(collected), "participants": state.participants},
                latency_ms=latency,
                status="ok",
                reason_next_step="transcribe_media",
            )

            if not collected:
                logger.warning("Agent run has no collected messages; returning insufficient_data digest")
                digest = (
                    "Недостаточно данных для осмысленного дайджеста. "
                    "В выбранном окне сообщений нет или они слишком короткие."
                )
                evaluation = await self._safe_evaluate(digest=digest, source_messages=[])
                await tracer.save(
                    action="insufficient_data",
                    input_json={"chat_id": chat_id, "start_message_id": effective_start_message_id, "before_message_id": end_message_id},
                    output_json={"digest": digest},
                    latency_ms=0,
                    status="ok",
                    reason_next_step="stop",
                )
                run.collected_messages = []
                run.transcriptions = []
                run.grouped_topics = []
                run.decisions = []
                run.tasks = []
                run.final_digest = digest
                run.status = "completed"
                run.stop_reason = "insufficient_data"
                run.finished_at = utc_now()
                evaluation_repo = DigestEvaluationRepository(self.session)
                await evaluation_repo.upsert(
                    run_id=run.id,
                    correctness=evaluation.correctness,
                    groundedness=evaluation.groundedness,
                    completeness=evaluation.completeness,
                    coverage_of_required_fields=evaluation.coverage_of_required_fields,
                    source_consistency=evaluation.source_consistency,
                    comment=evaluation.comment,
                    raw_json=evaluation.raw_json,
                )
                return run

            t0 = time.perf_counter()
            transcriptions = await self.tools.transcribe_media_messages(collected)
            latency = int((time.perf_counter() - t0) * 1000)
            state.transcriptions = transcriptions
            logger.info("Step transcribe_media_messages completed: count=%s", len(transcriptions))
            await tracer.save(
                action="transcribe_media_messages",
                input_json={"count": len(collected)},
                output_json={"count": len(transcriptions)},
                latency_ms=latency,
                status="ok",
                reason_next_step="group_messages_by_topic",
            )

            t0 = time.perf_counter()
            grouped_topics = await self.tools.group_messages_by_topic(collected)
            latency = int((time.perf_counter() - t0) * 1000)
            state.grouped_topics = grouped_topics
            logger.info("Step group_messages_by_topic completed: topics=%s latency_ms=%s", len(grouped_topics), latency)
            await tracer.save(
                action="group_messages_by_topic",
                input_json={"count": len(collected)},
                output_json={"topics": grouped_topics},
                latency_ms=latency,
                status="ok",
                reason_next_step="extract_decisions",
            )

            t0 = time.perf_counter()
            decisions = await self.tools.extract_decisions(collected)
            latency = int((time.perf_counter() - t0) * 1000)
            state.decisions = decisions
            logger.info("Step extract_decisions completed: decisions=%s latency_ms=%s", len(decisions), latency)
            await tracer.save(
                action="extract_decisions",
                input_json={"count": len(collected)},
                output_json={"decisions": decisions},
                latency_ms=latency,
                status="ok",
                reason_next_step="extract_tasks",
            )

            t0 = time.perf_counter()
            tasks = await self.tools.extract_tasks(collected)
            latency = int((time.perf_counter() - t0) * 1000)
            state.tasks = tasks
            logger.info("Step extract_tasks completed: tasks=%s latency_ms=%s", len(tasks), latency)
            await tracer.save(
                action="extract_tasks",
                input_json={"count": len(collected)},
                output_json={"tasks": tasks},
                latency_ms=latency,
                status="ok",
                reason_next_step="extract_open_questions",
            )

            t0 = time.perf_counter()
            open_questions = await self.tools.extract_open_questions(collected)
            latency = int((time.perf_counter() - t0) * 1000)
            state.open_questions = open_questions
            logger.info("Step extract_open_questions completed: open_questions=%s latency_ms=%s", len(open_questions), latency)
            await tracer.save(
                action="extract_open_questions",
                input_json={"count": len(collected)},
                output_json={"open_questions": open_questions},
                latency_ms=latency,
                status="ok",
                reason_next_step="generate_digest",
            )

            t0 = time.perf_counter()
            digest = await self.tools.generate_digest(state=state, messages=collected)
            latency = int((time.perf_counter() - t0) * 1000)
            state.final_digest = digest
            logger.info("Step generate_digest completed: digest_len=%s latency_ms=%s", len(digest or ""), latency)
            await tracer.save(
                action="generate_digest",
                input_json={"topics": grouped_topics, "decisions": decisions, "tasks": tasks, "open_questions": open_questions},
                output_json={"digest": digest},
                latency_ms=latency,
                status="ok",
                reason_next_step="evaluate_digest",
            )

            evaluation = await self._safe_evaluate(
                digest=digest,
                source_messages=state.collected_messages,
            )
            logger.info("Step evaluate_digest completed")
            evaluation_repo = DigestEvaluationRepository(self.session)
            await evaluation_repo.upsert(
                run_id=run.id,
                correctness=evaluation.correctness,
                groundedness=evaluation.groundedness,
                completeness=evaluation.completeness,
                coverage_of_required_fields=evaluation.coverage_of_required_fields,
                source_consistency=evaluation.source_consistency,
                comment=evaluation.comment,
                raw_json=evaluation.raw_json,
            )
            await tracer.save(
                action="evaluate_digest",
                input_json={"digest": digest},
                output_json=evaluation.raw_json or {},
                latency_ms=0,
                status="ok",
                reason_next_step="finish",
            )

            run.collected_messages = state.collected_messages
            run.transcriptions = state.transcriptions
            run.grouped_topics = grouped_topics
            run.decisions = decisions
            run.tasks = tasks
            run.final_digest = digest
            run.status = "completed"
            run.stop_reason = "completed"
            run.finished_at = utc_now()
            deleted = await self.tools.message_repository.delete_messages_before(chat_id, end_message_id)
            logger.info(
                "Agent run cleaned up source messages: deleted=%s chat_id=%s before_message_id=%s",
                deleted,
                chat_id,
                end_message_id,
            )
            logger.info("Agent run completed: run_id=%s", run.id)
            return run
        except Exception as exc:
            logger.exception("Agent run failed: chat_id=%s user_id=%s", chat_id, user_id)
            await tracer.save(
                action="runner_error",
                input_json={"objective": objective},
                output_json=None,
                latency_ms=0,
                status="error",
                error=str(exc),
                reason_next_step="stop",
            )
            run.status = "failed"
            run.stop_reason = str(exc)
            run.finished_at = utc_now()
            raise

    async def _safe_evaluate(self, *, digest: str, source_messages: list[dict]) -> object:
        try:
            return await self.evaluator.evaluate(digest=digest, source_messages=source_messages)
        except Exception as exc:
            return type(
                "EvaluationFallback",
                (),
                {
                    "correctness": 0,
                    "groundedness": 0,
                    "completeness": 0,
                    "coverage_of_required_fields": 0,
                    "source_consistency": 0,
                    "comment": f"Evaluation skipped due to error: {exc}",
                    "raw_json": {"error": str(exc), "fallback": True},
                },
            )()
