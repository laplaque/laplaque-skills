---
name: drawio
description: Generate, read, update, and export draw.io diagrams from natural language. Use when the user asks to create a diagram (architecture, sequence, ER, BPMN), open or read an existing .drawio file, modify or extend a diagram, export to PNG/SVG/PDF, or manage brand/colour schemes for diagrams. Do not use for Mermaid, PlantUML, or Graphviz unless conversion is requested.
---

# draw.io Skill

Generate, read, update, and export draw.io diagrams from natural language.
Editing uses draw.io Desktop locally; export uses a Docker export server — no data leaves to cloud services.

---

## Before doing anything: run the prerequisites checklist

Read and execute **`references/setup.md`** first, every time.
Do not proceed if setup fails — report the blocking issue to the user.

---

## Operation decision tree

```
User request
    │
    ├─ "create" / "draw" / "make a diagram"
    │       └─ references/create.md
    │
    ├─ "open" / "read" / "show me" + .drawio file
    │       └─ references/read-update.md  (read mode)
    │
    ├─ "update" / "change" / "add" / "modify" + existing diagram
    │       └─ references/read-update.md  (update mode)
    │
    ├─ "preview" / "edit in draw.io" / "open for editing"
    │       └─ references/preview.md
    │
    ├─ "export" / "save as PNG" / "PDF" / "SVG"
    │       └─ references/export.md
    │
    └─ "brand" / "colour scheme" / "style" / "logo"
            └─ references/brands.md
```

---

## Sub-documents

| File | Contents |
|---|---|
| `references/setup.md` | Prerequisites, Docker stack, sandbox, DB init |
| `references/create.md` | Dialog → XML → `.drawio` file → open in editor |
| `references/read-update.md` | Parse existing file, describe, modify, re-open |
| `references/preview.md` | Open in draw.io Desktop, wait for user, detect changes |
| `references/export.md` | Export to PNG / SVG / PDF via export server |
| `references/brands.md` | Brand scheme CRUD, confidence scoring, logo bootstrapping |

---

## Key constraints

- Never delete files. Offer to overwrite with confirmation.
- Never generate XML without first completing the dialog phase (see `references/create.md`).
- Always verify the export server is healthy before performing exports.
- Temp files live in the session sandbox only — clean up on completion.
