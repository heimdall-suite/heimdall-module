"""Merge EasyEDA Pro's separate Schematic1.epro and PCB1.epro exports into
one linked project (heimdall-module.epro), so KiCad's
File > Import > Non-KiCad Project brings in schematic and PCB together.

Run with KiCad's bundled python (or any python 3) from this directory.
"""
import json
import zipfile

SCH, PCB, OUT = "Schematic1.epro", "PCB1.epro", "heimdall-module.epro"

a, b = zipfile.ZipFile(SCH), zipfile.ZipFile(PCB)
pa = json.loads(a.read("project.json"))
pb = json.loads(b.read("project.json"))

merged = {"config": {"title": "heimdall-module", "cbbProject": False}}
for key in ("devices", "symbols", "footprints"):
    merged[key] = {**pb[key], **pa[key]}
merged["schematics"] = pa["schematics"]
merged["pcbs"] = pb["pcbs"]
merged["panels"] = {}
(sch_uuid,) = pa["schematics"]
(pcb_uuid,) = pb["pcbs"]
merged["boards"] = {"Board1": {"schematic": sch_uuid, "pcb": pcb_uuid}}

seen = set()
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for src in (a, b):
        for name in src.namelist():
            if name == "project.json" or name in seen:
                continue
            seen.add(name)
            z.writestr(name, src.read(name))
    z.writestr("project.json", json.dumps(merged, ensure_ascii=False, indent=2))
print(f"wrote {OUT}: {len(seen)} entries, board {sch_uuid} + {pcb_uuid}")
