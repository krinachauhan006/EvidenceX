"""The single entry point for Gemini calls.

Stdlib HTTP only (no SDK dependency). Every call declares a Pydantic output schema;
the response is validated before anything uses it. On a validation failure the model
gets ONE repair attempt, then the call fails with ``AIOutputInvalidError``. Values are
never invented to satisfy a schema.

The API key travels only in a request header. It is never logged, never put into an
exception message and never returned.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)
Transport = Callable[[str, bytes, dict[str, str], float], bytes]

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
_MODEL_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MAX_ERROR_LINES = 8


class AIError(Exception):
    """A model call did not produce usable output."""


class AIUnavailableError(AIError):
    pass


class AIOutputInvalidError(AIError):
    pass


def _urllib_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        raise AIUnavailableError(f"the model service returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AIUnavailableError("the model service could not be reached") from None


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


class GeminiClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 60,
        transport: Transport | None = None,
    ) -> None:
        if not api_key:
            raise AIUnavailableError("GEMINI_API_KEY is not set")
        if not _MODEL_NAME.match(model):
            raise AIUnavailableError("GEMINI_MODEL is not a valid model name")
        self._api_key = api_key
        self.model = model
        self._timeout = float(timeout_seconds)
        self._transport = transport or _urllib_transport

    def _call(self, system: str, user: str) -> str:
        body = json.dumps(
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._api_key}
        raw = self._transport(
            f"{API_ROOT}/{self.model}:generateContent", body, headers, self._timeout
        )
        try:
            payload = json.loads(raw)
            parts = payload["candidates"][0]["content"]["parts"]
            return "".join(str(p.get("text", "")) for p in parts)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise AIOutputInvalidError("the model response had an unexpected shape") from None

    def generate(self, system: str, user: str, schema: type[T]) -> T:
        """Validated output, after at most one repair attempt."""
        text = self._call(system, user)
        try:
            return schema.model_validate_json(_strip_fences(text))
        except ValidationError as first:
            problems = "\n".join(
                f"- {'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                for e in first.errors()[:MAX_ERROR_LINES]
            )
            logger.info("model output failed validation; one repair attempt (model=%s)", self.model)
        repair = (
            f"{user}\n\nYour previous answer did not match the required JSON schema:\n"
            f"{problems}\nReturn ONLY corrected JSON. Do not invent values: omit a claim "
            "rather than guess."
        )
        text = self._call(system, repair)
        try:
            return schema.model_validate_json(_strip_fences(text))
        except ValidationError:
            raise AIOutputInvalidError("the model output failed validation twice") from None
