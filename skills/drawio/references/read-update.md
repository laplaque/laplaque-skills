# SKILL-read-update — Read & Update Existing Diagrams

---

## Read mode

### Step 1: Locate the file

Accept any of:

- An absolute path (`/home/user/project/arch.drawio`)
- A relative path resolved against the working directory
- A workspace-relative path (`docs/diagrams/arch.drawio`)

The agent should resolve the path using the working directory context available
in its environment. Do not assume any specific upload directory or harness-specific
file staging location.

```python
from pathlib import Path
import os

def resolve_drawio_file(user_input: str, cwd: str | None = None) -> Path:
    """Resolve a user-provided path to an existing .drawio file."""
    path = Path(user_input).expanduser()
    if not path.is_absolute():
        base = Path(cwd) if cwd else Path.cwd()
        path = (base / path).resolve()
    else:
        path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if path.suffix != ".drawio":
        raise ValueError(f"Expected .drawio file, got: {path.suffix}")
    return path
```

### Step 2: Parse and describe

```python
from lxml import etree

def parse_drawio(path: Path) -> etree._Element:
    tree = etree.parse(str(path))
    return tree.getroot()

def describe_diagram(root: etree._Element) -> dict:
    cells = root.findall(".//mxCell")
    vertices = [c for c in cells if c.get("vertex") == "1" and c.get("id") not in ("0", "1")]
    edges = [c for c in cells if c.get("edge") == "1"]
    return {
        "vertex_count": len(vertices),
        "edge_count": len(edges),
        "vertices": [{"id": v.get("id"), "label": v.get("value", "")} for v in vertices],
        "edges": [{"source": e.get("source"), "target": e.get("target"), "label": e.get("value", "")} for e in edges],
    }
```

Report to user:

```text
File: <path>
Diagram contains <N> components and <M> connections.
Components: <list of labels>
Connections: <source> → <target> [label]
```

### Step 3: Open in editor (if user wants to view)

Follow **`references/preview.md`** — call `open_in_drawio(path)` to open the file
in draw.io Desktop. Wait for the user's next message before continuing.

---

## Update mode

### Step 1: Read the existing file

Follow Read mode Steps 1–2. Load XML into memory.

### Step 2: Dialog — clarify changes

Ask only what is not clear:

- What to add / remove / change?
- New connections or components?
- Style or label changes?
- Brand scheme change?

Do not ask if the request is unambiguous (e.g. "add a Redis cache between Service A and the DB").

### Step 3: Apply changes to XML

```python
def add_vertex(root: etree._Element, cell_id: str, label: str, style: str,
               x: int, y: int, w: int = 120, h: int = 60) -> None:
    parent = root.find(".//mxCell[@id='1']")
    cell = etree.SubElement(parent.getparent(), "mxCell",
        id=cell_id, value=label, style=style,
        vertex="1", parent="1")
    etree.SubElement(cell, "mxGeometry",
        x=str(x), y=str(y), width=str(w), height=str(h),
        **{"as": "geometry"})

def add_edge(root: etree._Element, cell_id: str, source: str, target: str,
             label: str = "") -> None:
    cell = etree.SubElement(root.find(".//root"), "mxCell",
        id=cell_id, value=label,
        edge="1", source=source, target=target, parent="1")
    etree.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})

def remove_cell(root: etree._Element, cell_id: str) -> None:
    for cell in root.findall(f".//mxCell[@id='{cell_id}']"):
        cell.getparent().remove(cell)

def update_label(root: etree._Element, cell_id: str, new_label: str) -> None:
    cell = root.find(f".//mxCell[@id='{cell_id}']")
    if cell is not None:
        cell.set("value", new_label)
```

**ID assignment for new cells:** find the current max integer ID in the diagram, increment from there.

### Step 4: Validate

Run the same `validate_mxgraph()` from `SKILL-create.md`. Fix any errors before writing.

### Step 5: Write and re-open

```python
from lxml import etree

# Serialise
updated_xml = etree.tostring(root.getroottree(), pretty_print=True,
                              xml_declaration=True, encoding="UTF-8").decode()

# Write back to same path (user already confirmed update intent)
path.write_text(updated_xml, encoding="utf-8")
```

Then open for preview — follow **`references/preview.md`**:

1. Call `open_in_drawio(path)` — opens updated file in draw.io Desktop, records pre-hash
2. Tell the user:

   ```text
   Updated: <path>
   Changes applied: <brief summary>
   Opened in draw.io Desktop — save and let me know when done.
   ```

3. Wait for user's next message, then `reread_diagram(path, pre_hash)` to pick up any further manual edits
