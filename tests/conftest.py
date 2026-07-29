"""Shared fixtures.

``scripts/`` is not a package (the files are entry points run by the release
workflow, not an importable library), so the tests put it on ``sys.path``
explicitly rather than adding packaging ceremony the project does not need.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WWW = REPO_ROOT / "www"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture
def www() -> Path:
    """The PWA source directory served verbatim by Caddy."""
    return WWW
