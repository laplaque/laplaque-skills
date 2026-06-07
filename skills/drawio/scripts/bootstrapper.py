#!/usr/bin/env python3
"""
drawio-skill bootstrapper

Handles all environment setup before any draw.io skill operation:
  - Export server Docker container (PNG/SVG/PDF export)
  - SQLite brand/config database initialisation
  - Per-session sandbox creation (when needed)
  - Graceful teardown on exit

Usage (standalone — via entry point):
    python scripts/run.py

Usage (as module — must run inside the skill venv):
    from bootstrapper import DrawioEnvironment
    env = DrawioEnvironment()
    env.setup()   # raises RuntimeError if any check fails
    # ... do work ...
    env.teardown()

    # Or as a context manager:
    with DrawioEnvironment() as env:
        print(env.sandbox)      # Path to session sandbox
        print(env.export_url)   # e.g. http://localhost:60081
"""

from __future__ import annotations

import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import types
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from platformdirs import user_data_dir


# ── Constants ────────────────────────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent.parent  # skills/drawio/
DB_PATH = Path(user_data_dir("drawio-skill")) / "drawio-skill.db"
DRAWIO_COMPOSE = SKILL_DIR / "docker-compose.drawio.yml"

EXPORT_DEFAULT_URL = "http://localhost:60081"

EXPORT_HEALTH_TIMEOUT = 60   # seconds to wait for export server
HEALTH_POLL_INTERVAL  = 2    # seconds between health check polls

VENV_DIR = SKILL_DIR / ".venv"
REQUIREMENTS = SKILL_DIR / "requirements.txt"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _http_ok(url: str, timeout: float = 2.0) -> bool:
    """Return True if the URL responds with any HTTP status."""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True   # Got a response — server is up
    except Exception:
        return False


def _wait_for(check_fn: Callable[[], bool], timeout: float, label: str) -> bool:
    """Poll check_fn every HEALTH_POLL_INTERVAL seconds until timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check_fn():
            return True
        time.sleep(HEALTH_POLL_INTERVAL)
    print(f"[bootstrapper] TIMEOUT: {label} did not become ready within {timeout}s",
          file=sys.stderr)
    return False


def _docker_compose(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run docker compose -f <drawio-compose> <args>."""
    return subprocess.run(
        ["docker", "compose", "-f", str(DRAWIO_COMPOSE)] + args,
        capture_output=True,
        text=True,
    )


