"""Pick a Python that can import pypdf (Noesis .venv 3.14 currently breaks pyexpat)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_CANDIDATES = (
    Path(sys.executable),
    REPO.parent / "CaseLinker" / ".venv" / "bin" / "python",
    Path("/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"),
    Path("/opt/homebrew/bin/python3.13"),
    Path("/opt/homebrew/bin/python3.11"),
)


def python_with_pypdf() -> str | None:
    seen: set[str] = set()
    for cand in _CANDIDATES:
        path = str(cand)
        if path in seen or not cand.is_file():
            continue
        seen.add(path)
        try:
            proc = subprocess.run(
                [path, "-c", "import pypdf, reportlab"],
                capture_output=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            return path
    return None
