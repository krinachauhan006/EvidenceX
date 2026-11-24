"""Which speech models are on disk, without loading or downloading anything.

A model is "available" only when its local snapshot holds a non-empty ``model.bin``
and a ``config.json``. Only available models can be selected for a run; a missing
model is reported, never silently replaced by another one.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.modules.processing.extractors.audio import resolve_model_dir

_FOLDER = re.compile(r"^models--(?P<org>[^-][\w.-]*?)--(?P<repo>[\w.-]+)$")
NAME_PATTERN = r"^[A-Za-z0-9._-]{1,64}$"


@dataclass(frozen=True)
class LocalModel:
    name: str  # the WHISPER_MODEL_SIZE value, e.g. "small"
    repo: str  # e.g. "Systran/faster-whisper-small"
    available: bool
    size_bytes: int | None
    problem: str | None = None


def _known_names() -> dict[str, str]:
    """repo id -> model name, from faster-whisper's own table when installed."""
    try:
        from faster_whisper.utils import _MODELS  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - optional; folder names are the fallback
        return {}
    return {str(repo): str(name) for name, repo in dict(_MODELS).items()}


def _snapshot_state(folder: Path) -> tuple[bool, int | None, str | None]:
    snapshots = folder / "snapshots"
    if not snapshots.is_dir():
        return False, None, "no snapshot folder"
    for snap in sorted(snapshots.iterdir()):
        model_bin, config = snap / "model.bin", snap / "config.json"
        if model_bin.is_file() and config.is_file() and os.path.getsize(model_bin) > 0:
            return True, os.path.getsize(model_bin), None
    return False, None, "incomplete download (model.bin or config.json missing)"


def list_local_models(model_dir: str) -> list[LocalModel]:
    root = resolve_model_dir(model_dir)
    if not root.is_dir():
        return []
    known = _known_names()
    found: list[LocalModel] = []
    for folder in sorted(root.iterdir()):
        m = _FOLDER.match(folder.name)
        if not folder.is_dir() or not m or "whisper" not in folder.name.lower():
            continue
        repo = f"{m.group('org')}/{m.group('repo')}"
        name = known.get(repo) or m.group("repo").removeprefix("faster-whisper-")
        available, size, problem = _snapshot_state(folder)
        found.append(LocalModel(name, repo, available, size, problem))
    return found


def available_model_names(model_dir: str) -> set[str]:
    return {m.name for m in list_local_models(model_dir) if m.available}
