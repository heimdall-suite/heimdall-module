# Routing pipeline for heimdall-module (KiCad python + Freerouting), adapted from
# heimdall-switch/hardware/kicad/route_pcb.py:
#   prep IN OUT DSN              U1 tab heatsink zones + vias, DSN without GND (left to the pours)
#   (java -jar freerouting.jar -de DSN -do SES -mp 100 --gui.enabled=false)
#   finish IN SES OUT            import SES, GND pours both layers
#   gridstitch IN OUT 4.0        GND stitching vias
#   islandstitch IN OUT          via for every GND pour fragment
#   cleanup IN OUT               drop fragment/dangling vias
#   gapstitch IN OUT 4.0 [0.7]   more GND vias (0.7/0.3): >= 2 per pour fragment, all overlap within 4mm
#   widen IN OUT 0.2             tracks Freerouting necked down below 0.2mm back to 0.2mm
#   bridge IN OUT                GND vias tying every pour fragment that has pads to the main GND
#   final IN OUT                 remove GND pour islands that are still floating
# Order used for rev 2: prep, Freerouting, finish, widen, cleanup, bridge, gapstitch 4.0, bridge, final.
# Last run on the spread_place.py placement (same order). The DSN takes its net classes from the
# .kicad_pro next to the board file: without it everything is routed at 0.2mm.
# Only for re-running the flow from a fresh placement (rev_pcb.py): it rebuilds all copper.
# gapstitch and syncfields (copy schematic fields onto footprints) also run on a finished board.
import sys, re, pcbnew

MM = pcbnew.FromMM
# hand routes are locked; note Freerouting never counts them (locked or not) as connections,
# so a net touched by a hand route has to be finished by hand
LOCK = True
# offset of the placement group being drawn (prep), see grp()
OFF = [0.0, 0.0]
def V(x, y): return pcbnew.VECTOR2I_MM(x + OFF[0], y + OFF[1])

def zone(b, net, layer, pts, prio, clear=0.25, full=True, name=""):
    z = pcbnew.ZONE(b)
    z.SetLayer(layer)
    z.SetNetCode(b.GetNetsByName()[net].GetNetCode())
    o = z.Outline(); o.NewOutline()
    for x, y in pts: o.Append(MM(x + OFF[0]), MM(y + OFF[1]))
    z.SetAssignedPriority(prio)
    z.SetLocalClearance(MM(clear))
    z.SetMinThickness(MM(0.25))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if full else pcbnew.ZONE_CONNECTION_THT_THERMAL)
    z.SetThermalReliefGap(MM(0.3)); z.SetThermalReliefSpokeWidth(MM(0.4))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    if name: z.SetZoneName(name)
    b.Add(z)
    return z

def track(b, net, layer, x0, y0, x1, y1, w):
    t = pcbnew.PCB_TRACK(b); t.SetStart(V(x0, y0)); t.SetEnd(V(x1, y1))
    t.SetWidth(MM(w)); t.SetLayer(layer); t.SetNetCode(b.GetNetsByName()[net].GetNetCode()); t.SetLocked(LOCK); b.Add(t)

def via(b, net, x, y, d=0.8, drill=0.4):
    v = pcbnew.PCB_VIA(b); v.SetPosition(V(x, y)); v.SetWidth(MM(d)); v.SetDrill(MM(drill))
    v.SetNetCode(b.GetNetsByName()[net].GetNetCode()); v.SetLocked(LOCK); b.Add(v)

def rect(x0, y0, x1, y1): return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

def pad_boxes(b, margin):
    """Pad bounding boxes (mm) grown by margin: stitching vias stay out of every pad, any net"""
    out = []
    for f in b.GetFootprints():
        for p in f.Pads():
            bb = p.GetBoundingBox()
            out.append(tuple(pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom())))
    return [(a - margin, c - margin, d + margin, e + margin) for a, c, d, e in out]

def in_boxes(boxes, x, y): return any(a <= x <= d and c <= y <= e for a, c, d, e in boxes)

