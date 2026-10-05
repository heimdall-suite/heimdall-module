"""Fit the board to MULTI-Module_Bangood_4-in-1_Case: outline = cavity - 0.3mm, latch notches,
M2 holes on the case standoffs, groups moved clear. Strips copper (routing is redone)."""
import pcbnew, sys
B = sys.argv[1]
MM = pcbnew.FromMM; T = pcbnew.ToMM
V = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))
b = pcbnew.LoadBoard(B)
dead = list(b.GetTracks()) + list(b.Zones())
# outline: keep the H1 slot, replace the rest
for d in b.GetDrawings():
    if d.GetLayer() == pcbnew.Edge_Cuts:
        bb = d.GetBoundingBox()
        if not (T(bb.GetLeft()) > 160.6 and T(bb.GetRight()) < 173.6 and T(bb.GetTop()) > 92.5 and T(bb.GetBottom()) < 94.9):
            dead.append(d)
OUT = [(119.42, 89.48), (136.7, 89.48), (136.7, 100.1), (154.7, 100.1), (154.7, 93.53), (158.12, 93.53),
       (158.12, 89.48), (175.82, 89.48), (175.82, 130.38), (158.12, 130.38), (158.12, 126.33), (137.12, 126.33),
       (137.12, 130.38), (119.42, 130.38)]
for i in range(len(OUT)):
    g = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT); g.SetLayer(pcbnew.Edge_Cuts); g.SetWidth(MM(0.05))
    g.SetStart(V(*OUT[i])); g.SetEnd(V(*OUT[(i + 1) % len(OUT)])); b.Add(g)
# mounting holes on the case standoffs
for f in list(b.GetFootprints()):
    if f.GetReference() in ('MH1', 'MH2'): dead.append(f)
IO = pcbnew.PCB_IO_KICAD_SEXPR()
for i, (x, y) in enumerate(((126.42, 91.73), (172.02, 101.63), (157.92, 123.83))):
    f = IO.FootprintLoad(r'C:/Users/svefre/AppData/Local/Programs/KiCad/10.0/share/kicad/footprints/MountingHole.pretty', 'MountingHole_2.2mm_M2')
    f.SetFPID(pcbnew.LIB_ID('MountingHole', 'MountingHole_2.2mm_M2'))
    f.SetReference('MH%d' % (i + 1)); f.Reference().SetVisible(False); f.SetValue('M2')
    f.SetBoardOnly(True); f.SetExcludedFromBOM(True); f.SetExcludedFromPosFiles(True)
    f.SetPosition(V(x, y)); b.Add(f)
# groups
RIGHT = {'U3', 'U4', 'R3', 'R4', 'D1', 'D2', 'C1'}
for f in b.GetFootprints():
    r = f.GetReference()
    if not r or r.startswith('MH') or r == 'H1': continue
    p = f.GetPosition()
    if r in RIGHT: dx, dy = 0, 3.7
    elif r == 'U1': dx, dy = 4.1, 3.7
    elif r == 'R1': f.SetPosition(V(171.8, 97.9)); f.SetOrientationDegrees(0); continue
    elif r == 'R2': f.SetPosition(V(174.6, 118.0)); f.SetOrientationDegrees(90); continue
    else: dx, dy = 0, 2.8
    f.SetPosition(pcbnew.VECTOR2I(p.x + MM(dx), p.y + MM(dy)))
for it in dead:
    b.Remove(it)
pcbnew.SaveBoard(B, b)

# ---- H1 + slot onto the bay pins as three reference designs place them (Multi STM32 Eagle, Multipro V2
# Gerber, ELRS TX_SX1280): 1.25mm towards the end wall, 0.25mm towards the case centre
b = pcbnew.LoadBoard(B)
DX, DY = 1.25, 0.25
h1 = b.FindFootprintByReference('H1')
h1.SetPosition(pcbnew.VECTOR2I(h1.GetPosition().x + MM(DX), h1.GetPosition().y + MM(DY)))
for d in b.GetDrawings():
    if d.GetLayer() == pcbnew.Edge_Cuts:
        bb = d.GetBoundingBox()
        if T(bb.GetLeft()) > 160.6 and T(bb.GetRight()) < 173.6 and T(bb.GetTop()) > 92.5 and T(bb.GetBottom()) < 94.9:
            d.Move(V(DX, DY))
b.FindFootprintByReference('R1').SetPosition(V(171.8, 98.0))
pcbnew.SaveBoard(B, b)

# ---- C2 (U1's output cap) beside the tab, clear of the M2 hole
b = pcbnew.LoadBoard(B)
c2 = b.FindFootprintByReference('C2'); c2.SetPosition(V(158.0, 118.5)); c2.SetOrientationDegrees(90)
pcbnew.SaveBoard(B, b)

# ---- J2's pin labels are board texts: follow the L group
b = pcbnew.LoadBoard(B)
for d in b.GetDrawings():
    if d.GetClass() == 'PCB_TEXT' and d.GetText() in ('01', '03', '10', 'SDA', 'SCL', '3v3', 'G'):
        d.Move(V(0, 2.8))
pcbnew.SaveBoard(B, b)
