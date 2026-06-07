#!/usr/bin/env python3
"""
Entry point for drawio-skill bootstrapper.

Ensures the skill's virtual environment exists and re-execs bootstrapper.py
under the venv Python. This script uses only stdlib.

Usage:
    python scripts/run.py [--db PATH]
"""

import os
import subprocess
import sys
import venv
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # skills/drawio/
VENV_DIR = SKILL_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
REQUIREMENTS = SKILL_DIR / "requirements.txt"
BOOTSTRAPPER = Path(__file__).resolve().parent / "bootstrapper.py"

if not VENV_PYTHON.exists():
    print("[venv] creating virtual environment...")
    venv.create(VENV_DIR, with_pip=True)
    if REQUIREMENTS.exists():
        result = subprocess.run(
            [str(VENV_DIR / "bin" / "pip"), "install", "--quiet", "-r", str(REQUIREMENTS)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"[venv] pip install failed:\n{result.stderr}", file=sys.stderr)
            raise SystemExit(1)
        print("[venv] dependencies installed")

os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(BOOTSTRAPPER)] + sys.argv[1:])
