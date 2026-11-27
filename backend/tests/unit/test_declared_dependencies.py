"""Every third-party package the application imports is declared in pyproject.toml.

Regression for the prepared-dataset audit: graph_export.py imports networkx, which was
installed only because pymupdf happened to depend on it. A deployment that installs
exactly the declared dependencies (Vercel) must not rely on that.

A module counts as declared if its distribution is listed directly (base dependencies
or an optional extra), or is listed in INDIRECT with the declared package that provides
it; the test then checks that the declared package really requires it."""

from __future__ import annotations

import ast
import importlib.metadata as md
import re
import sys
import tomllib
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"

# Imported module -> the declared distribution that brings it in.
INDIRECT = {
    "botocore": "boto3",  # boto3's own exception/config types
    "starlette": "fastapi",  # FastAPI is built on Starlette
    "av": "faster-whisper",  # audio extra (PyAV decodes audio/video)
    "numpy": "faster-whisper",  # audio extra
}
# Distribution names for modules of an optional extra, used only when not installed.
NOT_INSTALLED_NAMES = {"faster_whisper": "faster-whisper"}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _req_name(req: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
    assert match, req
    return _norm(match.group(1))


def _declared() -> tuple[set[str], dict[str, set[str]]]:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text("utf-8"))["project"]
    base = {_req_name(r) for r in project["dependencies"]}
    extras = {k: {_req_name(r) for r in v} for k, v in project["optional-dependencies"].items()}
    return base, extras


def _imported_modules() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top != "app" and top not in sys.stdlib_module_names:
                    found.setdefault(top, []).append(str(path.relative_to(BACKEND)))
    return found


def _requires_closure(dist: str) -> set[str]:
    seen: set[str] = set()
    stack = [dist]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            reqs = md.requires(name) or []
        except md.PackageNotFoundError:
            continue
        # Unconditional requirements only (no "extra == ..." markers).
        stack += [_req_name(r) for r in reqs if "extra ==" not in r]
    return seen


def test_networkx_is_a_direct_base_dependency():
    base, _ = _declared()
    assert "networkx" in base


def test_every_imported_third_party_module_is_declared():
    base, extras = _declared()
    declared = base | set().union(*extras.values())
    dists = md.packages_distributions()
    problems: list[str] = []
    for module, files in sorted(_imported_modules().items()):
        if module in INDIRECT:
            parent = _norm(INDIRECT[module])
            if parent not in declared:
                problems.append(f"{module}: INDIRECT parent {parent} is not declared")
            continue
        names = {_norm(d) for d in dists.get(module, [])}
        if not names and module in NOT_INSTALLED_NAMES:
            names = {NOT_INSTALLED_NAMES[module]}  # an optional extra absent here
        if not names:
            problems.append(f"{module} (imported in {files[0]}) is not installed")
        elif not names & declared:
            problems.append(
                f"{module} (imported in {files[0]}) comes from {sorted(names)}, "
                "which pyproject.toml does not declare"
            )
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("module", sorted(INDIRECT))
def test_indirect_modules_really_come_from_their_declared_parent(module):
    parent = _norm(INDIRECT[module])
    try:
        md.distribution(parent)
    except md.PackageNotFoundError:
        pytest.skip(f"{parent} is not installed here (optional extra)")
    provided = {_norm(d) for d in md.packages_distributions().get(module, [])}
    assert provided, f"{module} is not installed although {parent} is"
    assert provided & _requires_closure(parent), (module, parent)