if sys.argv[1] == "prep":
    # Placement from spread_place.py (on top of case_place.py). The USB-C field (R group) is still
    # drawn in rev 2 coordinates with its case_place offset (+0.0, +4.0); everything else is absolute.
    b = pcbnew.LoadBoard(sys.argv[2])
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    def grp(dx, dy): OFF[0], OFF[1] = dx, dy
    def rulearea(name, pts, tracks=True, vias=True, fills=False, layer=None):
        k = pcbnew.ZONE(b); k.SetIsRuleArea(True)
        if layer is None: k.SetLayerSet(pcbnew.LSET.AllCuMask())
        else: k.SetLayer(layer)
        o = k.Outline(); o.NewOutline()
        for x, y in pts: o.Append(MM(x + OFF[0]), MM(y + OFF[1]))
        k.SetDoNotAllowTracks(tracks); k.SetDoNotAllowVias(vias); k.SetDoNotAllowZoneFills(fills)
        k.SetDoNotAllowPads(False); k.SetDoNotAllowFootprints(False); k.SetZoneName(name); b.Add(k)

    # ------------------------------------------------------------------ U1 (bottom edge)
    # U1 (MC33269, DPAK) dissipates (VBAT - 3.3V) x I_load into its tab, which is VCC (Vout):
    # VCC copper on both layers around the tab, joined by vias beside the pad (never in it).
    # MH3's keepout takes the copper's top-left corner; the vias sit right of the tab and below it.
    grp(0, 0)
    zone(b, "/VCC", F, rect(159.1, 122.6, 169.0, 129.9), 10, name="U1 tab heatsink (top)")
    zone(b, "/VCC", B, rect(159.1, 122.6, 169.0, 129.9), 10, name="U1 tab heatsink (bottom)")
    for x, y in ((168.5, 124.4), (168.5, 126.0), (168.5, 127.6), (159.7, 128.0), (159.7, 129.3)):
        via(b, "/VCC", x, y)
    track(b, "/VCC", F, 162.5, 120.3, 162.5, 123.2, 0.6)      # C2 (output cap) onto the tab
    rulearea("U1 heatsink: no other tracks", rect(161.2, 123.0, 168.0, 129.9))

    # ------------------------------------------------------------------ R group
    grp(0, 4.0)
    # no tracks or vias on top under the module body (keep it GND, per Espressif's layout guide);
    # the module sits 2.8mm below rev 2, so this one is drawn with that offset
    grp(0, 2.8)
    rulearea("U2 underside: GND only", rect(138.3, 97.6, 152.0, 111.0), tracks=True, vias=True, layer=F)
    grp(0, 4.0)
    # U3 (vertical USB-C): rows A (x=169.59) and B (x=170.99) leave a 0.7mm channel at x=170.29;
    # everything that has to pass between the rows is laid here by hand (y below: rev 2 values)
    A, Bx, C = 169.592, 170.992, 170.292
    # VBUS: both connector pairs out through the channel (0.3: pin pitch), then a 0.6 rail at
    # x=167.4 joining them to D1's anode and U4's VBUS pin
    track(b, "/VBUS", F, A, 103.448, Bx, 103.448, 0.6)     # A9-B4
    track(b, "/VBUS", F, C, 103.448, C, 101.6, 0.3)        # out between A12/B1
    track(b, "/VBUS", F, A, 108.048, Bx, 108.048, 0.6)     # A4-B9
    track(b, "/VBUS", F, C, 108.048, C, 109.6, 0.3)        # out between A1/B12
    track(b, "/VBUS", F, C, 109.6, C, 110.1, 0.6)
    track(b, "/VBUS", F, C, 110.1, 167.4, 110.1, 0.6)
    track(b, "/VBUS", F, 164.09, 97.8, 167.4, 97.8, 0.6)   # D1 anode (D1 0.8mm up from rev 2)
    track(b, "/VBUS", F, 167.4, 97.8, 167.4, 110.1, 0.6)   # rail
    track(b, "/VBUS", F, 167.4, 103.5, 165.4, 103.5, 0.6)  # -> U4 pin 5
    track(b, "/VBUS", F, 165.4, 103.5, 165.4, 104.865, 0.6)
    # D+/D- cross links: D+ on top, D- on the bottom, so they can cross
    track(b, "/USB-D+", F, A, 106.198, Bx, 105.248, 0.25)
    track(b, "/USB-D-", B, A, 105.298, Bx, 106.148, 0.25)
    # D+ from R3 (USB side towards U4) through U4 round the right of the connector to B6
    for (x0, y0, x1, y1) in ((159.6, 105.4, 160.82, 104.18),
                             (160.82, 104.18, 163.76, 104.18), (163.76, 104.18, 164.45, 104.86), (164.45, 104.86, 164.45, 108.94),
                             (164.45, 108.94, 166.24, 110.73), (166.24, 110.73, 171.05, 110.73), (171.05, 110.73, 173.0, 108.78),
                             (173.0, 108.78, 173.0, 106.69), (173.0, 106.69, 171.56, 105.25), (171.56, 105.25, Bx, 105.248)):
        track(b, "/USB-D+", F, x0, y0, x1, y1, 0.25)
    # D- likewise: R4 -> U4 on top, under U4 on the bottom to A7
    for (x0, y0, x1, y1) in ((159.6, 108.6, 161.87, 106.33), (161.87, 106.33, 163.53, 106.33),
                             (166.35, 104.863, 166.35, 108.9)):
        track(b, "/USB-D-", F, x0, y0, x1, y1, 0.25)
    via(b, "/USB-D-", 163.53, 106.33, 0.7, 0.3)
    via(b, "/USB-D-", 166.35, 108.9, 0.7, 0.3)
    for (x0, y0, x1, y1) in ((163.53, 106.33, 164.8, 106.33), (164.8, 106.33, 166.35, 107.88), (166.35, 107.88, 166.35, 108.9),
                             (166.35, 107.88, 168.04, 106.2), (168.04, 106.2, 168.64, 106.2), (168.64, 106.2, 169.53, 105.3),
                             (169.53, 105.3, A, 105.298)):
        track(b, "/USB-D-", B, x0, y0, x1, y1, 0.25)
    # CC2 / CC1: out of the channel on the bottom (the R1/R2 ends are absolute, below)
    track(b, "Net-(U3-CC2)", B, Bx, 104.348, C, 104.348, 0.25)
    track(b, "Net-(U3-CC2)", B, C, 104.348, C, 101.3, 0.25)
    track(b, "Net-(U3-CC1)", B, A, 107.098, C, 107.098, 0.25)
    track(b, "Net-(U3-CC1)", B, C, 107.098, C, 109.9, 0.25)
    track(b, "Net-(U3-CC1)", B, C, 109.9, 171.792, 111.4, 0.25)
    track(b, "Net-(U3-CC1)", B, 171.792, 111.4, 173.3, 111.4, 0.25)
    via(b, "Net-(U3-CC1)", 173.3, 111.4, 0.7, 0.3)
    # U4's GND pin is boxed in by VBUS and the USB lines: own via
    track(b, "GND", F, 165.4, 107.135, 165.4, 108.9, 0.3)
    via(b, "GND", 165.4, 108.9, 0.7, 0.3)

    # ------------------------------------------------------------------ absolute: R1/R2 ends
    grp(0, 0)
    # VBUS out of the channel between A12/B1 and left to the rail, clear of the MH2 hole
    track(b, "/VBUS", F, C, 105.6, 168.99, 104.3, 0.6)
    track(b, "/VBUS", F, 168.99, 104.3, 167.4, 104.3, 0.6)
    # CC2: from the channel (C, 105.3) round the MH2 hole up to R1 left of H1's pin 4
    for (x0, y0, x1, y1) in ((C, 105.3, 168.4, 103.9), (168.4, 103.9, 168.4, 99.3)):
        track(b, "Net-(U3-CC2)", B, x0, y0, x1, y1, 0.25)
    via(b, "Net-(U3-CC2)", 168.4, 99.3, 0.7, 0.3)
    track(b, "Net-(U3-CC2)", F, 168.4, 99.3, 168.0, 98.0, 0.25)
    # CC1: via right of the connector, on top down to R2 at the right edge
    track(b, "Net-(U3-CC1)", F, 173.3, 115.4, 174.6, 116.7, 0.25)
    track(b, "Net-(U3-CC1)", F, 174.6, 116.7, 174.6, 117.0, 0.25)

    # ------------------------------------------------------------------ absolute: bay lines from H1
    # H1 pins 1/3/5 sit in the strip between the board edge and the slot, pins 2/4 below the slot.
    # VBAT_IN: via beside pin 3, round the slot's left end on the bottom, up between D1 and D2
    track(b, "/VBAT_IN", F, 168.367, 91.825, 166.05, 91.8, 0.6)
    via(b, "/VBAT_IN", 166.05, 91.8)
    for (x0, y0, x1, y1) in ((166.05, 91.8, 160.6, 91.8), (160.6, 91.8, 160.6, 104.25), (160.6, 104.25, 161.9, 104.25)):
        track(b, "/VBAT_IN", B, x0, y0, x1, y1, 0.6)
    via(b, "/VBAT_IN", 161.9, 104.25)
    track(b, "/VBAT_IN", F, 161.9, 104.25, 164.093, 105.9, 0.6)
    # SIGNAL: on top past the latch notch, via beside the antenna cut-out, then west on the bottom
    for (x0, y0, x1, y1) in ((163.287, 91.825, 159.0, 91.825), (159.0, 91.825, 159.0, 99.4), (159.0, 99.4, 156.6, 100.0)):
        track(b, "/SIGNAL", F, x0, y0, x1, y1, 0.25)
    via(b, "/SIGNAL", 156.6, 100.0, 0.7, 0.3)
    # DATA: via beside pin 5, along the top edge on the bottom, down at x=159.2 and west
    track(b, "/DATA", F, 173.447, 91.825, 171.15, 91.7, 0.25)
    via(b, "/DATA", 171.15, 91.7, 0.7, 0.3)
    for (x0, y0, x1, y1) in ((171.15, 91.7, 170.48, 91.03), (170.48, 91.03, 159.2, 91.03), (159.2, 91.03, 159.2, 101.28)):
        track(b, "/DATA", B, x0, y0, x1, y1, 0.25)
    # HB: via beside pin 2, down on the bottom at x=162.7, west on top below the module, down the
    # right of J1 on the bottom, west below J1, back on top between R9 and R10 to D5/R12
    track(b, "/HB", F, 165.827, 96.041, 164.75, 96.04, 0.25)
    via(b, "/HB", 164.75, 96.04, 0.7, 0.3)
    track(b, "/HB", B, 164.75, 96.04, 162.7, 98.09, 0.25)
    track(b, "/HB", B, 162.7, 98.09, 162.7, 115.55, 0.25)
    via(b, "/HB", 162.7, 115.55, 0.7, 0.3)
    track(b, "/HB", F, 162.7, 115.55, 144.9, 115.55, 0.25)
    track(b, "/HB", F, 144.9, 115.55, 144.5, 115.95, 0.25)
    via(b, "/HB", 144.5, 115.95, 0.7, 0.3)                    # clear of the GND spine
    track(b, "/HB", B, 144.5, 115.95, 144.5, 123.6, 0.25)
    track(b, "/HB", B, 144.5, 123.6, 131.5, 123.6, 0.25)
    via(b, "/HB", 131.5, 123.6, 0.7, 0.3)
    for (x0, y0, x1, y1) in ((131.5, 123.6, 125.3, 123.6), (125.3, 123.6, 125.3, 118.0),
                             (125.3, 118.0, 123.65, 118.0), (125.3, 118.0, 127.0, 118.0)):   # D5 cathode, R12
        track(b, "/HB", F, x0, y0, x1, y1, 0.25)
    # 3V3 trunk (Espressif: >= 20 mil for VDD3P3): from the tab copper up the module's right edge
    # on the bottom, west under the antenna end of the module, up to module pin 1
    for (x0, y0, x1, y1) in ((161.0, 123.0, 161.0, 120.6), (161.0, 120.6, 159.2, 118.8), (159.2, 118.8, 155.6, 118.8),
                             (155.6, 118.8, 155.6, 102.0), (155.6, 102.0, 134.6, 102.0)):
        track(b, "/VCC", B, x0, y0, x1, y1, 0.5)
    # 0.7mm via, high enough that EN (module pin 2) passes straight below it to C4
    via(b, "/VCC", 134.6, 102.0, 0.7, 0.3)
    track(b, "/VCC", F, 134.6, 102.0, 135.2, 101.28, 0.5)
    track(b, "/VCC", F, 135.2, 101.28, 136.904, 101.28, 0.5)
    # R8 (IO2 pull-up): via below it onto the trunk
    track(b, "/VCC", F, 157.0, 104.8, 157.0, 106.3, 0.3)
    via(b, "/VCC", 157.0, 106.3, 0.7, 0.3)
    track(b, "/VCC", B, 157.0, 106.3, 155.6, 106.3, 0.3)
    # I2C pull-ups R6/R7 (by J1): VCC pads joined, via, on the bottom onto the trunk; J1 pin 2 on
    # top from R6 (the left-hand pull-ups below are fed from J1 pin 2)
    track(b, "/VCC", F, 146.9, 120.98, 150.6, 120.98, 0.3)
    track(b, "/VCC", F, 150.6, 120.98, 151.5, 120.98, 0.3)
    via(b, "/VCC", 151.5, 120.98, 0.7, 0.3)
    track(b, "/VCC", B, 151.5, 120.98, 153.68, 118.8, 0.3)
    track(b, "/VCC", B, 153.68, 118.8, 155.6, 118.8, 0.3)
    track(b, "/VCC", F, 146.9, 120.98, 142.0, 120.98, 0.3)
    track(b, "/VCC", F, 142.0, 120.98, 141.34, 120.61, 0.3)
    # GND spine: module pad 9 along the strip under the pad row to a via by R4 keeps the pours joined
    track(b, "GND", F, 136.904, 113.278, 137.88, 114.9, 0.4)
    track(b, "GND", F, 137.88, 114.9, 159.9, 114.9, 0.4)
    track(b, "GND", F, 159.9, 114.9, 160.6, 114.2, 0.4)
    via(b, "GND", 160.6, 114.2, 0.7, 0.3)
    # copper-free around the M2 holes (screw head on top, standoff on the bottom)
    import math
    for i, (cx, cy) in enumerate(((126.42, 91.73), (172.02, 101.63), (157.92, 123.83))):
        rulearea("M2 hole %d keepout" % (i + 1), [(cx + 3.0 * math.cos(k * math.pi / 8), cy + 3.0 * math.sin(k * math.pi / 8)) for k in range(16)],
                 fills=True)
    # H1 pin 4 (GND) is boxed in below the slot: via beside it
    track(b, "GND", F, 170.907, 96.041, 172.4, 96.45, 0.3)
    via(b, "GND", 172.4, 96.45, 0.6, 0.3)
    # no pour in the strip above the slot (bay pins 1/3/5 only; a GND fill there is an island)
    rulearea("no pour: strip above the H1 slot", rect(158.6, 89.0, 176.5, 92.45), tracks=False, vias=False, fills=True)
    # the pocket between the antenna cut-out and the latch notch can't reach the GND pours
    rulearea("no pour: pocket beside the antenna cut-out", rect(154.67, 93.0, 158.15, 99.6), tracks=False, vias=False, fills=True)
    # H1 slot: 0.5mm copper-free margin (the autorouter only keeps its 0.2mm clearance)
    grp(1.25, 0.25)
    rulearea("H1 slot margin", rect(160.267, 92.183, 173.967, 95.183))

    # ------------------------------------------------------------------ left of the module
    grp(0, 0)
    # SIGNAL / DATA bottom runs under the antenna end of the module to the bay interface diodes
    for (x0, y0, x1, y1) in ((156.6, 100.0, 156.6, 100.83), (156.6, 100.83, 122.3, 100.83), (122.3, 100.83, 122.3, 105.5)):
        track(b, "/SIGNAL", B, x0, y0, x1, y1, 0.25)
    via(b, "/SIGNAL", 122.3, 105.5, 0.7, 0.3)
    track(b, "/SIGNAL", F, 122.3, 105.5, 124.55, 105.5, 0.25)           # D3 cathode
    for (x0, y0, x1, y1) in ((159.2, 101.28, 123.4, 101.28), (123.4, 101.28, 123.4, 109.1)):
        track(b, "/DATA", B, x0, y0, x1, y1, 0.25)
    via(b, "/DATA", 123.4, 109.1, 0.7, 0.3)
    track(b, "/DATA", F, 123.4, 109.1, 124.55, 109.1, 0.25)             # D4 cathode (RX)
    track(b, "/DATA", F, 123.4, 109.1, 122.4, 110.1, 0.25)              # R14 (1k from U5)
    track(b, "/DATA", F, 122.4, 110.1, 121.4, 110.1, 0.25)
    # 3V3 from the trunk via: north on top to C3, C5 (round its GND pad) and R5 (EN pull-up)
    for (x0, y0, x1, y1) in ((134.6, 102.0, 134.0, 101.4), (134.0, 101.4, 134.0, 96.25), (134.0, 98.3, 132.8, 98.3),
                             (134.0, 96.25, 130.1, 96.25), (130.1, 96.25, 130.1, 94.7),
                             (130.1, 96.25, 126.75, 96.25), (126.75, 96.25, 126.0, 97.0), (126.0, 97.0, 126.0, 98.0)):
        track(b, "/VCC", F, x0, y0, x1, y1, 0.3)
    # south on the bottom to R11/R13 (MCU-side bay pull-ups, VCC pads towards the module)
    track(b, "/VCC", B, 134.6, 102.0, 134.6, 109.1, 0.3)
    for y in (105.5, 109.1):
        track(b, "/VCC", F, 132.8, y, 134.6, y, 0.3)
        via(b, "/VCC", 134.6, y, 0.7, 0.3)
    # U5's GND pin (towards the module) is cut off from the pours by the module's escapes: own via
    track(b, "GND", F, 133.04, 112.25, 134.3, 112.25, 0.3)
    via(b, "GND", 134.3, 112.25, 0.6, 0.3)
    # U5 + C6 share a via left of U5; the bottom track from it runs down the right of R12/R9/R10
    # (vias beside their VCC pads) and is fed from J1 pin 2 below the header
    for (x0, y0, x1, y1) in ((126.6, 113.2, 127.9, 114.5), (127.9, 114.5, 128.7, 114.5),
                             (128.7, 114.5, 130.4, 114.5), (130.4, 114.5, 130.7625, 114.15)):
        track(b, "/VCC", F, x0, y0, x1, y1, 0.3)
    via(b, "/VCC", 128.7, 114.5, 0.7, 0.3)
    for (x0, y0, x1, y1) in ((128.7, 114.5, 130.5, 116.3), (130.5, 116.3, 130.5, 125.0),
                             (141.34, 120.61, 141.34, 121.4), (141.34, 121.4, 140.44, 122.3), (140.44, 122.3, 130.5, 122.3)):
        track(b, "/VCC", B, x0, y0, x1, y1, 0.3)
    for y in (118.0, 121.5, 125.0):
        via(b, "/VCC", 130.5, y, 0.7, 0.3)
        track(b, "/VCC", F, 130.5, y, 129.0, y, 0.3)
    # J1 pin 1 (GND, plated through, fed from the bottom pour): keep the top pour out of the sliver
    # between pins 3 and 1, where it would hang on pin 1 by one spoke
    rulearea("no pour sliver at J1 pin 1", rect(139.6, 117.25, 140.95, 118.9), tracks=False, vias=False, fills=True, layer=F)
    grp(0, 0)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(sys.argv[3], b)
    pcbnew.ExportSpecctraDSN(b, sys.argv[4])
    # leave GND to the pours: drop it from the autorouter's netlist
    d = open(sys.argv[4], encoding="utf-8").read()
    gsub = [a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--gnd-pins=")]
    if gsub:   # route GND only between these pins; the pours handle the rest
        d2 = re.sub(r'\(net GND\s*\(pins[^)]*\)\s*\)', '(net GND (pins ' + ' '.join(gsub[0]) + '))', d, count=1)
    else:
        d2 = d if "--keep-gnd" in sys.argv else re.sub(r'\(net GND\s*\(pins[^)]*\)\s*\)', '', d, count=1)
    print("GND removed from DSN:", d2 != d)
    open(sys.argv[4], "w", encoding="utf-8").write(d2)

elif sys.argv[1] == "finish":
    b = pcbnew.LoadBoard(sys.argv[2])
    ok = pcbnew.ImportSpecctraSES(b, sys.argv[3])
    print("SES imported:", ok)
    edge = b.GetBoardEdgesBoundingBox()
    x0, y0 = pcbnew.ToMM(edge.GetLeft()), pcbnew.ToMM(edge.GetTop())
    x1, y1 = pcbnew.ToMM(edge.GetRight()), pcbnew.ToMM(edge.GetBottom())
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = zone(b, "GND", layer, rect(x0, y0, x1, y1), 1, clear=0.3, full=False, name="GND")
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)   # until stitched, see "final"
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(sys.argv[4], b)

