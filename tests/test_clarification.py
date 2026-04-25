from __future__ import annotations

from app.utils.digest import build_clarification_prompt


def test_build_clarification_prompt_contains_digest_and_question() -> None:
    prompt = build_clarification_prompt(
        digest="Сводка: Максим обсуждает поездку и планы.",
        question="Кто куда едет?",
        messages=[
            {
                "date": "2026-04-24T10:00:00+00:00",
                "author_display_name": "Максим",
                "text": "Мы едем к родственникам",
            }
        ],
    )

    assert "Сводка: Максим обсуждает поездку и планы." in prompt
    assert "Кто куда едет?" in prompt
    assert "Максим" in prompt
