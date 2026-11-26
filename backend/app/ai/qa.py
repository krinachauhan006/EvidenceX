"""Grounded question answering and case briefs.

The model only sees numbered excerpts (inside data delimiters) and must cite them.
Locally, every statement is checked: citations must name a provided ref, statements
without a valid citation are removed (and counted), and wording that adjudicates
(guilt, lying, authenticity) is removed. When AI is not available or not allowed,
the answer is retrieval-only: the most relevant source passages, quoted verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.ai.gemini_client import GeminiClient
from app.modules.analysis.report_text import BANNED

ASK_PROMPT = (Path(__file__).parent / "prompts" / "ask_v1.txt").read_text("utf-8")
BRIEF_PROMPT = (Path(__file__).parent / "prompts" / "brief_v1.txt").read_text("utf-8")


class LlmStatement(BaseModel):
    text: str = Field(min_length=1, max_length=800)
    citations: list[str] = Field(default_factory=list, max_length=10)
    support: Literal["supported", "interpretation", "unknown"]


class LlmStatements(BaseModel):
    statements: list[LlmStatement] = Field(max_length=20)


def _payload(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False).replace("<", "\\u003c")


def validate_statements(
    statements: list[LlmStatement], allowed_refs: set[str]
) -> tuple[list[dict], int]:
    kept, removed = [], 0
    for s in statements:
        refs = [r for r in s.citations if r in allowed_refs]
        if not refs or BANNED.search(s.text):
            removed += 1
            continue
        kept.append({"text": s.text.strip(), "citations": refs, "support": s.support})
    return kept, removed


def ask(client: GeminiClient, question: str, sources: list[dict]) -> tuple[list[dict], int]:
    """sources: [{"ref": "S1", "text": "...", "where": "..."}]"""
    user = (
        f"Question: {json.dumps(question, ensure_ascii=False)}\n"
        f"<sources>\n{_payload(sources)}\n</sources>"
    )
    result = client.generate(ASK_PROMPT, user, LlmStatements)
    return validate_statements(result.statements, {s["ref"] for s in sources})


def brief(client: GeminiClient, findings: list[dict]) -> tuple[list[dict], int]:
    user = f"<findings>\n{_payload(findings)}\n</findings>"
    result = client.generate(BRIEF_PROMPT, user, LlmStatements)
    return validate_statements(result.statements, {f["ref"] for f in findings})