elif sys.argv[1] == "widen":
    # widen IN OUT MIN -> Freerouting necks tracks down below MIN at some pads; set them back to MIN
    # (only where that keeps 0.2mm to other-net copper; the rest stay necked, see .kicad_dru)
    b = pcbnew.LoadBoard(sys.argv[2]); w = MM(float(sys.argv[4])); n = kept = 0
    others = [(p.GetNetCode(), p) for f in b.GetFootprints() for p in f.Pads()] + [(t.GetNetCode(), t) for t in b.GetTracks()]
    for t in [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and t.GetWidth() < w]:
        old = t.GetWidth(); t.SetWidth(w); L = t.GetLayer(); shp = t.GetEffectiveShape(L)
        hit = any(nc != t.GetNetCode() and it.IsOnLayer(L) and it.GetEffectiveShape(L).Collide(shp, MM(0.2) - 1)
                  for nc, it in others if it is not t)
        if hit: t.SetWidth(old); kept += 1
        else: n += 1
    pcbnew.SaveBoard(sys.argv[3], b)
    print("tracks widened:", n, "left necked:", kept)

elif sys.argv[1] == "bridge":
    # bridge IN OUT -> tie every GND pour fragment to the main GND: fragments are joined through
    # GND vias and through GND pads (THT on both layers); a fragment not reached from the one with
    # the most pads gets a via where it overlaps a reached fragment on the other layer
    import math
    b = pcbnew.LoadBoard(sys.argv[2]); mm = pcbnew.ToMM
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    gn = b.GetNetsByName()["GND"].GetNetCode()
    gz = {z.GetLayer(): z for z in b.Zones() if z.GetNetCode() == gn and not z.GetIsRuleArea()}
    def ring(p, r, n=16):
        return [p] + [pcbnew.VECTOR2I(int(p.x + r * math.cos(a * 2 * math.pi / n)), int(p.y + r * math.sin(a * 2 * math.pi / n))) for a in range(n)]
    kos = [z for z in b.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
    crt = [c for f in b.GetFootprints() for c in (f.GetCourtyard(F), f.GetCourtyard(B)) if c.OutlineCount()]
    pboxes = pad_boxes(b, 0.35 + 0.2)
    added = 0
    for _ in range(20):
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        frags = [(L, gz[L].GetFilledPolysList(L).Outline(i)) for L in (F, B) for i in range(gz[L].GetFilledPolysList(L).OutlineCount())]
        def find(L, p, r=0):
            return {k for k, (l, o) in enumerate(frags) if l == L for q in (ring(p, r) if r else [p]) if o.PointInside(q)}
        groups, npads = [], {}
        for t in b.GetTracks():
            if t.GetNetCode() == gn and t.Type() == pcbnew.PCB_VIA_T:
                groups.append(find(F, t.GetPosition()) | find(B, t.GetPosition()))
        for fp in b.GetFootprints():
            for p in fp.Pads():
                if p.GetNetCode() != gn: continue
                bb = p.GetBoundingBox(); r = max(bb.GetWidth(), bb.GetHeight()) / 2 + MM(0.45)
                ks = set()
                for L in (F, B):
                    if p.IsOnLayer(L): ks |= find(L, p.GetPosition(), r)
                groups.append(ks)
                for k in ks: npads[k] = npads.get(k, 0) + 1
        main = max(range(len(frags)), key=lambda k: npads.get(k, 0))
        seen = {main}; grew = True
        while grew:
            grew = False
            for g in groups:
                if g & seen and not g <= seen: seen |= g; grew = True
        lost = [k for k in range(len(frags)) if k not in seen and npads.get(k, 0)]
        if not lost: break
        k = max(lost, key=lambda k: npads[k])
        L, o = frags[k]; OL = B if L == F else F
        bb = o.BBox(); best = None
        R = MM(0.35 + 0.1)
        y = bb.GetTop()
        while y <= bb.GetBottom() and not best:
            x = bb.GetLeft()
            while x <= bb.GetRight():
                p = pcbnew.VECTOR2I(int(x), int(y))
                if all(o.PointInside(q) for q in ring(p, R, 12)):
                    other = [j for j in seen if frags[j][0] == OL and all(frags[j][1].PointInside(q) for q in ring(p, R, 12))]
                    if other and not any(z.Outline().Contains(p) for z in kos) and not any(c.Contains(p) for c in crt)                             and not in_boxes(pboxes, mm(p.x), mm(p.y)):
                        best = p; break
                x += MM(0.2)
            y += MM(0.2)
        if not best:
            print("no bridge spot for", b.GetLayerName(L), "fragment", "%.1f,%.1f-%.1f,%.1f" % tuple(mm(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom())))
            break
        via(b, "GND", round(mm(best.x), 2), round(mm(best.y), 2), 0.7, 0.3); added += 1
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(sys.argv[3], b)
    print("bridge vias:", added)

elif sys.argv[1] == "final":
    # final IN OUT -> drop pour islands that stitching didn't tie in
    b = pcbnew.LoadBoard(sys.argv[2])
    gz = [z for z in b.Zones() if z.GetNetname() == "GND" and not z.GetIsRuleArea()]
    for z in gz:
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    # stitching vias whose pour islands just went away (unlocked GND vias without fill around them)
    gone = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == "GND" and not t.IsLocked()
            and not all(z.HitTestFilledArea(z.GetLayer(), t.GetPosition()) for z in gz)]
    for t in gone: b.Remove(t)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    print("floating stitch vias removed:", len(gone))
    pcbnew.SaveBoard(sys.argv[3], b)

