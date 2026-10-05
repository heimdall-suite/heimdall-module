"""Bay interface on the PCB: sync to the netlist (D5 out; U5/C6 in, R17 moved), place, strip copper.
Run with KiCad's python from hardware/kicad:  python bay_pcb.py NETLIST.xml"""
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
pinnet = {(n2.get('ref'), n2.get('pin')): n.get('name') for n in net.iter('net') for n2 in n.iter('node')}

def load(fpid):
    nick, name = fpid.split(':')
    f = IO.FootprintLoad(PRJLIB + '.pretty' if nick == PRJLIB else '%s/%s.pretty' % (STD, nick), name)
    f.SetFPID(pcbnew.LIB_ID(nick, name))
    return f

# rows follow module pins 3..6 (IO4 PPM_IN, IO5 DATA_RX, IO6 DATA_TX, IO7 HB_OUT)
RA, RB, RC, RD = 101.9, 103.95, 106.0, 108.05
XD, XB, XM = 127.7, 123.1, 132.4
PLACE = {
    'D3': (XD, RA, 0), 'D4': (XD, RB, 0),            # K at the bay (left)
    'R14': (XM, RA, 180), 'R16': (XM, RB, 180),      # MCU-side pull-ups, VCC pad right
    # DATA transmit in the band below row B: U5 beside module pads 6/7, C6 next to it, R17 by the DATA via
    'U5': (133.4, 106.7, 180), 'C6': (129.25, 106.9, 180), 'R17': (125.2, 107.3, 0),
    # HB a step lower to make room: D6 (A at the bay, left) and its pull-up R15
    'D6': (XD, 109.3, 180), 'R15': (122.7, 109.3, 0),
    'R12': (131.4, 109.9, 0), 'R13': (131.4, 112.1, 0),   # 0.3 lower, so HB_OUT and U5's VCC via fit above
}

dead = list(b.GetTracks()) + list(b.Zones())
for f in b.GetFootprints():
    ref = f.GetReference()
    if ref and ref not in comps and not f.IsBoardOnly():
        dead.append(f); print('remove', ref)

for ref, c in comps.items():
    f = b.FindFootprintByReference(ref)
    if not f:
        f = load(c.findtext('footprint')); f.SetReference(ref); b.Add(f)
        f.SetPath(pcbnew.KIID_PATH('/' + c.find('tstamps').text))
        f.SetSheetname('/'); f.SetSheetfile('heimdall-module.kicad_sch')
        print('add', ref)
    if ref in PLACE:      # new or changed parts: value and fields from the schematic
        f.SetValue(c.findtext('value'))
        for fld in c.iter('field'):
            if fld.get('name') not in ('Footprint', 'Datasheet', 'Description'):
                f.SetField(fld.get('name'), fld.text or '')
                f.GetField(fld.get('name')).SetVisible(False)
    if ref in PLACE:
        x, y, r = PLACE[ref]
        f.SetPosition(V(x, y)); f.SetOrientationDegrees(r)
        f.Reference().SetLayer(pcbnew.F_Fab)   # too dense for silk refs
    for p in f.Pads():
        name = pinnet.get((ref, p.GetNumber()))
        if name is None:
            p.SetNetCode(0); continue
        ni = b.FindNet(name)
        if ni is None:
            ni = pcbnew.NETINFO_ITEM(b, name); b.Add(ni)
        p.SetNet(ni)

# JP1's reference would sit on D6 (one row lower now): left of the jumper instead
b.FindFootprintByReference('JP1').Reference().SetPosition(V(122.8, 112.0))

for it in dead:
    b.Remove(it)
pcbnew.SaveBoard(B, b)
for r in sorted(PLACE):
    f = b.FindFootprintByReference(r)
    print(r, [(p.GetNumber(), p.GetNetname(), round(pcbnew.ToMM(p.GetPosition().x), 2), round(pcbnew.ToMM(p.GetPosition().y), 2)) for p in f.Pads()])
