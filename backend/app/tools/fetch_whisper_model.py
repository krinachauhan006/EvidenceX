"""Explicit speech-model download. Never run automatically.

    python -m app.tools.fetch_whisper_model --size base

Prints the approximate download size and asks for confirmation (``--yes`` skips the
prompt). Files go to WHISPER_MODEL_DIR. Nothing is downloaded without the confirmation.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from app.core.config import get_settings

APPROX_SIZE_MB = {"tiny": 75, "base": 145, "small": 480, "medium": 1500}


def confirm_download(
    size: str, directory: str, assume_yes: bool, ask: Callable[[str], str]
) -> bool:
    approx = APPROX_SIZE_MB.get(size)
    where = f"about {approx} MB" if approx else "an unknown size"
    print(f"This downloads the '{size}' speech model ({where}) into {directory}.")
    if assume_yes:
        return True
    return ask("Continue? [y/N] ").strip().lower() in ("y", "yes")


def main(
    argv: Sequence[str] | None = None,
    *,
    ask: Callable[[str], str] = input,
    download: Callable[[str, str], str] | None = None,
) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Download a faster-whisper model.")
    parser.add_argument("--size", default=settings.whisper_model_size)
    parser.add_argument("--dir", default=settings.whisper_model_dir)
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args(argv)
    # Same resolution as the backend: a relative folder is taken from backend/, not
    # from wherever this command happens to be run.
    from app.modules.processing.extractors.audio import resolve_model_dir

    args.dir = str(resolve_model_dir(args.dir))

    if not confirm_download(args.size, args.dir, args.yes, ask):
        print("Cancelled. Nothing was downloaded.")
        return 1
    if download is None:
        try:
            from faster_whisper.utils import download_model
        except ImportError:
            print("faster-whisper is not installed.", file=sys.stderr)
            return 2

        def download(size: str, directory: str) -> str:
            return download_model(size, output_dir=None, cache_dir=directory)

    path = download(args.size, args.dir)
    print(f"Model ready: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