def _container_healthy(name: str) -> bool:
    """Return True if a named container reports healthy status."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Health.Status}}", name],
        capture_output=True, text=True,
    )
    return result.stdout.strip() == "healthy"


# ── Database ──────────────────────────────────────────────────────────────────

def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Create/open the SQLite DB and ensure schema exists. Idempotent."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS schemes (
            id         INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            customer   TEXT,
            tags       TEXT DEFAULT '[]',
            aliases    TEXT DEFAULT '[]',
            last_used  TEXT,
            confidence REAL DEFAULT 0.0,
            payload    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS config (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    con.commit()
    return con


def get_config(con: sqlite3.Connection, key: str) -> Optional[str]:
    row = con.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_config(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO config (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    con.commit()


def count_schemes(con: sqlite3.Connection) -> int:
    return con.execute("SELECT COUNT(*) FROM schemes").fetchone()[0]


# ── Export stack ─────────────────────────────────────────────────────────────

class ExportStack:
    """
    Manages the draw.io export server Docker Compose stack.

    Starts via docker compose if not already running.
    Never stops a stack it did not start.
    """

    EXPORT_CONTAINER = "drawio-export"

    def __init__(self) -> None:
        self._started_by_us = False
        self.export_url = EXPORT_DEFAULT_URL

    def ensure_running(self) -> str:
        """Ensure the export server is up. Returns the export URL."""
        if not DRAWIO_COMPOSE.exists():
            raise RuntimeError(
                f"[drawio] Compose file not found: {DRAWIO_COMPOSE}\n"
                "Ensure docker-compose.drawio.yml is in the skill directory."
            )

        if _http_ok(self.export_url):
            print(f"[drawio] export server already running at {self.export_url}")
            return self.export_url

        print("[drawio] starting export server...")
        result = _docker_compose(["up", "-d"])
        if result.returncode != 0:
            raise RuntimeError(
                f"[drawio] docker compose up failed:\n{result.stderr}\n"
                "Is Docker running? Try: docker info"
            )
        self._started_by_us = True

        if not _wait_for(
            lambda: _container_healthy(self.EXPORT_CONTAINER),
            EXPORT_HEALTH_TIMEOUT,
            "export server",
        ):
            raise RuntimeError(
                f"[drawio] export container '{self.EXPORT_CONTAINER}' did not become healthy "
                f"within {EXPORT_HEALTH_TIMEOUT}s. Check: docker logs {self.EXPORT_CONTAINER}"
            )

        print(f"[drawio] export server healthy at {self.export_url}")
        return self.export_url

    def stop_if_managed(self) -> None:
        """Tear down the stack only if we started it."""
        if self._started_by_us:
            print("[drawio] stopping export stack...")
            _docker_compose(["down"])
            print("[drawio] stopped")


# ── Sandbox ───────────────────────────────────────────────────────────────────

def create_sandbox() -> Path:
    """Create a temporary per-session work directory."""
    sandbox = Path(tempfile.mkdtemp(prefix="drawio-skill-"))
    (sandbox / "work").mkdir()
    (sandbox / "export").mkdir()
    print(f"[sandbox] created at {sandbox}")
    return sandbox


def destroy_sandbox(sandbox: Path) -> None:
    """Remove the session sandbox."""
    if sandbox.exists():
        shutil.rmtree(sandbox, ignore_errors=True)
        print(f"[sandbox] removed {sandbox}")


# ── Environment (facade) ──────────────────────────────────────────────────────

class DrawioEnvironment:
    """
    Facade that sets up and tears down the full draw.io skill environment.

    Attributes after setup():
        db         -- open sqlite3.Connection
        sandbox    -- Path to session temp directory (if requested)
        export_url -- str, e.g. 'http://localhost:60081'
    """

    def __init__(self, db_path: Path = DB_PATH, *, needs_sandbox: bool = True) -> None:
        self._db_path = db_path
        self._needs_sandbox = needs_sandbox
        self.db: Optional[sqlite3.Connection] = None
        self.sandbox: Optional[Path] = None
        self.export_url: Optional[str] = None
        self._export_stack: Optional[ExportStack] = None

    def setup(self) -> "DrawioEnvironment":
        """
        Run all setup steps. Raises RuntimeError with a descriptive message
        if any step fails. Safe to call multiple times (idempotent checks).
        """
        print("[bootstrapper] starting setup...")

        # 1. Database
        self.db = init_db(self._db_path)
        scheme_count = count_schemes(self.db)
        print(f"[db] ready at {self._db_path} ({scheme_count} schemes)")

        # 2. Export stack
        self._export_stack = ExportStack()
        self.export_url = self._export_stack.ensure_running()

        # 3. Sandbox (optional)
        if self._needs_sandbox:
            self.sandbox = create_sandbox()

        # 4. Status report
        self._print_status(scheme_count)

        # 5. Register signal handlers for clean teardown
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal_handler)

        return self

    def teardown(self) -> None:
        """Clean up sandbox and any managed processes."""
        print("[bootstrapper] tearing down...")
        if self.sandbox:
            destroy_sandbox(self.sandbox)
        if self._export_stack:
            self._export_stack.stop_if_managed()
        if self.db:
            self.db.close()
        print("[bootstrapper] done")

    def _print_status(self, scheme_count: int) -> None:
        print()
        print("─" * 50)
        print("✓ Export server ", self.export_url)
        print(f"✓ Brand DB       {self._db_path} ({scheme_count} schemes)")
        if self.sandbox:
            print("✓ Sandbox       ", self.sandbox)
        print("─" * 50)
        print()

    def _signal_handler(self, signum: int, frame: types.FrameType | None) -> None:
        print(f"\n[bootstrapper] caught signal {signum}, tearing down...")
        self.teardown()
        sys.exit(0)

    def __enter__(self) -> "DrawioEnvironment":
        return self.setup()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self.teardown()


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    """
    Standalone invocation: set up the environment, print status, and wait.
    Useful for manually verifying the stack before running skill operations.

    Ctrl-C triggers clean teardown.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="draw.io skill bootstrapper — verify and start environment"
    )
    parser.add_argument(
        "--db", type=Path, default=DB_PATH,
        help=f"Path to SQLite DB (default: {DB_PATH})",
    )
    args = parser.parse_args()

    env = DrawioEnvironment(db_path=args.db)

    try:
        env.setup()
        print("Environment ready. Press Ctrl-C to stop managed processes and exit.")
        while True:
            time.sleep(1)
    except RuntimeError as exc:
        print(f"\n[bootstrapper] SETUP FAILED:\n{exc}", file=sys.stderr)
        env.teardown()
        sys.exit(1)
    except KeyboardInterrupt:
        pass  # signal handler calls teardown


if __name__ == "__main__":
    main()