elif sys.argv[1] == "stitch":
    # stitch IN.kicad_pcb OUT.kicad_pcb REF:PAD ...  -> GND via beside each listed pad
    import math
    b = pcbnew.LoadBoard(sys.argv[2])
    gnd = b.GetNetsByName()["GND"].GetNetCode()
    VR, CL = 0.3, 0.25
    edge = b.GetBoardEdgesBoundingBox()
    X0, Y0, X1, Y1 = [pcbnew.ToMM(v) for v in (edge.GetLeft(), edge.GetTop(), edge.GetRight(), edge.GetBottom())]
    obst = []   # (kind, geometry, layers) for other-net copper
    for fp in b.GetFootprints():
        for pd in fp.Pads():
            if pd.GetNetCode() == gnd: continue
            bb = pd.GetBoundingBox()
            obst.append(("box", [pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom())]))
    for t in b.GetTracks():
        if t.GetNetCode() == gnd: continue
        if t.Type() == pcbnew.PCB_VIA_T:
            c = t.GetPosition(); r = pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) / 2
            obst.append(("circ", (pcbnew.ToMM(c.x), pcbnew.ToMM(c.y), r)))
        else:
            obst.append(("seg", (pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y), pcbnew.ToMM(t.GetEnd().x), pcbnew.ToMM(t.GetEnd().y), pcbnew.ToMM(t.GetWidth()) / 2)))
    nogo = [z for z in b.Zones() if (z.GetIsRuleArea() and z.GetDoNotAllowVias()) or (not z.GetIsRuleArea() and z.GetNetCode() != gnd)]
    def segdist(px, py, ax, ay, bx, by):
        dx, dy = bx - ax, by - ay; L = dx * dx + dy * dy
        t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
        return math.hypot(px - ax - t * dx, py - ay - t * dy)
    def clear(x, y, r):
        if x - r < X0 + 0.5 or x + r > X1 - 0.5 or y - r < Y0 + 0.5 or y + r > Y1 - 0.5: return False
        if not b.GetBoardEdgesBoundingBox().Contains(pcbnew.VECTOR2I_MM(x, y)): return False
        for z in nogo:
            for dx, dy in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r)):
                if z.Outline().Contains(pcbnew.VECTOR2I_MM(x + dx, y + dy)): return False
        for k, g in obst:
            if k == "box":
                dx = max(g[0] - x, x - g[2], 0); dy = max(g[1] - y, y - g[3], 0)
                if math.hypot(dx, dy) < r + CL: return False
            elif k == "circ":
                if math.hypot(x - g[0], y - g[1]) < r + g[2] + CL: return False
            else:
                if segdist(x, y, *g[:4]) < r + g[4] + CL: return False
        return True
    def pathclear(ax, ay, bx, by, w):
        for i in range(1, 11):
            t = i / 10
            if not clear(ax + (bx - ax) * t, ay + (by - ay) * t, w / 2): return False
        return True
    added = 0
    for spec in sys.argv[4:]:
        ref, num = spec.split(":")
        fp = b.FindFootprintByReference(ref)
        pd = [p for p in fp.Pads() if p.GetNumber() == num][0]
        cx, cy = pcbnew.ToMM(pd.GetPosition().x), pcbnew.ToMM(pd.GetPosition().y)
        layer = pcbnew.B_Cu if pd.IsOnLayer(pcbnew.B_Cu) and not pd.IsOnLayer(pcbnew.F_Cu) else pcbnew.F_Cu
        done = False
        for rr in (1.0, 1.3, 1.6, 2.0, 2.5):
            for k in range(24):
                a = 2 * math.pi * k / 24
                x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
                if clear(x, y, VR) and pathclear(cx, cy, x, y, 0.3):
                    via(b, "GND", round(x, 3), round(y, 3), 0.6, 0.3)
                    track(b, "GND", layer, cx, cy, round(x, 3), round(y, 3), 0.3)
                    obst  # (GND items don't block other GND vias)
                    added += 1; done = True; break
            if done: break
        if not done: print("no spot for", spec)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(sys.argv[3], b)
    print("stitch vias added:", added)

