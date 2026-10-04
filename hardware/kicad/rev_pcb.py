"""PCB revision for heimdall-module (rev 2): sync the EasyEDA import to the revised schematic,
add the new parts, re-place the crowded right-hand side, cut the H1 slot.
Run with KiCad's python from hardware/kicad, on the rev 1 board (git), with a netlist from
  kicad-cli sch export netlist --format kicadxml -o net.xml heimdall-module.kicad_sch
  python rev_pcb.py net.xml
then route_pcb.py (prep, Freerouting, finish, widen, cleanup, bridge, gapstitch, bridge, final).
Strips all copper. The committed .kicad_pcb is the source of truth: don't run this on it."""
import sys, pcbnew, xml.etree.ElementTree as ET

B = 'heimdall-module.kicad_pcb'
STD = r'C:/Users/svefre/AppData/Local/Programs/KiCad/10.0/share/kicad/footprints'
PRJLIB = 'heimdall-m-easyedapro'
IO = pcbnew.PCB_IO_KICAD_SEXPR()
MM = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))

b = pcbnew.LoadBoard(B)
net = ET.parse(sys.argv[1]).getroot()
comps = {c.get('ref'): c for c in net.iter('comp')}
pinnet = {}
for n in net.iter('net'):
    for node in n.iter('node'):
        pinnet[(node.get('ref'), node.get('pin'))] = n.get('name')

# ---- strip copper and the leftovers of the EasyEDA import
dead = list(b.GetTracks()) + list(b.Zones())
loose = [f for f in b.GetFootprints() if not f.GetReference() and len(f.Pads()) == 1 and pcbnew.ToMM(f.Pads()[0].GetSize(pcbnew.F_Cu).x) < 2]
holes = [f for f in b.GetFootprints() if not f.GetReference() and f not in loose]

def load(fpid):
    nick, name = fpid.split(':')
    path = PRJLIB + '.pretty' if nick == PRJLIB else '%s/%s.pretty' % (STD, nick)
    f = IO.FootprintLoad(path, name)
    f.SetFPID(pcbnew.LIB_ID(nick, name))
    return f

# ---- placement: ref -> (x, y, rotation); only parts listed here move
PLACE = {
    # right zone: between the module (x<155.65), H1 (y<96.7), U3 (x>167.66) and U1 (y>111.9)
    'D1': (161.9, 98.6, 0), 'D2': (161.9, 101.9, 0),
    'R11': (157.0, 101.0, 270),
    'R3': (158.3, 105.2, 0), 'R4': (158.3, 107.4, 0),
    'U4': (165.4, 106.0, 90),
    'C1': (160.8, 109.8, 0), 'R1': (172.9, 98.7, 90),
    # left zone
    'C5': (131.3, 91.9, 0),
    'R12': (131.4, 109.6, 0), 'R13': (131.4, 111.8, 0),
    'JP1': (126.4, 111.6, 0),
}
J2_PIN1 = (141.34, 115.27)   # square pad of the old breakout grid (GND)

added = []
for ref, c in comps.items():
    fpid = c.findtext('footprint')
    f = b.FindFootprintByReference(ref)
    if f and f.GetFPIDAsString() != fpid:            # footprint changed (C1: tantalum -> 0805)
        pos, rot = f.GetPosition(), f.GetOrientationDegrees()
        dead.append(f); f = None
    if not f:
        f = load(fpid)
        f.SetReference(ref)
        b.Add(f); added.append(ref)
    f.SetValue(c.findtext('value'))
    ds = c.findtext('datasheet') or ''
    f.GetField('Datasheet').SetText('' if ds == '~' else ds)
    f.SetPath(pcbnew.KIID_PATH('/' + c.find('tstamps').text))
    f.SetSheetname('/'); f.SetSheetfile('heimdall-module.kicad_sch')
    for fld in c.iter('field'):
        if fld.get('name') not in ('Footprint', 'Datasheet', 'Description'):
            f.SetField(fld.get('name'), fld.text or '')
            f.GetField(fld.get('name')).SetVisible(False)
    if ref in PLACE:
        x, y, r = PLACE[ref]
        f.SetPosition(V(x, y)); f.SetOrientationDegrees(r)
    for p in f.Pads():
        name = pinnet.get((ref, p.GetNumber()))
        if name is None:
            p.SetNetCode(0); continue
        ni = b.FindNet(name)
        if ni is None:
            ni = pcbnew.NETINFO_ITEM(b, name); b.Add(ni)
        p.SetNet(ni)

