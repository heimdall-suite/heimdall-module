# EasyEDA Pro archive

The original heimdall-module design was drawn in EasyEDA Pro 3.2 (project
"Atmosphere module") before the move to KiCad. These files are kept
unmodified as a reference:

- `Schematic1.epro`, `PCB1.epro` — per-document exports from EasyEDA Pro
  (2026-10-04). The full project's native `.epro2` format can't be read by
  the KiCad 10 importer, these older-format exports can.
- `merge_epro.py` — joins the two exports into one linked project,
  `heimdall-module.epro`, for KiCad's File → Import → Non-KiCad Project.

Once imported, `hardware/kicad/` is the source of truth; nothing here is
edited further.