elif sys.argv[1] == "gridstitch":
    # gridstitch IN OUT PITCH -> GND via wherever both GND pours have solid copper around it
    b = pcbnew.LoadBoard(sys.argv[2]); pitch = float(sys.argv[4])
    gz = [z for z in b.Zones() if z.GetNetname() == "GND" and not z.GetIsRuleArea()]
    def solid(z, x, y, r):
        L = z.GetLayer()
        pts = [(x, y)] + [(x + r * c, y + r * s) for c, s in ((1, 0), (-1, 0), (0, 1), (0, -1), (.7, .7), (-.7, .7), (.7, -.7), (-.7, -.7))]
        return all(z.HitTestFilledArea(L, pcbnew.VECTOR2I_MM(px, py)) for px, py in pts)
    edge = b.GetBoardEdgesBoundingBox()
    x0, y0, x1, y1 = [pcbnew.ToMM(v) for v in (edge.GetLeft(), edge.GetTop(), edge.GetRight(), edge.GetBottom())]
    n = 0; x = x0 + 1.5
    while x < x1 - 1:
        y = y0 + 1.5
        while y < y1 - 1:
            if all(solid(z, x, y, 0.3 + 0.35) for z in gz):
                via(b, "GND", round(x, 2), round(y, 2), 0.6, 0.3); n += 1
            y += pitch
        x += pitch
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(sys.argv[3], b)
    print("grid stitch vias:", n)

