"""Reference designators on the top silkscreen, readable after assembly: 1.0mm text (0.15mm
stroke, 0.8mm where 1.0 doesn't fit), each placed at the nearest spot beside its part that keeps
clear of pads, vias, holes, part bodies, other silk and the board edge. Mounting holes stay hidden.
    silk_refs.py BOARD"""
import pcbnew, sys, math
B = sys.argv[1]
MM, T = pcbnew.FromMM, pcbnew.ToMM
b = pcbnew.LoadBoard(B)
F_SilkS = b.GetLayerID("F.Silkscreen")

def box(x0, y0, x1, y1): return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
def grow(r, d): return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)
def hit(a, c): return a[0] < c[2] and c[0] < a[2] and a[1] < c[3] and c[1] < a[3]
def bb(item): r = item.GetBoundingBox(); return box(T(r.GetLeft()), T(r.GetTop()), T(r.GetRight()), T(r.GetBottom()))

edge = b.GetBoardEdgesBoundingBox()
outline = pcbnew.SHAPE_POLY_SET(); b.GetBoardPolygonOutlines(outline, False)
def inside(r, m=0.4):
    pts = [(r[0] - m, r[1] - m), (r[2] + m, r[1] - m), (r[2] + m, r[3] + m), (r[0] - m, r[3] + m), ((r[0] + r[2]) / 2, r[1] - m), ((r[0] + r[2]) / 2, r[3] + m)]
    return all(outline.Contains(pcbnew.VECTOR2I(MM(x), MM(y))) for x, y in pts)

fps = [f for f in b.GetFootprints() if not f.GetReference().startswith("MH")]
# obstacles: (rect, owner ref or None); own pads/body block the own text too
obst = []
for f in b.GetFootprints():
    ref = f.GetReference()
    for p in f.Pads():
        obst.append((grow(bb(p), 0.2), ref))
    c = f.GetCourtyard(pcbnew.F_CrtYd)
    if c.OutlineCount():   # body: courtyard less its 0.25 margin
        r = c.BBox(); obst.append((grow(box(T(r.GetLeft()), T(r.GetTop()), T(r.GetRight()), T(r.GetBottom())), -0.2), ref))
    for g in f.GraphicalItems():
        if g.GetLayer() == F_SilkS and g.Type() != pcbnew.PCB_FIELD_T and g.Type() != pcbnew.PCB_TEXT_T:
            obst.append((grow(bb(g), 0.15), ref))
for t in b.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T: obst.append((grow(bb(t), 0.15), None))
for d in b.GetDrawings():
    if d.GetLayer() == F_SilkS: obst.append((grow(bb(d), 0.15), None))

def text_rect(cx, cy, n, h, ang):
    w = n * h * 0.9 + 0.15; hh = h + 0.15     # stroke font: ~0.9h per character
    return box(cx - w / 2, cy - hh / 2, cx + w / 2, cy + hh / 2) if ang in (0, 180) else box(cx - hh / 2, cy - w / 2, cx + hh / 2, cy + w / 2)

# parts' courtyard boxes: a label has to sit clearly closer to its own part than to any other
crt = {}
for f in fps:
    c = f.GetCourtyard(pcbnew.F_CrtYd)
    if c.OutlineCount():
        r = c.BBox(); crt[f.GetReference()] = box(T(r.GetLeft()), T(r.GetTop()), T(r.GetRight()), T(r.GetBottom()))
def gap(r, c):   # distance between two boxes
    return math.hypot(max(0, c[0] - r[2], r[0] - c[2]), max(0, c[1] - r[3], r[1] - c[3]))

placed = []
order = sorted(fps, key=lambda f: T(f.GetCourtyard(pcbnew.F_CrtYd).BBox().GetArea()) if f.GetCourtyard(pcbnew.F_CrtYd).OutlineCount() else 0)
fails = []
for f in order:
    ref = f.GetReference(); c = f.GetCourtyard(pcbnew.F_CrtYd).BBox() if f.GetCourtyard(pcbnew.F_CrtYd).OutlineCount() else f.GetBoundingBox()
    fx, fy = T(c.GetCenter().x), T(c.GetCenter().y)
    hw, hh = T(c.GetWidth()) / 2, T(c.GetHeight()) / 2
    best = None
    for h in (1.0, 0.8):
        for ang in (0, 90):
            ni, nj = int((hw + 4) / 0.2), int((hh + 4) / 0.2)   # search out to 4mm past the courtyard
            for i in range(-ni, ni + 1):
                for j in range(-nj, nj + 1):
                    cx, cy = fx + i * 0.2, fy + j * 0.2
                    r = text_rect(cx, cy, len(ref), h, ang)
                    if not inside(r): continue
                    if any(hit(r, o) for o, _ in obst): continue
                    if any(hit(r, grow(p, 0.2)) for p in placed): continue
                    own = gap(r, crt[ref]) if ref in crt else 0
                    if any(gap(r, c) < own + 0.3 for k, c in crt.items() if k != ref): continue
                    # distance from the part's courtyard edge; horizontal text preferred
                    dx = max(0, abs(cx - fx) - hw); dy = max(0, abs(cy - fy) - hh)
                    score = math.hypot(dx, dy) + (0.4 if ang else 0) + (0.6 if h < 1 else 0)
                    if best is None or score < best[0]: best = (score, cx, cy, h, ang, r)
        if best and best[3] == h: break
    t = f.Reference()
    if not best:
        fails.append(ref); continue
    _, cx, cy, h, ang, r = best
    t.SetLayer(F_SilkS); t.SetVisible(True)
    t.SetTextSize(pcbnew.VECTOR2I(MM(h), MM(h))); t.SetTextThickness(MM(0.15))
    t.SetKeepUpright(True); t.SetTextAngleDegrees(ang)
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER); t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    t.SetPosition(pcbnew.VECTOR2I(MM(cx), MM(cy)))
    placed.append(r)
    print("%-4s %.1fmm %3d (%.1f, %.1f)  %.2fmm from its part" % (ref, h, ang, cx, cy, best[0] - (0.4 if ang else 0) - (0.6 if h < 1 else 0)))
for f in b.GetFootprints():
    if f.GetReference().startswith("MH"): f.Reference().SetVisible(False)
print("no spot:", fails)
pcbnew.SaveBoard(B, b)
