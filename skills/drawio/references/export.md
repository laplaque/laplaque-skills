# SKILL-export — Export to PNG, SVG, or PDF

---

## When to invoke

User says: "export", "save as image", "give me a PNG/SVG/PDF", or similar.
Requires a diagram to already exist (created or read in the current session,
or a file path provided by the user).

---

## Prerequisites

Requires the Docker export stack (see `references/setup.md` §1B).
Run `check_export_stack()` before proceeding.

### Auto-update and version pinning

Before each export session, pull the latest image and record the digest:

```python
import json
import sqlite3
import subprocess
from pathlib import Path

IMAGE = "jgraph/export-server:latest"

def ensure_latest_export_image(db_path: Path) -> str:
    """Pull latest export-server image, store digest, return short ID."""
    subprocess.run(["docker", "pull", "--quiet", IMAGE], check=True)
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.Id}}", IMAGE],
        capture_output=True, text=True, check=True,
    )
    digest = result.stdout.strip()
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            ("export_server_digest", digest),
        )
    return digest[:19]  # short ID for logging
```

Call this at the start of every export operation. The compose file uses `latest`
tag, so `docker compose up -d` after a pull automatically picks up the new image.

---

## Supported formats

| Format | MIME type | Notes |
|---|---|---|
| PNG | `image/png` | Raster, good for docs/slides |
| SVG | `image/svg+xml` | Vector, editable, retains XML |
| PDF | `application/pdf` | Print/archive quality |

Default: PNG if not specified.

---

## Export via the draw.io export server

The export server is exposed on `localhost:60081`. Call it directly from the host
via HTTP POST — no need to route through another container.

```python
import json
import urllib.request
from pathlib import Path

EXPORT_URL = "http://localhost:60081/"

def export_diagram(
    drawio_path: Path,
    fmt: str,           # "png", "svg", or "pdf"
    out_path: Path,
) -> Path:
    """
    POST the diagram XML to the export server and write the result.
    The export server accepts a JSON body with 'xml' and 'format' fields.
    """
    xml_content = drawio_path.read_text(encoding="utf-8")
    payload = json.dumps({"xml": xml_content, "format": fmt}).encode()

    req = urllib.request.Request(
        EXPORT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        out_path.write_bytes(resp.read())

    return out_path
```

---

## Output path

```python
import time
from pathlib import Path

def resolve_export_path(source: Path, fmt: str, user_dir: Path | None) -> Path:
    stem = source.stem
    out_dir = user_dir or source.parent
    candidate = out_dir / f"{stem}.{fmt}"
    if candidate.exists():
        candidate = out_dir / f"{stem}-{int(time.time())}.{fmt}"
    return candidate
```

Never overwrite an existing export file without confirmation.

---

## After export

Tell the user:

```text
Exported: <out_path>
Format: <PNG|SVG|PDF>  Size: <file size>
```

---

## Fallback: export server not reachable

If the export server is down and cannot be started:

1. Offer SVG as a fallback — generate SVG directly from the mxGraph XML
   using `cairosvg` without the export server
2. Tell the user PNG and PDF require the export server

```python
import cairosvg

def svg_to_png_fallback(svg_path: Path, out_path: Path) -> Path:
    cairosvg.svg2png(url=str(svg_path), write_to=str(out_path))
    return out_path
```