elif sys.argv[1] == "islandstitch":
    # islandstitch IN OUT -> every GND pour island gets a via to the other side's pour
    b = pcbnew.LoadBoard(sys.argv[2])
    gz = {z.GetLayer(): z for z in b.Zones() if z.GetNetname() == "GND" and not z.GetIsRuleArea()}
    gvias = [t.GetPosition() for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == "GND"]
    added = 0
    for L, z in gz.items():
        other = gz[pcbnew.B_Cu if L == pcbnew.F_Cu else pcbnew.F_Cu]
        OL = other.GetLayer()
        polys = z.GetFilledPolysList(L)
        for i in range(polys.OutlineCount()):
            ol = polys.Outline(i)
            if any(ol.PointInside(v) for v in gvias): continue
            allv = [t.GetPosition() for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
            bb = ol.BBox()
            x0, y0, x1, y1 = [pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom())]
            r = 0.3 + 0.2
            ring = [(1, 0), (-1, 0), (0, 1), (0, -1), (.7, .7), (-.7, .7), (.7, -.7), (-.7, -.7)]
            kos = [k for k in b.Zones() if k.GetIsRuleArea() and k.GetDoNotAllowVias()]
            spot = None
            y = y0
            while y <= y1 and not spot:
                x = x0
                while x <= x1:
                    pts = [(x, y)] + [(x + r * c, y + r * s) for c, s in ring]
                    if any(k.Outline().Contains(pcbnew.VECTOR2I_MM(x, y)) for k in kos) or                        any(abs(pcbnew.ToMM(v.x) - x) < 1.0 and abs(pcbnew.ToMM(v.y) - y) < 1.0 for v in allv):
                        x += 0.2; continue
                    if all(z.HitTestFilledArea(L, pcbnew.VECTOR2I_MM(px, py)) and other.HitTestFilledArea(OL, pcbnew.VECTOR2I_MM(px, py)) for px, py in pts):
                        spot = (round(x, 2), round(y, 2)); break
                    x += 0.2
                y += 0.2
            if spot:
                via(b, "GND", spot[0], spot[1], 0.6, 0.3); gvias.append(pcbnew.VECTOR2I_MM(*spot)); added += 1
            else:
                print("island without a spot on", b.GetLayerName(L), "bbox %.1f,%.1f-%.1f,%.1f" % (x0, y0, x1, y1))
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(sys.argv[3], b)
    print("island vias:", added)

