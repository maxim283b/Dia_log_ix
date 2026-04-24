from __future__ import annotations

from sqlalchemy import select

from app.models.digest_evaluation import DigestEvaluation
from app.repositories.base import BaseRepository


class DigestEvaluationRepository(BaseRepository):
    async def upsert(
        self,
        run_id: int,
        correctness: int,
        groundedness: int,
        completeness: int,
        coverage_of_required_fields: int,
        source_consistency: int,
        comment: str | None,
        raw_json: dict | None,
    ) -> DigestEvaluation:
        result = await self.session.execute(select(DigestEvaluation).where(DigestEvaluation.run_id == run_id))
        evaluation = result.scalar_one_or_none()
        if evaluation is None:
            evaluation = DigestEvaluation(
                run_id=run_id,
                correctness=correctness,
                groundedness=groundedness,
                completeness=completeness,
                coverage_of_required_fields=coverage_of_required_fields,
                source_consistency=source_consistency,
                comment=comment,
                raw_json=raw_json,
            )
            self.session.add(evaluation)
            return evaluation
        evaluation.correctness = correctness
        evaluation.groundedness = groundedness
        evaluation.completeness = completeness
        evaluation.coverage_of_required_fields = coverage_of_required_fields
        evaluation.source_consistency = source_consistency
        evaluation.comment = comment
        evaluation.raw_json = raw_json
        return evaluation

