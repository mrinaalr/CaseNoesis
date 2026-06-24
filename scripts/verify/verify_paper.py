#!/usr/bin/env python3
"""Launcher → scripts/verify/paper/verify_paper.py."""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "paper" / "verify_paper.py"), run_name="__main__")