elif sys.argv[1] == "cleanup":
    # cleanup IN OUT: drop GND vias in pad-less pour fragments, drop vias with copper on
    # only one layer, solid zone connection for the wire-pad GND (3A return)
    b = pcbnew.LoadBoard(sys.argv[2])
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    gz = {z.GetLayer(): z for z in b.Zones() if z.GetNetname() == "GND" and not z.GetIsRuleArea()}
    pads = [p.GetPosition() for f in b.GetFootprints() for p in f.Pads() if p.GetNetname() == "GND"]
    # the main fragment on each layer = the one with the most GND pads
    removed = 0
    for L, z in gz.items():
        polys = z.GetFilledPolysList(L)
        counts = [sum(1 for p in pads if polys.Outline(i).PointInside(p)) for i in range(polys.OutlineCount())]
        for i in range(polys.OutlineCount()):
            if counts[i] > 0: continue
            ol = polys.Outline(i)
            for t in list(b.GetTracks()):
                if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == "GND" and ol.PointInside(t.GetPosition()) and not t.IsLocked():
                    b.Remove(t); removed += 1
    # vias touched by tracks on only one layer and not sitting in a same-net zone
    dang = 0
    for v in [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() != "GND"]:
        layers = set()
        for t in b.GetTracks():
            if t.Type() == pcbnew.PCB_TRACE_T and t.GetNetCode() == v.GetNetCode() and (t.GetStart() == v.GetPosition() or t.GetEnd() == v.GetPosition()):
                layers.add(t.GetLayer())
        inzone = any(z.GetNetCode() == v.GetNetCode() and not z.GetIsRuleArea() and z.HitTestFilledArea(z.GetLayer(), v.GetPosition()) for z in b.Zones())
        if len(layers) < 2 and not inzone and not v.IsLocked():
            b.Remove(v); dang += 1
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(sys.argv[3], b)
    print("removed fragment vias:", removed, "dangling vias:", dang)

