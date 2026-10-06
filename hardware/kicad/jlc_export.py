# Builds the JLCPCB order package for a board into gerber/ in its project folder:
#   <name>.zip            Gerbers (board plot settings) + Excellon drill (PTH/NPTH)
#   <name>-BOM[-top|-bottom].csv   Comment, Designator, Footprint, LCSC
#   <name>-CPL[-top|-bottom].csv   Designator, Mid X, Mid Y, Layer, Rotation
# No suffix = both sides; -top / -bottom are for one-sided ("Economic") assembly.
# Parts without an LCSC number are left out of BOM and CPL. Copied from heimdall-switch; the
# module is ordered as a bare board (parts from TME/Mouser, hand assembly), so the zip is what counts.
#
# Run with KiCad's bundled python; the argument is the project folder (default: this one):
#   python jlc_export.py                  (from hardware/kicad/)
#
# Rotation, as in Bouni's kicad-jlcpcb-tools: top = KiCad angle + correction,
# bottom = 180 - KiCad angle + correction (JLC reads bottom angles mirrored).
# ROT_OFFSET holds the corrections per footprint name, for parts whose JLC model
# doesn't share KiCad's zero angle (values from heimdall-switch's JLC preview checks).
# Check the preview after every upload if this board is ever machine-assembled.
# Mid X/Y = centre of the pads (footprint origins aren't always the part centre).
import csv, os, subprocess, sys, zipfile
import pcbnew

KICAD_CLI = r"C:\Users\svefre\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe"
os.chdir(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
name = [f[:-len(".kicad_pro")] for f in os.listdir(".") if f.endswith(".kicad_pro")][0]
BOARD, SCH, OUT = name + ".kicad_pcb", name + ".kicad_sch", "gerber"
ROT_OFFSET = {
    "D_SOD-123": 0,        # rev 1 preview: band on the cathode with the mirrored angle alone
    "SOT-583-8": 270,      # U2: JLC's model is turned 90 deg against KiCad's
    "SOT-23": 180,         # rev 1 preview: Q1/Q2 correct at mirrored angle + 180
}
LAYERS = "F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"

def cli(*args):
    subprocess.run([KICAD_CLI, *args], check=True, stdout=subprocess.DEVNULL)

os.makedirs(OUT, exist_ok=True)
cli("pcb", "export", "gerbers", "--board-plot-params", "-l", LAYERS, "-o", OUT + "/", BOARD)
cli("pcb", "export", "drill", "--format", "excellon", "--drill-origin", "absolute",
    "--excellon-units", "mm", "--excellon-separate-th", "-o", OUT + "/", BOARD)
# every Gerber/drill file the export wrote for this board (layer file names follow the
# board's layer names, e.g. "top_cu" on the UI board, so match by extension)
EXT = (".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".gtp", ".gbp", ".gm1", ".drl", ".gbrjob")
parts = sorted(f for f in os.listdir(OUT) if f.startswith(name + "-") and f.endswith(EXT))
with zipfile.ZipFile(os.path.join(OUT, name + ".zip"), "w", zipfile.ZIP_DEFLATED) as z:
    for p in parts:
        z.write(os.path.join(OUT, p), p)

# BOM straight from the schematic (fields Value/Reference/Footprint/LCSC)
tmp = os.path.join(OUT, "_bom.csv")
cli("sch", "export", "bom", "--fields", "Value,Reference,Footprint,LCSC",
    "--labels", "Comment,Designator,Footprint,LCSC", "--group-by", "Value,Footprint,LCSC",
    "--exclude-dnp", "-o", tmp, SCH)
bom = list(csv.reader(open(tmp, encoding="utf8"))); os.remove(tmp)
skipped = [r[1] for r in bom[1:] if not r[3].strip()]
bom = [bom[0]] + [r for r in bom[1:] if r[3].strip()]
lcsc = {d.strip() for r in bom[1:] for d in r[1].split(",")}

# CPL from the board, with the rotation offsets applied
b = pcbnew.LoadBoard(BOARD)
cpl, side = [], {}
for f in sorted(b.GetFootprints(), key=lambda f: f.GetReference()):
    if f.IsExcludedFromPosFiles() or f.IsDNP() or f.GetReference() not in lcsc: continue
    fp = f.GetFPID().GetLibItemName().wx_str()
    a = f.GetOrientationDegrees()
    rot = ((180 - a) if f.IsFlipped() else a) + ROT_OFFSET.get(fp, 0)
    bb = pcbnew.BOX2I()
    for q in f.Pads(): bb.Merge(q.GetBoundingBox())
    p = bb.GetCenter()
    layer = "Bottom" if f.IsFlipped() else "Top"
    side[f.GetReference()] = layer
    cpl.append([f.GetReference(), "%.4fmm" % pcbnew.ToMM(p.x), "%.4fmm" % -pcbnew.ToMM(p.y), layer, "%.1f" % (rot % 360)])

def write(fn, rows):
    with open(os.path.join(OUT, fn), "w", newline="", encoding="utf8") as fh:
        csv.writer(fh).writerows(rows)
HEAD = ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]
write(name + "-BOM.csv", bom)
write(name + "-CPL.csv", [HEAD] + cpl)
counts = []
for s in ("Top", "Bottom"):
    refs = {r for r, l in side.items() if l == s}
    rows = [bom[0]] + [[r[0], ",".join(d.strip() for d in r[1].split(",") if d.strip() in refs), r[2], r[3]]
                       for r in bom[1:] if any(d.strip() in refs for d in r[1].split(","))]
    write("%s-BOM-%s.csv" % (name, s.lower()), rows)
    write("%s-CPL-%s.csv" % (name, s.lower()), [HEAD] + [c for c in cpl if c[3] == s])
    counts.append("%s %d lines / %d parts" % (s.lower(), len(rows) - 1, len(refs)))
print("JLC package in %s/: zip; BOM %d lines, CPL %d parts (%s); no LCSC number, left out: %s"
      % (OUT, len(bom) - 1, len(cpl), ", ".join(counts), ", ".join(skipped)))
