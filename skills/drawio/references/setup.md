# SKILL-setup — Prerequisites & Environment

Run this before any operation. Which checks are required depends on the operation:

- **All operations:** §0 (Python deps) + §2 (SQLite DB)
- **Create / Read / Update / Preview:** §0 + §1A (draw.io Desktop) + §2
- **Export:** §0 + §1B (Docker export stack) + §2 + §3 (sandbox)
- **Brands with logo import:** §0 + §2 + §3 (sandbox)

---

## 0. Python dependencies

The skill requires `lxml`, `platformdirs`, and `Pillow`. Ensure they are importable
in the current Python environment.

```python
import importlib.util
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # adjust if called differently
REQUIREMENTS = SKILL_DIR / "requirements.txt"

REQUIRED_PACKAGES = ["lxml", "platformdirs", "PIL"]  # PIL = Pillow's import name

def ensure_deps() -> None:
    """Install missing dependencies from requirements.txt."""
    missing = [pkg for pkg in REQUIRED_PACKAGES if importlib.util.find_spec(pkg) is None]
    if missing:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(REQUIREMENTS)]
        )
```

**Decision logic:**

1. Check each required package with `importlib.util.find_spec()`
2. If any missing → `pip install -r requirements.txt` using the current interpreter
3. If pip fails → report to user ("Install dependencies manually: `pip install -r requirements.txt`")

---

## 1A. draw.io Desktop check (for create / read / update / preview)

Required when the operation opens the diagram for visual editing.

```python
import shutil

def check_drawio_desktop() -> str:
    """Return the path to draw.io Desktop binary, or raise."""
    binary = shutil.which("drawio") or shutil.which("draw.io")
    if not binary:
        raise EnvironmentError(
            "draw.io Desktop not found on PATH.\n"
            "Install from: https://github.com/jgraph/drawio-desktop/releases"
        )
    return binary
```

**Decision logic:**

1. `shutil.which("drawio")` or `shutil.which("draw.io")` returns a path → proceed
2. If not found → report install URL to user, do not proceed with preview

---

## 1B. Docker export stack check (for export only)

| Service | Host port | Notes |
|---|---|---|
| export server  | `localhost:60081` | Mapped from container `:8000` |

```python
import subprocess
import urllib.request

def check_export_stack(compose_file: Path) -> None:
    """Ensure the export server is running. Start if needed."""
    try:
        urllib.request.urlopen("http://localhost:60081", timeout=3)
    except Exception:
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            check=True,
        )
        # Wait for healthy (poll from host — no curl needed inside container)
        import time
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen("http://localhost:60081", timeout=2)
                break
            except Exception:
                time.sleep(2)
        else:
            raise RuntimeError("Export server did not become ready within 60s")
```

**Decision logic:**

1. `http://localhost:60081` reachable → export server running
2. If not → `docker compose up -d` with the skill's `docker-compose.drawio.yml`
3. Wait up to 60 s for the export container health check
4. If Docker not available → report to user, offer SVG-only fallback (see `export.md`)

`<skill_dir>` = directory containing this SKILL.md file.

---

## 2. SQLite database init

```python
import sqlite3
from pathlib import Path
from platformdirs import user_data_dir

DB_PATH = Path(user_data_dir("drawio-skill")) / "drawio-skill.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(DB_PATH) as con:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS schemes (
            id        INTEGER PRIMARY KEY,
            name      TEXT NOT NULL,
            customer  TEXT,
            tags      TEXT DEFAULT '[]',
            aliases   TEXT DEFAULT '[]',
            last_used TEXT,
            confidence REAL DEFAULT 0.0,
            payload   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS config (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
```

Run this on every startup — `IF NOT EXISTS` makes it idempotent.

---

## 3. Session sandbox (conditional — export and brand-logo ops only)

Only create the sandbox when the operation requires temporary file staging
(export output, logo downloads). Skip for create/read/update/preview.

```python
import tempfile
from pathlib import Path

def create_sandbox() -> Path:
    """Create a temporary working directory. Call only when needed."""
    sandbox = Path(tempfile.mkdtemp(prefix="drawio-skill-"))
    (sandbox / "work").mkdir()
    (sandbox / "export").mkdir()
    return sandbox
```

Store `sandbox` path for the duration of the session if created.
On skill completion: `shutil.rmtree(sandbox, ignore_errors=True)`

---

## 4. Setup complete confirmation

Report to user (briefly) — only include lines for checks that actually ran:

```text
✓ draw.io Desktop: <binary path>          ← only if §1A ran
✓ Export server:   http://localhost:60081  ← only if §1B ran
✓ Brand DB ready   (<N> schemes loaded)
✓ Sandbox:         <path>                 ← only if §3 ran
```

Then proceed to the requested operation.