elif sys.argv[1] == "gapstitch":
    # gapstitch IN OUT LIMIT [DIAM] -> extra GND vias (DIAM/0.3mm, default 0.7 for JLCDFM's
    # 0.2mm annular ring) on a finished board, only where both GND pours are solid around the
    # via (so it can't touch other copper), outside courtyards and via keep-outs, >= 1.5mm from
    # other GND vias. First every pour fragment gets >= 2 ties to the other layer, then vias go
    # where the overlap is farthest from a tie, until all is within LIMIT.
    import math
    b = pcbnew.LoadBoard(sys.argv[2]); LIMIT = float(sys.argv[4])
    DIAM = float(sys.argv[5]) if len(sys.argv) > 5 else 0.7
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    mm = pcbnew.ToMM
    gnd = b.GetNetsByName()["GND"].GetNetCode()
    gz = {z.GetLayer(): z for z in b.Zones() if z.GetNetCode() == gnd and not z.GetIsRuleArea()}
    def filled(L, x, y): return gz[L].HitTestFilledArea(L, V(x, y))
    ties = [(mm(t.GetPosition().x), mm(t.GetPosition().y)) for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetCode() == gnd]
    ties += [(mm(p.GetPosition().x), mm(p.GetPosition().y)) for f in b.GetFootprints() for p in f.Pads()
             if p.GetNetCode() == gnd and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
    edge = b.GetBoardEdgesBoundingBox()
    X0, Y0, X1, Y1 = [mm(v) for v in (edge.GetLeft(), edge.GetTop(), edge.GetRight(), edge.GetBottom())]
    step = 0.25
    overlap = [(X0 + step * (i + .5), Y0 + step * (j + .5)) for i in range(int((X1 - X0) / step)) for j in range(int((Y1 - Y0) / step))]
    overlap = [(x, y) for x, y in overlap if filled(F, x, y) and filled(B, x, y)]
    R = DIAM / 2 + 0.1   # via radius + margin inside the fill
    ring = [(R * math.cos(a * math.pi / 6), R * math.sin(a * math.pi / 6)) for a in range(12)]
    kos = [z for z in b.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
    crt = [s for f in b.GetFootprints() for s in (f.GetCourtyard(pcbnew.F_CrtYd), f.GetCourtyard(pcbnew.B_CrtYd)) if s.OutlineCount()]
    pboxes = pad_boxes(b, DIAM / 2 + 0.2)
    cand = [(x, y) for x, y in overlap
            if all(filled(F, x + dx, y + dy) and filled(B, x + dx, y + dy) for dx, dy in ring)
            and not any(k.Outline().Contains(V(x, y)) for k in kos) and not any(c.Contains(V(x, y)) for c in crt)
            and not in_boxes(pboxes, x, y)]
    added = []
    def add(p):
        added.append(p); ties.append(p)
        cand[:] = [c for c in cand if math.hypot(c[0] - p[0], c[1] - p[1]) >= 1.5]
    cand = [c for c in cand if min(math.hypot(c[0] - t[0], c[1] - t[1]) for t in ties) >= 1.5]
    for L in (F, B):
        polys = gz[L].GetFilledPolysList(L)
        for i in range(polys.OutlineCount()):
            ol = polys.Outline(i)
            while True:
                inside = [t for t in ties if ol.PointInside(V(*t))]
                spots = [c for c in cand if ol.PointInside(V(*c))]
                if len(inside) >= 2 or not spots: break
                add(max(spots, key=lambda c: min([math.hypot(c[0] - t[0], c[1] - t[1]) for t in inside] or [0])))
    n_frag = len(added)
    todo = list(overlap)
    while todo and cand:
        dist, wx, wy = max((min(math.hypot(x - t[0], y - t[1]) for t in ties), x, y) for x, y in todo)
        if dist <= LIMIT: break
        c = min(cand, key=lambda c: math.hypot(c[0] - wx, c[1] - wy))
        if math.hypot(c[0] - wx, c[1] - wy) > LIMIT:
            todo.remove((wx, wy)); continue   # no via spot close enough to this point
        add(c)
    for x, y in added:
        via(b, "GND", round(x, 2), round(y, 2), DIAM, 0.3)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(sys.argv[3], b)
    print("gap stitch vias: %d for fragments, %d for coverage" % (n_frag, len(added) - n_frag))

elif sys.argv[1] == "syncfields":
    # syncfields IN OUT SCH FIELD... -> copy these symbol fields onto the matching footprints
    # (hidden, on the LCSC field's layer), like "Update PCB from Schematic" does for fields
    # read the symbol instances straight from the .kicad_sch (kicad-cli's BOM export groups by
    # reference *prefix* even with --group-by Reference, merging different parts into one row)
    b = pcbnew.LoadBoard(sys.argv[2]); names = sys.argv[5:]
    text = open(sys.argv[4], encoding="utf8").read().replace("\r\n", "\n")
    unq = lambda s: s.replace('\\"', '"').replace("\\\\", "\\")
    n = 0
    for blk in re.findall(r'\n\t\(symbol\n\t\t\(lib_id .*?\n\t\)', text, re.S):
        props = {k: unq(v) for k, v in re.findall(r'\n\t\t\(property "([^"]*)" "((?:[^"\\]|\\.)*)"', blk)}
        fp = b.FindFootprintByReference(props.get("Reference", ""))
        if not fp: continue
        for name in names:
            val = props.get(name, "")
            if not val or (fp.HasField(name) and fp.GetFieldText(name) == val): continue
            fp.SetField(name, val)
            fld, ref = fp.GetField(name), fp.GetField("LCSC") if fp.HasField("LCSC") else fp.Reference()
            fld.SetVisible(False); fld.SetLayer(ref.GetLayer()); fld.SetPosition(ref.GetPosition())
            n += 1
    pcbnew.SaveBoard(sys.argv[3], b)
    print("fields set:", n)

elif sys.argv[1] == "jumper":
    # jumper IN OUT NET LAYER W x0,y0 x1,y1 ... : polyline track, refused if it hits other-net copper
    import math
    b = pcbnew.LoadBoard(sys.argv[2]); net, layer, w = sys.argv[4], b.GetLayerID(sys.argv[5]), float(sys.argv[6])
    pts = [tuple(map(float, a.split(","))) for a in sys.argv[7:]]
    nc = b.GetNetsByName()[net].GetNetCode()
    tr = pcbnew.PCB_TRACK(b); tr.SetWidth(MM(w)); tr.SetLayer(layer); tr.SetNetCode(nc)
    bad = []
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        tr.SetStart(V(ax, ay)); tr.SetEnd(V(bx, by))
        shp = tr.GetEffectiveShape(layer)
        for fp in b.GetFootprints():
            for pd in fp.Pads():
                if pd.GetNetCode() != nc and pd.IsOnLayer(layer) and pd.GetEffectiveShape(layer).Collide(shp, MM(0.2)):
                    bad.append(fp.GetReference() + ":" + pd.GetNumber())
        for t in b.GetTracks():
            if t.GetNetCode() != nc and t.IsOnLayer(layer) and t.GetEffectiveShape(layer).Collide(shp, MM(0.2)):
                bad.append("track " + t.GetNetname())
    if bad:
        print("jumper refused, hits:", sorted(set(bad)))
    else:
        for (ax, ay), (bx, by) in zip(pts, pts[1:]): track(b, net, layer, ax, ay, bx, by, w)
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        print("jumper added")
    pcbnew.SaveBoard(sys.argv[3], b)
