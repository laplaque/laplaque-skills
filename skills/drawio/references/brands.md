# SKILL-brands — Brand Scheme Management

---

## What is a brand scheme?

A named set of visual properties stored in SQLite and applied to diagrams:
- Primary / secondary / accent colours (`fillColor`, `strokeColor`, `fontColor`)
- Font family and size
- Shape styles per semantic type (service, database, queue, actor, etc.)

---

## Auto-selection at diagram creation time

Call this before asking the user about brand/style:

```python
import json
import sqlite3
from pathlib import Path
from platformdirs import user_data_dir

DB_PATH = Path(user_data_dir("drawio-skill")) / "drawio-skill.db"
THRESHOLD = 0.75  # auto-apply if top score >= this

def score_scheme(scheme: dict, context: dict) -> float:
    """
    context keys: customer (str), tags (list[str]), recent_names (list[str])
    Returns a float 0.0–1.0.
    """
    score = 0.0
    customer = (scheme.get("customer") or "").lower()
    ctx_customer = (context.get("customer") or "").lower()
    if customer and ctx_customer and customer in ctx_customer:
        score += 0.5
    scheme_tags = set(json.loads(scheme.get("tags") or "[]"))
    ctx_tags = set(context.get("tags") or [])
    if scheme_tags & ctx_tags:
        score += 0.3 * len(scheme_tags & ctx_tags) / max(len(scheme_tags), 1)
    aliases = json.loads(scheme.get("aliases") or "[]")
    for alias in aliases:
        if alias.lower() in ctx_customer:
            score += 0.2
            break
    # Recency bonus
    if scheme.get("last_used"):
        score += min(scheme.get("confidence", 0.0), 0.2)
    return min(score, 1.0)

def select_scheme(context: dict) -> dict | None:
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM schemes").fetchall()
    if not rows:
        return None
    scored = sorted(rows, key=lambda r: score_scheme(dict(r), context), reverse=True)
    top = scored[0]
    top_score = score_scheme(dict(top), context)
    if top_score >= THRESHOLD:
        return dict(top)   # auto-apply
    if top_score > 0.0:
        return {"candidates": [dict(r) for r in scored[:3]]}  # present top 3
    return None
```

**Caller logic:**
- If `select_scheme` returns a scheme dict with `"payload"` → auto-apply, tell user
- If it returns `{"candidates": [...]}` → present names to user, ask which to use
- If it returns `None` → proceed with draw.io defaults, optionally offer to create a scheme

---

## Applying a scheme

```python
def apply_scheme(style_base: str, payload: dict, semantic_type: str) -> str:
    """
    Inject brand colours into a style string.
    semantic_type: 'service', 'database', 'queue', 'actor', 'edge'
    """
    overrides = payload.get(semantic_type, payload.get("default", {}))
    parts = [s for s in style_base.split(";") if s]
    keys_to_set = {k.split("=")[0]: k for k in parts}
    for prop, val in overrides.items():
        keys_to_set[prop] = f"{prop}={val}"
    return ";".join(keys_to_set.values()) + ";"
```

**Payload structure example:**
```json
{
  "default": {
    "fillColor": "#1A365D",
    "strokeColor": "#2D5A8A",
    "fontColor": "#FFFFFF",
    "fontFamily": "Helvetica",
    "fontSize": "12"
  },
  "database": {
    "fillColor": "#2D5A8A",
    "strokeColor": "#1A365D",
    "fontColor": "#FFFFFF"
  },
  "edge": {
    "strokeColor": "#E63946",
    "fontColor": "#333333"
  }
}
```

---

## CRUD operations

### Create / save a scheme

```python
import json
from datetime import datetime, timezone

def save_scheme(name: str, customer: str, tags: list[str],
                aliases: list[str], payload: dict) -> int:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            """INSERT INTO schemes (name, customer, tags, aliases, last_used, payload)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, customer, json.dumps(tags), json.dumps(aliases),
             datetime.now(timezone.utc).isoformat(), json.dumps(payload))
        )
        return cur.lastrowid
```

### List schemes

```python
def list_schemes() -> list[dict]:
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(
            "SELECT id, name, customer, tags, last_used FROM schemes ORDER BY last_used DESC"
        )]
```

### Update last_used

```python
def touch_scheme(scheme_id: int) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("UPDATE schemes SET last_used = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), scheme_id))
```

### Delete a scheme

```python
def delete_scheme(scheme_id: int) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM schemes WHERE id = ?", (scheme_id,))
```

Always confirm with the user before deleting: "Delete scheme '<name>'? This cannot be undone."

---

## Bootstrap from logo image

```python
from PIL import Image
import colorsys

def extract_palette(image_path: str, n: int = 5) -> list[str]:
    """
    Extract N dominant hex colours from a logo image.
    Returns list of '#RRGGBB' strings, sorted dark → light.
    """
    img = Image.open(image_path).convert("RGB")
    img = img.resize((150, 150))  # reduce for speed
    pixels = list(img.getdata())
    # Simple frequency-based approach
    from collections import Counter
    # Quantise to reduce colour space
    quantised = [(r // 32 * 32, g // 32 * 32, b // 32 * 32) for r, g, b in pixels]
    common = Counter(quantised).most_common(n * 3)
    # Filter near-white and near-black
    filtered = [
        rgb for rgb, _ in common
        if not (all(c > 220 for c in rgb) or all(c < 35 for c in rgb))
    ][:n]
    return ["#{:02X}{:02X}{:02X}".format(*rgb) for rgb in filtered]
```

**Bootstrap workflow:**
1. User drops logo image
2. Call `extract_palette(image_path)`
3. Present palette to user: show hex codes and ask for confirmation
4. Map colours to roles: "Which colour is your primary / secondary / accent?"
5. Build `payload` dict from answers
6. Call `save_scheme(...)` with user-provided name and customer
7. Confirm: "Scheme '<name>' saved with <N> colours."
