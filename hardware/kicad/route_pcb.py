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
    # Board fitted to MULTI-Module_Bangood_4-in-1_Case (see case_place in the commit log): the hand
    # routes are drawn per placement group with that group's offset from the rev 2 layout
    #   L (module, left side, J2):            +0.0, +2.8
    #   R (USB-C, ESD, D1/D2, R3/R4, C1):     +0.0, +4.0
    #   U1 (regulator):                       +4.6, +3.7
    #   H1 (bay header + slot):               +1.25, +0.25
    # Routes that cross groups are drawn in absolute coordinates (offset 0).
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

    # ------------------------------------------------------------------ U1 group
    # U1 (MC33269, DPAK) dissipates (VBAT - 3.3V) x I_load into its tab, which is VCC (Vout):
    # VCC copper on both layers around the tab, joined by vias beside the pad (never in it).
    # The bottom copper reaches further left so the 3V3 trunk and R11's feed can land in it.
    grp(0, 0)
    zone(b, "/VCC", F, rect(159.1, 116.0, 168.0, 122.3), 10, name="U1 tab heatsink (top)")
    zone(b, "/VCC", B, rect(155.2, 116.0, 168.0, 122.3), 10, name="U1 tab heatsink (bottom)")
    for x, y in ((159.7, 116.7), (159.7, 118.1), (159.7, 119.5)):
        via(b, "/VCC", x, y)
    track(b, "/VCC", F, 158.0, 119.7, 159.7, 119.5, 0.6)      # C2 (output cap) onto the tab copper
    rulearea("U1 heatsink: no other tracks", rect(160.2, 116.6, 168.0, 122.3))
    # and none across the bottom copper's left part either (the trunk and R11 land there)
    rulearea("U1 heatsink bottom: no other tracks", rect(155.8, 116.6, 160.2, 122.3), layer=B)

    # ------------------------------------------------------------------ L group
    grp(0, 2.8)
    # no tracks or vias on top under the module body (keep it GND, per Espressif's layout guide)
    rulearea("U2 underside: GND only", rect(138.3, 97.6, 152.0, 111.0), tracks=True, vias=True, layer=F)

    # ------------------------------------------------------------------ R group
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
    track(b, "/VBUS", F, 164.09, 98.6, 167.4, 98.6, 0.6)   # D1 anode
    track(b, "/VBUS", F, 167.4, 98.6, 167.4, 110.1, 0.6)   # rail
    track(b, "/VBUS", F, 167.4, 103.5, 165.4, 103.5, 0.6)  # -> U4 pin 5
    track(b, "/VBUS", F, 165.4, 103.5, 165.4, 104.865, 0.6)
    # D+/D- cross links: D+ on top, D- on the bottom, so they can cross
    track(b, "/USB-D+", F, A, 106.198, Bx, 105.248, 0.25)
    track(b, "/USB-D-", B, A, 105.298, Bx, 106.148, 0.25)
    # D+ from R3 through U4 round the right of the connector to B6
    for (x0, y0, x1, y1) in ((157.3, 105.2, 158.19, 105.2), (158.19, 105.2, 158.19, 104.53), (158.19, 104.53, 158.55, 104.18),
                             (158.55, 104.18, 163.76, 104.18), (163.76, 104.18, 164.45, 104.86), (164.45, 104.86, 164.45, 108.94),
                             (164.45, 108.94, 166.24, 110.73), (166.24, 110.73, 171.05, 110.73), (171.05, 110.73, 173.0, 108.78),
                             (173.0, 108.78, 173.0, 106.69), (173.0, 106.69, 171.56, 105.25), (171.56, 105.25, Bx, 105.248)):
        track(b, "/USB-D+", F, x0, y0, x1, y1, 0.25)
    # D- likewise: R4 -> U4 on top, under U4 on the bottom to A7
    for (x0, y0, x1, y1) in ((157.3, 107.4, 158.37, 106.33), (158.37, 106.33, 163.53, 106.33),
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
    # VBUS out of the channel between A12/B1 and left to the rail, clear of the M3 hole
    track(b, "/VBUS", F, C, 105.6, 168.99, 104.3, 0.6)
    track(b, "/VBUS", F, 168.99, 104.3, 167.4, 104.3, 0.6)
    # CC2: from the channel (C, 105.3) round the M3 hole up to R1 left of H1's pin 4
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
    # SIGNAL: on top past the latch notch, via beside the antenna cut-out, then the L-group bottom run
    for (x0, y0, x1, y1) in ((163.287, 91.825, 159.0, 91.825), (159.0, 91.825, 159.0, 99.4), (159.0, 99.4, 156.6, 100.0)):
        track(b, "/SIGNAL", F, x0, y0, x1, y1, 0.25)
    via(b, "/SIGNAL", 156.6, 100.0, 0.7, 0.3)
    # DATA: via beside pin 5, along the top edge on the bottom, down at x=159.2 to the L-group run
    track(b, "/DATA", F, 173.447, 91.825, 171.15, 91.7, 0.25)
    via(b, "/DATA", 171.15, 91.7, 0.7, 0.3)
    for (x0, y0, x1, y1) in ((171.15, 91.7, 170.48, 91.03), (170.48, 91.03, 159.2, 91.03), (159.2, 91.03, 159.2, 101.28)):
        track(b, "/DATA", B, x0, y0, x1, y1, 0.25)
    # HB: via beside pin 2, down on the bottom at x=162.7, then west on top below the module
    track(b, "/HB", F, 165.827, 96.041, 164.75, 96.04, 0.25)
    via(b, "/HB", 164.75, 96.04, 0.7, 0.3)
    track(b, "/HB", B, 164.75, 96.04, 162.7, 98.09, 0.25)
    track(b, "/HB", B, 162.7, 98.09, 162.7, 115.55, 0.25)
    via(b, "/HB", 162.7, 115.55, 0.7, 0.3)
    track(b, "/HB", F, 162.7, 115.55, 135.15, 115.55, 0.25)
    track(b, "/HB", F, 135.15, 115.55, 134.1, 116.14, 0.25)
    # 3V3 trunk start: from the bottom heatsink copper up the module's right edge (the rest is L)
    track(b, "/VCC", B, 155.6, 116.4, 155.6, 102.2, 0.5)
    # I2C pull-ups R9/R10 (by J2): VCC pads joined, via, on the bottom into the heatsink copper
    track(b, "/VCC", F, 147.559, 120.978, 150.099, 120.978, 0.3)
    track(b, "/VCC", F, 150.099, 120.978, 151.5, 120.978, 0.3)
    via(b, "/VCC", 151.5, 120.978, 0.7, 0.3)
    track(b, "/VCC", B, 151.5, 120.978, 155.6, 120.978, 0.3)
    # R11's feed down into the bottom heatsink copper
    track(b, "/VCC", B, 157.0, 115.4, 157.0, 116.4, 0.3)
    # GND spine: module pad 9 along the strip under the pad row to C1's GND pad keeps the pours joined
    track(b, "GND", F, 136.904, 113.278, 137.88, 114.9, 0.4)
    track(b, "GND", F, 137.88, 114.9, 160.8, 114.9, 0.4)
    track(b, "GND", F, 160.8, 114.9, 161.8, 113.8, 0.4)
    # copper-free around the M3 holes (cheese/socket head up to 5.5mm on top, standoff on the bottom)
    import math
    for i, (cx, cy) in enumerate(((126.42, 91.73), (172.02, 101.63), (157.92, 123.83))):
        rulearea("M3 hole %d keepout" % (i + 1), [(cx + 3.0 * math.cos(k * math.pi / 8), cy + 3.0 * math.sin(k * math.pi / 8)) for k in range(16)],
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

    # ------------------------------------------------------------------ L group: left side
    grp(0, 2.8)
    # SIGNAL / DATA bottom runs under the antenna cut-out to the bay interface diodes
    for (x0, y0, x1, y1) in ((156.6, 97.2, 156.6, 98.03), (156.6, 98.03, 125.4, 98.03), (125.4, 98.03, 125.4, 101.9)):
        track(b, "/SIGNAL", B, x0, y0, x1, y1, 0.25)
    via(b, "/SIGNAL", 125.4, 101.9, 0.7, 0.3)
    track(b, "/SIGNAL", F, 125.4, 101.9, 126.65, 101.9, 0.25)          # D3 cathode
    for (x0, y0, x1, y1) in ((159.2, 98.48, 126.3, 98.48), (126.3, 98.48, 126.3, 104.27), (126.3, 104.27, 125.6, 104.97)):
        track(b, "/DATA", B, x0, y0, x1, y1, 0.25)
    via(b, "/DATA", 125.6, 104.97, 0.7, 0.3)
    track(b, "/DATA", F, 125.6, 104.97, 126.65, 103.95, 0.25)          # D4 cathode (RX)
    track(b, "/DATA", F, 125.6, 104.97, 124.2, 106.4, 0.25)            # R17 (1k from U5)
    track(b, "/DATA", F, 124.2, 106.4, 124.2, 107.3, 0.25)
    # DATA transmit: module pad 6 (IO7) -> U5 input, U5 output -> R17 under C6
    track(b, "/DATA_TX", F, 136.904, 105.978, 136.1, 106.2, 0.25)
    track(b, "/DATA_TX", F, 136.1, 106.2, 135.4, 106.7, 0.25)
    track(b, "/DATA_TX", F, 135.4, 106.7, 134.54, 106.7, 0.25)
    for (x0, y0, x1, y1) in ((132.26, 105.75, 131.8, 105.3), (131.8, 105.3, 126.8, 105.3),
                             (126.8, 105.3, 126.2, 105.9), (126.2, 105.9, 126.2, 107.3)):
        track(b, "/DATA_DRV", F, x0, y0, x1, y1, 0.25)
    # U5 supply: VCC via between U5 and C6 onto the bottom 3V3 track; GND vias beside U5 pin 3 and C6
    track(b, "/VCC", F, 132.26, 107.65, 131.25, 108.05, 0.3)
    track(b, "/VCC", F, 131.25, 108.05, 130.25, 106.9, 0.3)
    via(b, "/VCC", 131.25, 108.05, 0.6, 0.3)
    track(b, "/VCC", B, 131.25, 108.05, 134.6, 108.05, 0.3)
    track(b, "GND", F, 134.54, 105.75, 135.3, 105.0, 0.3)
    via(b, "GND", 135.3, 105.0, 0.6, 0.3)
    track(b, "GND", F, 128.25, 106.9, 127.3, 106.0, 0.3)
    via(b, "GND", 127.3, 106.0, 0.6, 0.3)
    # HB_OUT: module pad 7 (IO8) under U5 to D6, R12 (its pull-up) tapped on the way
    for (x0, y0, x1, y1) in ((136.904, 107.478, 136.0, 107.8), (136.0, 107.8, 135.3, 108.73),
                             (135.3, 108.73, 129.6, 108.73), (129.6, 108.73, 128.75, 109.3)):
        track(b, "/HB_OUT", F, x0, y0, x1, y1, 0.25)
    track(b, "/HB_OUT", F, 130.4, 108.73, 130.4, 109.9, 0.25)
    # HB: under J2's top edge and up the left side to R15/D6
    for (x0, y0, x1, y1) in ((134.1, 113.34, 126.06, 113.34), (126.06, 113.34, 124.1, 111.37),
                             (124.1, 111.37, 124.1, 109.3), (124.1, 109.3, 126.65, 109.3)):
        track(b, "/HB", F, x0, y0, x1, y1, 0.25)
    # 3V3 trunk (Espressif: >= 20 mil for VDD3P3): left under the antenna end of the module, up next
    # to module pin 1 (an L, so the bottom under the module stays free for the right-hand pins);
    # short top branch to C3
    track(b, "/VCC", B, 155.6, 99.4, 134.6, 99.4, 0.5)
    via(b, "/VCC", 134.6, 99.4)
    track(b, "/VCC", F, 134.6, 99.4, 135.2, 98.48, 0.5)
    track(b, "/VCC", F, 135.2, 98.48, 136.904, 98.478, 0.5)
    track(b, "/VCC", F, 134.6, 99.4, 133.9, 98.7, 0.3)
    track(b, "/VCC", F, 133.9, 98.7, 133.9, 96.2, 0.3)
    track(b, "/VCC", F, 133.9, 96.2, 132.811, 94.953, 0.3)
    # on to C5 (bulk cap): C5 and C3 face each other with opposite pads, so round C5's GND pad
    track(b, "/VCC", F, 133.9, 96.2, 133.9, 93.45, 0.3)
    track(b, "/VCC", F, 133.9, 93.45, 130.1, 93.45, 0.3)
    track(b, "/VCC", F, 130.1, 93.45, 130.1, 91.9, 0.3)
    track(b, "/VCC", F, 127.366, 94.334, 128.3, 93.45, 0.3)        # R8 (EN pull-up)
    track(b, "/VCC", F, 128.3, 93.45, 130.1, 93.45, 0.3)
    # JP1's GND pad is boxed in on top by HB and the IO9 run: own via
    track(b, "GND", F, 127.05, 111.6, 128.35, 111.6, 0.3)
    via(b, "GND", 128.35, 111.6, 0.6, 0.3)
    # left-hand 3V3 group (R12/R13 pull-ups, J2, I2C pull-ups): from the trunk via, down on the bottom
    track(b, "/VCC", B, 134.6, 99.4, 134.6, 109.2, 0.3)
    track(b, "/VCC", B, 134.6, 109.2, 133.8, 110.3, 0.3)
    via(b, "/VCC", 133.8, 110.3, 0.7, 0.3)   # below the module's IO8/IO9 escapes
    track(b, "/VCC", F, 133.8, 110.3, 132.4, 109.9, 0.3)
    # R14/R16 (MCU-side bay pull-ups): VCC pad straight onto that bottom track
    for y in (101.9, 103.95):
        track(b, "/VCC", F, 133.4, y, 134.6, y, 0.3)
        via(b, "/VCC", 134.6, y, 0.7, 0.3)
    # R11 (IO2 pull-up, VCC pad at the bottom): via below it, down on the bottom (absolute part above)
    track(b, "/VCC", F, 157.0, 102.0, 157.0, 103.5, 0.3)
    via(b, "/VCC", 157.0, 103.5, 0.7, 0.3)
    track(b, "/VCC", B, 157.0, 103.5, 157.0, 112.6, 0.3)
    # J2 pin 1 (GND, plated through, fed from the bottom pour): the routing round the header leaves
    # a top-pour sliver between pins 3 and 1 that hangs on pin 1 by one spoke; keep the pour out
    rulearea("no pour sliver at J2 pin 1", rect(139.6, 114.45, 140.95, 116.1), tracks=False, vias=False, fills=True, layer=F)
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