# J2: 2x04 header, rotated so the rows run along x like the old pad grid, pin 1 on the old square pad
j2 = b.FindFootprintByReference('J2')
j2.SetOrientationDegrees(-90)
j2.SetPosition(V(0, 0))
p1 = [p for p in j2.Pads() if p.GetNumber() == '1'][0].GetPosition()
j2.SetPosition(V(J2_PIN1[0], J2_PIN1[1]) - p1)

# mounting holes: board-only, not in BOM/position files
for i, f in enumerate(sorted(holes, key=lambda f: f.GetPosition().x)):
    f.SetReference('MH%d' % (i + 1))
    f.SetBoardOnly(True); f.SetExcludedFromBOM(True); f.SetExcludedFromPosFiles(True)
    f.Reference().SetVisible(False)

# J2: no outline (the board's own pin labels sit there), pads as small as the old grid
for g in list(j2.GraphicalItems()):
    if g.GetLayer() == pcbnew.F_SilkS and g.GetClass() != 'PCB_FIELD':
        dead.append(g)
for p in j2.Pads():
    p.SetSize(pcbnew.F_Cu, V(1.55, 1.55))
# U3 USB-C: 0.6mm square pads on 0.42mm holes leave a 0.09mm ring; 0.7mm round gives 0.14mm and still 0.2mm between pins
u3 = b.FindFootprintByReference('U3')
for p in u3.Pads():
    if abs(pcbnew.ToMM(p.GetSize(pcbnew.F_Cu).x) - 0.6) < 0.01:
        p.SetSize(pcbnew.F_Cu, V(0.7, 0.7))
        p.SetShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_CIRCLE)   # square corners reach into the A/B row channel
# U2: silk outline segments that run along the antenna cut-out
u2 = b.FindFootprintByReference('U2')
for g in list(u2.GraphicalItems()):
    if g.GetLayer() == pcbnew.F_SilkS and g.GetClass() == 'PCB_SHAPE' and max(g.GetStart().y, g.GetEnd().y) < MM(97.9):
        dead.append(g)

# H1 slot: the transmitter's module-bay pins come up through the board into the female header
# (EasyEDA had it as a multi-layer fill, which the KiCad import turned into copper)
SX0, SY0, SX1, SY1, SR = 160.767, 92.667, 173.467, 94.699, 0.635
def edge_line(x0, y0, x1, y1):
    g = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT); g.SetLayer(pcbnew.Edge_Cuts); g.SetWidth(MM(0.05))
    g.SetStart(V(x0, y0)); g.SetEnd(V(x1, y1)); b.Add(g)
def edge_arc(cx, cy, sx, sy, deg):
    g = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_ARC); g.SetLayer(pcbnew.Edge_Cuts); g.SetWidth(MM(0.05))
    g.SetCenter(V(cx, cy)); g.SetStart(V(sx, sy)); g.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(deg, pcbnew.DEGREES_T), True); b.Add(g)
edge_line(SX0 + SR, SY0, SX1 - SR, SY0); edge_line(SX1, SY0 + SR, SX1, SY1 - SR)
edge_line(SX1 - SR, SY1, SX0 + SR, SY1); edge_line(SX0, SY1 - SR, SX0, SY0 + SR)
edge_arc(SX1 - SR, SY0 + SR, SX1 - SR, SY0, 90); edge_arc(SX1 - SR, SY1 - SR, SX1, SY1 - SR, 90)
edge_arc(SX0 + SR, SY1 - SR, SX0 + SR, SY1, 90); edge_arc(SX0 + SR, SY0 + SR, SX0, SY0 + SR, 90)
# H1 pads stop 0.5mm short of the slot (copper-to-edge rule); the header's feet land on the outer part
h1 = b.FindFootprintByReference('H1')
for p in h1.Pads():
    bb = p.GetBoundingBox(); top, bot = pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom())
    y0, y1 = (top, SY0 - 0.5) if top < SY0 else (SY1 + 0.5, bot)
    cx = pcbnew.ToMM(p.GetPosition().x)
    p.SetSize(pcbnew.F_Cu, V(pcbnew.ToMM(p.GetSize(pcbnew.F_Cu).x), y1 - y0))
    p.SetPosition(V(cx, (y0 + y1) / 2))

for it in dead + loose:
    par = it.GetParentFootprint() if hasattr(it, 'GetParentFootprint') else None
    (par.Remove(it) if par else b.Remove(it))
pcbnew.SaveBoard(B, b)

print('added', added)
for f in b.GetFootprints():
    if f.GetReference() in ('J2',):
        print('J2 pads', [(p.GetNumber(), p.GetNetname(), round(pcbnew.ToMM(p.GetPosition().x), 2), round(pcbnew.ToMM(p.GetPosition().y), 2)) for p in f.Pads()])
