# SKILL-create — Create a New Diagram

Full workflow: dialog → XML generation → `.drawio` file → open in editor.

---

## Phase 1: Dialog (mandatory — do not skip)

Gather all required information before generating any XML.
Ask only what is not already clear from the user's request.

### Required

| Question | If not answered |
|---|---|
| Diagram type? (architecture / sequence / ER / BPMN) | Ask |
| Components / entities / actors? | Ask |
| Relationships / flows between them? | Ask |

### Optional (ask if context suggests it matters)

| Question | Default if skipped |
|---|---|
| Brand/colour scheme? | Check confidence scores (see `SKILL-brands.md`) |
| Output filename? | `diagram-<timestamp>.drawio` in current working dir |
| Layout direction? (LR / TB) | TB (top-to-bottom) |
| Any existing diagram to extend? | None |

**Dialog rules:**

- Ask all unclear questions in one message, not one at a time.
- If brand scheme confidence ≥ threshold → auto-apply and tell the user; do not ask.
- Once answers are complete → confirm back with a one-line summary before generating.

---

## Phase 2: XML generation

Generate mxGraph XML based on the gathered requirements.

### mxGraph XML skeleton

```xml
<?xml version="1.0" encoding="UTF-8"?>
<mxGraphModel>
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <!-- diagram cells go here -->
  </root>
</mxGraphModel>
```

### Cell ID rules

- IDs must be unique strings. Use sequential integers starting at 2.
- Every cell except 0 and 1 must have `parent` set (usually `"1"` for top-level).
- Edge cells must have `source` and `target` attributes referencing vertex IDs.
- Edge cells must have `edge="1"`, vertex cells must have `vertex="1"`.

### Style guidelines per diagram type

**Architecture:**

```text
service/box:   rounded=1;whiteSpace=wrap;
group/cluster: swimlane;
database:      shape=mxgraph.flowchart.stored_data;
queue:         shape=mxgraph.flowchart.stored_data;direction=south;
actor/user:    shape=mxgraph.flowchart.start_2;
```

**Sequence:**

```text
lifeline:      shape=mxgraph.archimate3.actor;
message:       endArrow=open;dashed=0;
return:        endArrow=open;dashed=1;
activation:    fillColor=#dae8fc;
```

**ER:**

```text
entity:        shape=table;
attribute row: shape=tableRow;
relationship:  endArrow=ERmany;startArrow=ERone;
```

**BPMN:**

```text
start event:   shape=mxgraph.bpmn.shape;perimeter=mxPerimeter.ellipsePerimeter;
task:          rounded=1;
gateway:       shape=mxgraph.bpmn.shape;bpmnShapeType=gateway;
end event:     shape=mxgraph.bpmn.shape;perimeter=mxPerimeter.ellipsePerimeter;fillColor=#FF0000;
```

### Brand scheme application

If a scheme is selected (auto or user-chosen), inject from `payload`:

- `fillColor`, `strokeColor`, `fontColor`, `fontSize`, `fontFamily`
Apply consistently across all cells of the same semantic type.

### Validation (run before writing file)

```python
from lxml import etree

def validate_mxgraph(xml_str: str) -> list[str]:
    errors = []
    root = etree.fromstring(xml_str.encode())
    ids = set()
    for cell in root.iter("mxCell"):
        cid = cell.get("id")
        if cid in ids:
            errors.append(f"Duplicate cell ID: {cid}")
        ids.add(cid)
        if cell.get("edge") == "1":
            if not cell.get("source") or not cell.get("target"):
                errors.append(f"Edge {cid} missing source/target")
    return errors
```

If validation errors exist → fix them before proceeding. Do not write invalid XML.

---

## Phase 3: Write file

```python
import time
from pathlib import Path

# Determine output path
filename = user_supplied_name or f"diagram-{int(time.time())}.drawio"
out_path = Path(user_cwd) / filename  # or sandbox/work/ if no cwd available

# Never overwrite without confirmation
if out_path.exists():
    # Ask user: "<filename> already exists. Overwrite? (yes/no)"
    # Abort if not confirmed
    pass

out_path.write_text(xml_str, encoding="utf-8")
```

---

## Phase 4: Preview in draw.io Desktop

Follow **`references/preview.md`**:

1. Call `open_in_drawio(out_path)` — opens the file in draw.io Desktop, records pre-hash
2. Tell the user editing is open, wait for their next message
3. On return, call `reread_diagram(out_path, pre_hash)` to detect changes
4. Route to next operation: export, further edits, or done
