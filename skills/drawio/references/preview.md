# SKILL-preview — Open Diagram in draw.io Desktop

---

## Prerequisites

draw.io Desktop must be installed. The binary is typically named `drawio` or `draw.io`.

## Open for editing

```python
import hashlib
import shutil
import subprocess
from pathlib import Path


def open_in_drawio(path: Path) -> str:
    """Open a .drawio file in the desktop editor. Returns the file's SHA256 before opening."""
    binary = shutil.which("drawio") or shutil.which("draw.io")
    if not binary:
        raise EnvironmentError(
            "draw.io Desktop not found on PATH.\n"
            "Install from: https://github.com/jgraph/drawio-desktop/releases"
        )
    pre_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    subprocess.Popen([binary, str(path)])
    return pre_hash
```

## After opening

Tell the user:

```text
Opened <path> in draw.io Desktop.
Edit and save (Ctrl+S / Cmd+S) as many times as you like.
Let me know when you're done — I'll pick up your changes.
```

Then **wait for the user's next message** (any intent: "done", "export", "continue", etc.).

## Re-read and detect changes

```python
def reread_diagram(path: Path, pre_hash: str) -> tuple[str, bool]:
    """Re-read the file after the user signals done. Returns (content, changed)."""
    content = path.read_text(encoding="utf-8")
    post_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    changed = post_hash != pre_hash
    if not changed:
        # Warn: user may not have saved
        pass
    return content, changed
```

**If `changed` is False**, tell the user:

```text
The file hasn't changed since I opened it. Did you save? (Ctrl+S / Cmd+S)
```

**If `changed` is True**, proceed with the next operation (export, further edits, etc.)
using the fresh file content.
