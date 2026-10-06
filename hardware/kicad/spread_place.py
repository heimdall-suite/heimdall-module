"""Spread the parts for hand soldering once the board had room to spare (M2 screws, corners
chamfered): the left-hand group gets >= 1mm between courtyards and its HB/BOOT part moves
below the module, U1 goes to the bottom edge with C1/C2 beside it, R3/R4, D1/D2 and R6/R7 apart.
Strips copper and rule areas (route_pcb.py prep redraws them)."""
import pcbnew, sys
B = sys.argv[1]
MM = pcbnew.FromMM
b = pcbnew.LoadBoard(B)
dead = list(b.GetTracks()) + list(b.Zones())
PLACE = {
    # left of the module, in module pin order: EN/3V3, PPM (pin 3), DATA_RX (pin 4), DATA_TX (pin 6)
    'C5': (131.30, 94.70, 0), 'C3': (131.80, 98.30, 0), 'R5': (126.00, 99.00, 90), 'C4': (131.80, 101.90, 180),
    'R11': (131.80, 105.50, 180), 'D3': (125.60, 105.50, 0),
    'R13': (131.80, 109.10, 180), 'D4': (125.60, 109.10, 0), 'R14': (121.40, 109.10, 90),
    'U5': (131.90, 113.20, 180), 'C6': (125.60, 113.20, 180),
    # below the module, left of J1: HB (pin 7) and BOOT (pin 8)
    'D5': (122.60, 118.00, 0), 'R12': (128.00, 118.00, 180), 'R9': (128.00, 121.50, 0),
    'R10': (128.00, 125.00, 0), 'JP1': (122.60, 125.00, 0),
    # regulator at the bottom edge, input cap by its VBAT pin, output cap by the tab
    'U1': (167.70, 126.00, 0), 'C1': (168.00, 120.30, 0), 'C2': (162.50, 119.10, 90),
    # USB series resistors off the module (module side towards it), D1 up from D2, I2C pull-ups apart
    'R3': (158.60, 109.40, 180), 'R4': (158.60, 112.60, 180), 'D1': (161.90, 101.80, 0),
    'R6': (146.90, 119.98, 90), 'R7': (150.60, 119.98, -90),
}
for ref, (x, y, r) in PLACE.items():
    f = b.FindFootprintByReference(ref)
    f.SetOrientationDegrees(r)
    f.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
# JP1's label below it (left of it is the board edge)
b.FindFootprintByReference('JP1').Reference().SetPosition(pcbnew.VECTOR2I(MM(122.6), MM(127.6)))
for it in dead:
    b.Remove(it)
pcbnew.SaveBoard(B, b)
