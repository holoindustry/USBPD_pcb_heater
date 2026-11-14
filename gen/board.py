"""Build the heater board: library parts, schematic, PCB, checks, fabrication files.

Order of work on the PCB (as in ../gen/boards/poc.py): place the circuit, draw the fixed
copper by hand (heater zone, links, power paths), let the grid router do the tail signals,
then add the ground pours, fill, and run DRC.
"""
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.append(os.path.join(os.path.dirname(ROOT), "gen"))

import pcbnew as P  # noqa: E402

import circuits  # noqa: E402
import geom as G  # noqa: E402
import heater as H  # noqa: E402
import pcbkit as K  # noqa: E402
import schematic as SC  # noqa: E402
import sheets  # noqa: E402
from eda.kicad_pcb import ORIGIN, Board, legalize  # noqa: E402
from eda.router import Router  # noqa: E402

X_PWR = circuits.X_LAND   # |x| of the power trace where a link meets the tail
X_SNS = 12.6              # |x| of the sense trace there (B.Cu)
X_GND = 13.4              # |x| of the plane's ground trace there (B.Cu)
X_EXIT_SNS = 31.2         # |x| where the sense trace leaves the heater zone
X_EXIT_GND = 32.4
X_EXIT_PWR = 32.9
Y_STRIP = (G.Y_LINK_TOP + G.Y_LINK_BOT) / 2      # centre line of the link strip
Y_VIAS = G.Y_TAIL - 1.8                          # centre of the power via groups
W_PWR = 2.4
W_SIG = 0.2
PLANE_INSET = 0.5         # underside plane and its mask window, from the heater zone edge


# ============================================================================ library
# 3D models. KiCad's footprints for the USB-C socket and the PD chip's package name model files
# that its library does not ship, and there is none for the trimmer. The STEP files in
# hw/lib/fable.3dshapes are EasyEDA's models of the LCSC parts (C283540, C118910), placed by their pins.
LIB3D = "${KIPRJMOD}/../lib/fable.3dshapes"
# footprint name -> (model file, offset x y z in mm with y up, rotation about z in degrees)
MODELS = {
    "USB_C_Receptacle_HRO_TYPE-C-31-M-17": (LIB3D + "/USB_C_Receptacle_HRO_TYPE-C-31-M-17.step", (0.0, -0.8, 0.0), 180.0),
    "WDFN-10-1EP_3x3mm_P0.5mm_EP1.8x2.5mm": ("${KICAD10_3DMODEL_DIR}/Package_DFN_QFN.3dshapes/"
                                             "DFN-10-1EP_3x3mm_P0.5mm_EP1.65x2.38mm.step", (0.0, 0.0, 0.0), 0.0),
    "Potentiometer_3362P": (LIB3D + "/Potentiometer_3362P.step", (2.54, 0.145, 0.0), 0.0),
}


def set_model(fp, path, offset=(0.0, 0.0, 0.0), rz=0.0):
    """Make `path` the only 3D model of a footprint."""
    fp.Models().clear()
    m = P.FP_3DMODEL()
    m.m_Filename = path
    m.m_Offset.x, m.m_Offset.y, m.m_Offset.z = offset
    m.m_Rotation.z = rz
    fp.Add3DModel(m)


def heater_fp(h):
    fp = K.fp_new("Heater_70x70",
                  f"Heater trace 70 x 70 mm on F.Cu: {h.n} lanes, {min(h.ws) * h.p.end_f:.2f}-{max(h.ws):.2f} mm, "
                  f"R20 {h.r20:.2f} ohm; pads 1/2 are the terminals (net tie)",
                  P.FP_SMD | P.FP_EXCLUDE_FROM_BOM | P.FP_EXCLUDE_FROM_POS_FILES)
    for a, b, w in h.segs:
        K.fp_seg(fp, a, b, w, P.F_Cu)
    for num, p in (("1", h.term[0]), ("2", h.term[1])):
        K.fp_pad(fp, num, p, (0.9, 0.9), K.lset(P.F_Cu))
    fp.AddNetTiePadGroup("1,2")
    K.fp_save(fp)


def slot_fp():
    fp = K.fp_new("LegSlot", "Plated slot for a leg tongue; land on both sides, tented on the top side",
                  P.FP_THROUGH_HOLE | P.FP_EXCLUDE_FROM_BOM | P.FP_EXCLUDE_FROM_POS_FILES)
    K.fp_pad(fp, "1", (0, 0), G.SLOT_PAD, K.lset(P.F_Cu, P.B_Cu, P.B_Mask), attrib=P.PAD_ATTRIB_PTH,
             shape=P.PAD_SHAPE_OVAL, drill=(G.SLOT_L, G.SLOT_W))
    K.fp_save(fp)


def leg_fp():
    """Origin at the middle of the shoulder line; tongue towards +y, body towards -y.
    One T-shaped bare copper area per face: across the top of the body and up the tongue."""
    fp = K.fp_new("Leg", "FR-4 leg: bare copper on both faces for soldering into a LegSlot",
                  P.FP_SMD | P.FP_EXCLUDE_FROM_BOM | P.FP_EXCLUDE_FROM_POS_FILES)
    bw, tw = G.LEG_W / 2 - 1.0, G.TONGUE_W / 2 - 0.35
    pts = [(-bw, -2.55), (bw, -2.55), (bw, -0.35), (tw, -0.35), (tw, G.TONGUE_H - 0.4), (-tw, G.TONGUE_H - 0.4),
           (-tw, -0.35), (-bw, -0.35)]
    for layer in (P.F_Cu, P.F_Mask, P.B_Cu, P.B_Mask):
        K.fp_poly(fp, pts, layer)
    K.fp_save(fp)


def bite_fp():
    fp = K.fp_new("MouseBite", "Three 0.5 mm holes across a break-off tab, on the edge of the heater zone",
                  P.FP_EXCLUDE_FROM_BOM | P.FP_EXCLUDE_FROM_POS_FILES)
    for dy in (-G.BITE_PITCH, 0.0, G.BITE_PITCH):
        K.fp_pad(fp, "", (0, dy), (G.BITE_D, G.BITE_D), P.PAD.UnplatedHoleMask(), attrib=P.PAD_ATTRIB_NPTH,
                 shape=P.PAD_SHAPE_CIRCLE, drill=(G.BITE_D, G.BITE_D))
    K.fp_save(fp)


def tooling_fp():
    """JLCPCB assembly tooling hole: 1.152 mm unplated, solder mask opened 0.148 mm around it."""
    fp = K.fp_new("ToolingHole", "JLCPCB PCBA tooling hole, 1.152 mm NPTH",
                  P.FP_EXCLUDE_FROM_BOM | P.FP_EXCLUDE_FROM_POS_FILES)
    pad = K.fp_pad(fp, "", (0, 0), (G.TOOLING_D, G.TOOLING_D), P.PAD.UnplatedHoleMask(), attrib=P.PAD_ATTRIB_NPTH,
                   shape=P.PAD_SHAPE_CIRCLE, drill=(G.TOOLING_D, G.TOOLING_D))
    pad.SetLocalSolderMaskMargin(P.FromMM(0.148))
    K.fp_save(fp)


def pot_fp():
    """3362P single-turn trimmer (Bourns 3362 datasheet, style P; the BOCHEN 3362P-1 is a copy).
    Seen from the adjustment side: pin 1 (anticlockwise end) at the origin, pin 3 (clockwise end)
    5.08 mm to its right, the wiper pin 2 between them and 2.54 mm back. Body 6.60 x 6.99 mm, its
    front edge 3.53 mm in front of pins 1 and 3; pins 0.46 mm."""
    fp = K.fp_new("Potentiometer_3362P", "Trimmer 3362P, top adjust, pins 1-3 5.08 mm apart, wiper 2.54 mm back",
                  P.FP_THROUGH_HOLE)
    for num, at, shape in (("1", (0.0, 0.0), P.PAD_SHAPE_RECT), ("2", (2.54, 2.54), P.PAD_SHAPE_CIRCLE),
                           ("3", (5.08, 0.0), P.PAD_SHAPE_CIRCLE)):
        K.fp_pad(fp, num, at, (1.5, 1.5), K.lset(P.F_Cu, P.B_Cu, P.F_Mask, P.B_Mask), attrib=P.PAD_ATTRIB_PTH,
                 shape=shape, drill=(0.8, 0.8))
    x0, x1, y0, y1 = 2.54 - 3.30, 2.54 + 3.30, -3.53, 6.99 - 3.53        # body, y up = towards the back
    for layer, grow, w in ((P.F_Fab, 0.0, 0.1), (P.F_SilkS, 0.12, 0.12), (P.F_CrtYd, 0.25, 0.05)):
        xa, xb, ya, yb = x0 - grow, x1 + grow, y0 - grow, y1 + grow
        K.fp_seg(fp, (xa, ya), (xb, ya), w, layer)
        K.fp_seg(fp, (xa, yb), (xb, yb), w, layer)
        for x in (xa, xb):                       # the silkscreen stops beside the pads of pins 1 and 3
            for a, b in ((ya, -1.2), (1.2, yb)) if layer == P.F_SilkS else ((ya, yb),):
                K.fp_seg(fp, (x, a), (x, b), w, layer)
    cx, cy = 2.54, 3.84 - 3.53                                           # rotor centre
    ring = [(cx + 2.4 * math.cos(math.radians(k * 15)), cy + 2.4 * math.sin(math.radians(k * 15))) for k in range(24)]
    for a, b in zip(ring, ring[1:] + ring[:1]):
        K.fp_seg(fp, a, b, 0.1, P.F_Fab)
    K.fp_seg(fp, (cx, cy - 1.6), (cx, cy + 1.6), 0.1, P.F_Fab)           # adjustment slot
    K.fp_seg(fp, (x0 - 0.6, -0.9), (x0 - 0.6, 0.9), 0.12, P.F_SilkS)     # pin 1 mark
    for item, layer, y in ((fp.Reference(), P.F_SilkS, y1 + 1.2), (fp.Value(), P.F_Fab, y0 - 1.2)):
        item.SetVisible(True)
        item.SetLayer(layer)
        item.SetPosition(P.VECTOR2I(P.FromMM(cx), P.FromMM(-y)))
        item.SetTextSize(P.VECTOR2I(P.FromMM(1.0), P.FromMM(1.0)))
        item.SetTextThickness(P.FromMM(0.15))
    set_model(fp, *MODELS["Potentiometer_3362P"])
    K.fp_save(fp)


def library(h):
    heater_fp(h)
    slot_fp()
    leg_fp()
    bite_fp()
    tooling_fp()
    pot_fp()


# ============================================================================ outline
def leg_origins():
    """(side, x of the shoulder-line centre, y of the shoulder line) for every leg, both strips."""
    n = G.N_LEGS_SIDE
    total = n * (G.LEG_H + G.TONGUE_H) + (n - 1) * 2.0
    out = []
    for side in (-1, 1):
        xc = side * (G.HALF + G.LEG_GAP + G.LEG_W / 2)
        for k in range(n):
            y0 = -total / 2 + k * G.LEG_PITCH
            out.append((side, xc, y0 + G.LEG_H))
    return out


def outline_ps():
    hf = G.HALF
    main = K.ps_sub(K.ps_rect(-hf, G.Y_BOT, hf, hf),
                    K.ps_rect(-G.LINK_X_HEAT, G.Y_LINK_TOP, G.LINK_X_HEAT, G.Y_HEAT),            # upper slot
                    K.ps_rect(-G.LINK_X_TAIL[0], G.Y_TAIL, G.LINK_X_TAIL[0], G.Y_HEAT),           # centre window
                    K.ps_rect(-hf - 1, G.Y_TAIL, -G.LINK_X_TAIL[1], G.Y_LINK_BOT),                 # lower notches
                    K.ps_rect(G.LINK_X_TAIL[1], G.Y_TAIL, hf + 1, G.Y_LINK_BOT))
    pieces, bites = [main], []
    for side, xc, ys in leg_origins():
        x_in = side * (hf + G.LEG_GAP)
        pieces.append(K.ps_rect(xc - G.LEG_W / 2, ys - G.LEG_H, xc + G.LEG_W / 2, ys))
        pieces.append(K.ps_rect(xc - G.TONGUE_W / 2, ys - 0.01, xc + G.TONGUE_W / 2, ys + G.TONGUE_H))
        for yt in (ys - G.LEG_H + 3.0, ys - G.LEG_H + 9.0):
            pieces.append(K.ps_rect(side * (hf - 0.05), yt - G.TAB_W / 2, x_in + side * 0.05, yt + G.TAB_W / 2))
            bites.append((side * (hf + 0.05), yt))      # one row, on the heater edge: the stub stays on the leg
    return K.ps_round_inside(K.ps_union(*pieces), G.R_FILLET), bites


# ============================================================================ heater zone
def sensor_geo(bd):
    """Geometry of each sensor island from the placed NTC footprints."""
    out = []
    for name, ys, side in G.SENSORS:
        gnd = K.padbox(bd, name, "2")
        sig = K.padbox(bd, name, "1")
        if abs((gnd[0] + gnd[2]) / 2) > abs((sig[0] + sig[2]) / 2):
            raise RuntimeError(f"{name}: ground pad must be the one next to the pickup bar")
        x_lo = min(-G.ISLAND[0] / 2, gnd[0] - 0.1)
        x_hi = max(G.ISLAND[0] / 2, gnd[2] + 0.1)
        island = (x_lo, ys - G.ISLAND[1] / 2, x_hi, ys + G.ISLAND[1] / 2)
        moat = (min(x_lo, sig[0]) - G.MOAT, ys - G.ISLAND[1] / 2 - G.MOAT,
                max(x_hi, sig[2]) + G.MOAT, ys + G.ISLAND[1] / 2 + G.MOAT)
        out.append(dict(name=name, y=ys, side=side, island=island, moat=moat,
                        sig=((sig[0] + sig[2]) / 2, (sig[1] + sig[3]) / 2),
                        net="NTC1" if name == "RT1" else "NTC2"))
    return out


def sense_route(s):
    """B.Cu path of a sensor signal: pad -> down -> corridor along the bottom edge -> link -> tail."""
    side = -1 if s["name"] == "RT1" else 1          # RT1 leaves through the left link, RT2 through the right
    xs, ys = s["sig"]
    return [(xs, ys), (xs, G.CORRIDOR_Y), (side * X_EXIT_SNS, G.CORRIDOR_Y), (side * X_EXIT_SNS, Y_STRIP + 0.5),
            (side * X_SNS, Y_STRIP + 0.5), (side * X_SNS, G.Y_TAIL - 1.2)]


def anchor_points():
    """Anchor vias along the perimeter of the underside plane."""
    a = G.HALF - G.ANCHOR_INSET
    n = int(2 * (a - 1.5) / G.ANCHOR_PITCH)
    ts = [-(n * G.ANCHOR_PITCH) / 2 + k * G.ANCHOR_PITCH for k in range(n + 1)]
    pts = [(t, a) for t in ts] + [(t, -a) for t in ts] + [(-a, t) for t in ts] + [(a, t) for t in ts]
    out = []
    for x, y in pts:
        if y == -a and abs(x) > G.LINK_X_HEAT - 1.0:
            continue                                # terminals and link exits at the bottom corners
        clash = False
        for cx, cy, orient in G.LEG_SLOTS:
            x0, y0, x1, y1 = G.slot_rect(cx, cy, orient, grow=0.6)
            clash |= x0 < x < x1 and y0 < y < y1
        if not clash:
            out.append((x, y))
    return out


def heater_zone(bd, h):
    hf = G.HALF
    sens = sensor_geo(bd)
    # pickup bar on the top layer (a filled strip) and its vias down to the sensor islands
    K.zone(bd, K.ps_rect(-G.BAR_W / 2, h.bar[0][1], G.BAR_W / 2, h.bar[1][1]), P.F_Cu, "GND", clearance=0.2,
           priority=2, thermal=False, name="pickup_bar", min_w=0.15)
    for s in sens:
        for dy in (-1.35, -0.45, 0.45, 1.35):
            K.via(bd, (0.0, s["y"] + dy), "GND", *G.VIA)
        K.zone(bd, K.ps_rect(*s["island"]), P.B_Cu, "GND", clearance=0.2, priority=3, thermal=False,
               name=f"island_{s['name']}")
        # thin spoke from the island to the plane: upwards, on the side away from the NTC
        x_sp = -s["side"] * 0.45
        y_top = s["island"][3]
        K.track(bd, (x_sp, y_top - 0.3), (x_sp, y_top + G.MOAT + 0.5), 0.2, P.B_Cu, "GND")
        K.path(bd, sense_route(s), W_SIG, P.B_Cu, s["net"])
    # underside plane with a moat around each sensor
    a = hf - PLANE_INSET
    plane = K.ps_sub(K.ps_rect(-a, -a, a, a), *[K.ps_rect(*s["moat"]) for s in sens])
    K.zone(bd, plane, P.B_Cu, "GND", clearance=0.25, priority=1, thermal=True, name="plane")
    # anchor vias around the plane, tied together on the top layer by a thin ground ring so that
    # each one holds copper on both faces (ring: left, top and right edges, plus the bottom edge
    # between the two heater terminals)
    pts = anchor_points()
    for p in pts:
        K.via(bd, p, "GND", *G.VIA)
    a_v = hf - G.ANCHOR_INSET
    y_lo = min(y for x, y in pts if abs(x) == a_v)
    x_b = max(x for x, y in pts if y == -a_v)
    K.path(bd, [(-a_v, y_lo), (-a_v, a_v), (a_v, a_v), (a_v, y_lo)], 0.4, P.F_Cu, "GND")
    K.track(bd, (-x_b, -a_v), (x_b, -a_v), 0.4, P.F_Cu, "GND")
    # bare-copper window: the plane, minus the sensors, the sense corridors and a dam around each leg land
    keep = [K.ps_rect(s["moat"][0] - 0.15, s["moat"][1] - 0.15, s["moat"][2] + 0.15, s["moat"][3] + 0.15) for s in sens]
    for s in sens:
        pts = sense_route(s)
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            keep.append(K.ps_rect(min(ax, bx) - 0.5, min(ay, by) - 0.5, max(ax, bx) + 0.5, max(ay, by) + 0.5))
    for cx, cy, orient in G.LEG_SLOTS:
        keep.append(K.ps_rect(*G.slot_rect(cx, cy, orient, grow=0.6)))
    K.fill_poly(bd, K.ps_sub(K.ps_rect(-a, -a, a, a), *keep), P.B_Mask)
    # links: heater power on top, plane ground and sense signal underneath
    for side, net, term in ((-1, "VBUS", h.term[0]), (1, "HTR_N", h.term[1])):
        K.path(bd, [(side * X_PWR, G.Y_TAIL - 2.6), (side * X_PWR, Y_STRIP), (side * X_EXIT_PWR, Y_STRIP),
                    (side * X_EXIT_PWR, G.Y_HEAT - 0.4)], W_PWR, P.F_Cu, net)
        K.path(bd, [(side * X_EXIT_PWR, G.Y_HEAT - 0.9), term], 0.9, P.F_Cu, net)
        for dx in (-0.5, 0.5):
            for dy in (-0.5, 0.5):
                K.via(bd, (side * X_PWR + dx, Y_VIAS + dy), net, *G.VIA)
        K.path(bd, [(side * X_EXIT_GND, -hf + 1.2), (side * X_EXIT_GND, Y_STRIP - 0.5),
                    (side * X_GND, Y_STRIP - 0.5), (side * X_GND, G.Y_TAIL - 1.2)], 0.25, P.B_Cu, "GND")
        K.via(bd, (side * X_GND, G.Y_TAIL - 1.2), "GND", *G.VIA)
    return sens


# ============================================================================ tail
REF_AT = {"analog": {"R16": (6.9, -46.7), "U3": (18.4, -58.1), "U4": (26.0, -58.1),
                     "R12": (11.7, -50.8), "R10": (11.7, -52.8), "R6": (11.7, -54.8), "R7": (11.7, -56.8),
                     "R5": (17.6, -43.7), "R13": (21.2, -43.7), "R8": (27.8, -43.7)}}


def tail_region(inset):
    """Tail rectangle, counter-clockwise in the board frame."""
    return [(-G.HALF + inset, G.Y_BOT + inset), (G.HALF - inset, G.Y_BOT + inset),
            (G.HALF - inset, G.Y_TAIL - inset), (-G.HALF + inset, G.Y_TAIL - inset)]


def to_kicad(pts):
    return [(ORIGIN[0] + x, ORIGIN[1] - y) for x, y in pts]


def place(c, out, symlib, variant):
    """Place the circuit, turn the parts whose pin direction matters, and legalise the passives."""
    path = os.path.join(out, f"{variant}.kicad_pcb")
    bd = Board(path, layers=2, thickness=G.T_PCB)
    K.set_rules(bd)
    report = bd.place_circuit(c, symlib, extra_fp_dirs=[K.LIBDIR])
    for fp in bd.b.GetFootprints():
        name = str(fp.GetFPID().GetLibItemName())
        if name in MODELS:
            set_model(fp, *MODELS[name])
    nf = os.path.join(out, f"{variant}.net")
    if os.path.exists(nf):
        bd.apply_netlist_unconnected(nf)
    y_of = lambda ref, pad: K.padxy(bd, ref, pad)[1]
    x_of = lambda ref, pad: K.padxy(bd, ref, pad)[0]
    # USB-C: contact pads towards the inside of the board, mouth at the edge
    K.orient(bd, "J1", lambda: y_of("J1", "A5") > G.Y_BOT + 3.2 + 1.0)
    # PD chip: the row with VIN..CC2 (pins 1-5) faces the connector; CC pins centred on it
    K.orient(bd, "U1", lambda: abs(y_of("U1", "4") - y_of("U1", "5")) < 0.01 and y_of("U1", "4") < y_of("U1", "8") - 1.0)
    K.move_fp(bd, "U1", -(x_of("U1", "4") + x_of("U1", "5")) / 2, 0.0)
    if (x_of("U1", "4") < x_of("U1", "5")) != (x_of("J1", "A5") < x_of("J1", "B5")):
        raise RuntimeError("CC lines would cross: swap the CC1/CC2 nets on J1 in circuits.py")
    if not x_of("U1", "7") < x_of("U1", "8") < x_of("U1", "9") < x_of("U1", "1"):
        raise RuntimeError("the parts around U1 are placed for VIN and ISET on its right-hand end")
    K.orient(bd, "C1", lambda: abs(y_of("C1", "1") - y_of("C1", "2")) < 0.01 and x_of("C1", "1") < x_of("C1", "2"))
    K.orient(bd, "R1", lambda: abs(y_of("R1", "1") - y_of("R1", "2")) < 0.01 and x_of("R1", "1") < x_of("R1", "2"))
    horiz = lambda ref: abs(y_of(ref, "1") - y_of(ref, "2")) < 0.01 and x_of(ref, "1") < x_of(ref, "2")
    K.orient(bd, "R15", lambda: abs(x_of("R15", "1") - x_of("R15", "2")) < 0.01 and y_of("R15", "1") < y_of("R15", "2"))
    K.move_fp(bd, "R15", x_of("U1", "8") - x_of("R15", "1"), 0.0)
    K.orient(bd, "R16", lambda: horiz("R16"))            # ISET pad on the left, like R1
    K.orient(bd, "D1", lambda: abs(y_of("D1", "1") - y_of("D1", "2")) < 0.01 and x_of("D1", "2") < x_of("D1", "1"))
    for ref in ("U3", "U4"):                             # pins 1-4 along the upper row, pin 1 on the left
        K.orient(bd, ref, lambda: y_of(ref, "1") > y_of(ref, "8") + 1.0 and x_of(ref, "1") < x_of(ref, "4") - 1.0)
    # switch: drain up (towards the link), on the power trace
    K.orient(bd, "Q1", lambda: y_of("Q1", "3") > y_of("Q1", "1") + 0.5 and abs(y_of("Q1", "1") - y_of("Q1", "2")) < 0.01)
    K.move_fp(bd, "Q1", X_PWR - x_of("Q1", "3"), 0.0)
    fixed = {"HTR1", "RT1", "RT2", "J1", "U1", "C1", "R1", "R15", "Q1", "D1", "U2", "U3"}
    fixed |= {p.ref for p in c.parts if p.ref.startswith("TP")}
    fixed |= {"R16", "U4"}
    rects, _, _ = power_plan(bd, variant)
    keep = [(*r, "B") for r in rects]
    keep += [(*G.slot_rect(cx, cy, o, grow=0.4), "FB") for cx, cy, o in G.LEG_SLOTS if cy < G.Y_TAIL]
    keep += [(x - 1.0, y - 1.0, x + 1.0, y + 1.0, "FB") for x, y in G.TOOLING]
    for side in (-1, 1):                                  # where the link traces land
        x0, x1 = sorted((side * (X_PWR - 1.3), side * (X_GND + 0.8)))
        keep.append((x0, G.Y_TAIL - 3.2, x1, G.Y_TAIL, "B"))
    moved, failed = legalize(bd, fixed, region=tail_region(0.7), rects=keep, step=0.2, rmax=8.0, margin=0.15)
    report.append(("legalise", f"moved {[(m[0], m[1], m[2]) for m in moved]}", f"failed {failed}", ""))
    for fp in bd.b.Footprints():
        if fp.GetReference() == "HTR1":
            continue
        ref = fp.Reference()
        ref.SetVisible(True)
        ref.SetTextSize(P.VECTOR2I(P.FromMM(0.8), P.FromMM(0.8)))
        ref.SetTextThickness(P.FromMM(0.12))
    for ref, at in REF_AT.get(variant, {}).items():       # designators that would sit on a neighbour
        txt = bd.b.FindFootprintByReference(ref).Reference()
        txt.SetPosition(K.xy(*at))
        txt.SetTextAngleDegrees(0)
    return bd, report


def power_plan(bd, variant):
    """Hand-drawn copper of the tail: the high-current paths and the short hops at the PD chip.

    Returns (keep-out rectangles, [(net, points, width, layer)], [(net, point)] vias).
    The heater feed runs on the top layer from the left link to the connector, so signals can
    pass under it; the return runs on the underside from the right link. Both meet the USB-C
    pads from above, which keeps the return current out of the ground pour that the sensing
    parts use."""
    B, F = P.B_Cu, P.F_Cu
    j = lambda n: K.padxy(bd, "J1", n)
    vb = sorted([j("A9"), j("B9")])
    gn = sorted([j("A12"), j("B12")])
    y_bus = K.padbox(bd, "J1", "A9")[3] + 0.75           # centre of the 0.8 mm buses above the pad row
    x_dn = -6.6                                          # where the feed drops to the underside
    paths = [("VBUS", [(-X_PWR, G.Y_TAIL - 2.6), (-X_PWR, y_bus + 4.0), (x_dn - 0.8, y_bus), (x_dn + 0.8, y_bus)], 1.2, F),
             ("VBUS", [(-X_PWR - 0.5, Y_VIAS), (-X_PWR + 0.5, Y_VIAS)], 1.6, B),      # pad under the via group:
             ("VBUS", [(x_dn - 0.8, y_bus), (vb[0][0], y_bus)], 0.8, B),             # feeds C2, the LDO, the LED
             ("VBUS", [(vb[0][0], y_bus), vb[0]], 0.7, B)]
    # PD chip supply: VIN (pin 1) and C1 sit over the right-hand VBUS pad; that pad is tied to the
    # left-hand bus by a jumper on the top layer
    p1, c1, c1g = K.padxy(bd, "U1", "1"), K.padxy(bd, "C1", "1"), K.padxy(bd, "C1", "2")
    y_hop = p1[1] - 1.3
    paths += [("VBUS", [p1, (p1[0], y_hop), (vb[1][0], y_bus - 0.35), vb[1]], 0.25, B),
              ("VBUS", [c1, (p1[0] + 0.6, c1[1]), p1], 0.25, B),
              ("GND", [c1g, (c1g[0], y_bus)], 0.5, B),
              ("VBUS", [(p1[0], y_hop), (x_dn + 1.6, y_hop), (x_dn + 0.8, y_bus)], 0.5, F)]
    vias = [("VBUS", (p1[0], y_hop))] + [("VBUS", (x_dn + dx, y_bus)) for dx in (-0.8, 0.0, 0.8)]
    # configuration pins straight to their resistors
    p9, r1 = K.padxy(bd, "U1", "9"), K.padxy(bd, "R1", "1")
    paths.append(("ISET", [p9, (p9[0], p9[1] + 0.8), (r1[0] - 0.3, r1[1]), r1], 0.2, B))
    paths.append(("VSET", [K.padxy(bd, "U1", "8"), K.padxy(bd, "R15", "1")], 0.2, B))
    paths.append(("ISET", [r1, K.padxy(bd, "R16", "1")], 0.2, B))
    # heater return: via group -> drain, source -> connector ground
    paths.append(("HTR_N", [(X_PWR, Y_VIAS), K.padxy(bd, "Q1", "3")], 1.2, B))
    s = K.padxy(bd, "Q1", "2")
    paths.append(("GND", [s, (s[0], y_bus)], 1.2, B))
    x_ret = s[0]
    paths.append(("GND", [(x_ret, y_bus), (gn[1][0], y_bus)], 0.8, B))
    paths.append(("GND", [(gn[1][0], y_bus), gn[1]], 0.8, B))
    rects = []
    for _, pts, w, layer in paths:
        if layer != B:
            continue
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            g = w / 2 + 0.35
            rects.append((min(ax, bx) - g, min(ay, by) - g, max(ax, bx) + g, max(ay, by) + g))
    return rects, paths, vias


def power_copper(bd, variant):
    _, paths, vias = power_plan(bd, variant)
    for net, pts, w, layer in paths:
        K.path(bd, pts, w, layer, net)
    for net, p in vias:
        K.via(bd, p, net, *G.VIA)


def npth_rects(bd, grow):
    """Rectangles (board frame) around every unplated hole in the tail."""
    out = []
    for fp in bd.b.Footprints():
        for pd in fp.Pads():
            if pd.GetAttribute() != P.PAD_ATTRIB_NPTH:
                continue
            c = pd.GetPosition()
            x, y = P.ToMM(c.x) - ORIGIN[0], ORIGIN[1] - P.ToMM(c.y)
            if y > G.Y_TAIL:
                continue
            bb = pd.GetBoundingBox()
            hx, hy = P.ToMM(bb.GetWidth()) / 2 + grow, P.ToMM(bb.GetHeight()) / 2 + grow
            out.append((x - hx, y - hy, x + hx, y + hy))
    return out


def via_points(bd):
    """Centres (KiCad mm) of every via on the board."""
    return [(P.ToMM(t.GetPosition().x), P.ToMM(t.GetPosition().y)) for t in bd.b.GetTracks() if t.GetClass() == "PCB_VIA"]


def gnd_vias(r, bd, skip=()):
    """A via to the top-side ground pour next to every ground SMD pad of the tail.

    The sibling Router.fanout() does this too, but it indexes its grid with every pad of the
    net and so cannot cope with ground pads outside the routing region (the heater zone)."""
    code = bd.b.FindNet("GND").GetNetCode()
    done, missing = 0, []
    taken = via_points(bd)                                # two drills must not touch, same net or not
    for fp in bd.b.Footprints():
        for pad in fp.Pads():
            if pad.GetNetCode() != code or pad.GetAttribute() != P.PAD_ATTRIB_SMD:
                continue
            if (fp.GetReference(), pad.GetNumber()) in skip:
                continue
            c = pad.GetPosition()
            px, py = P.ToMM(c.x), P.ToMM(c.y)
            iy, ix = r._idx(px, py)
            if not (0 <= iy < r.H and 0 <= ix < r.W) or r.edge_dist[iy, ix] <= 0:
                continue                                  # not in the tail
            free, via_ok = r._free(code, 0.3)
            ff = free[P.B_Cu].ravel()
            spot = None
            for rad in (1.0, 1.3, 1.7, 2.2, 2.8):
                for k in range(16):
                    q = (px + rad * math.cos(k * math.pi / 8), py + rad * math.sin(k * math.pi / 8))
                    jy, jx = r._idx(*q)
                    if (0 <= jy < r.H and 0 <= jx < r.W and via_ok[jy, jx] and r._los(ff, (px, py), q)
                            and all(math.hypot(q[0] - vx, q[1] - vy) >= 0.9 for vx, vy in taken)):
                        spot = q
                        break
                if spot:
                    break
            if spot is None:
                missing.append(f"{fp.GetReference()}.{pad.GetNumber()}")
                continue
            t = P.PCB_TRACK(bd.b)
            t.SetStart(P.VECTOR2I(P.FromMM(px), P.FromMM(py)))
            t.SetEnd(P.VECTOR2I(P.FromMM(spot[0]), P.FromMM(spot[1])))
            t.SetWidth(P.FromMM(0.3))
            t.SetLayer(P.B_Cu)
            t.SetNet(bd.b.FindNet("GND"))
            bd.b.Add(t)
            r._paint(P.B_Cu, r._seg_mask((px, py), spot, 0.15), code)
            if r.add_via(spot, "GND"):
                done += 1
                taken.append(spot)
            else:
                missing.append(f"{fp.GetReference()}.{pad.GetNumber()}")
    return done, missing


WIDTH = {"VBUS": 0.5, "HTR_N": 0.5, "+3V3": 0.3, "GATE": 0.25, "GATE_OC": 0.25}
FIRST = ["CC1", "CC2", "ISET", "VSET", "I2C_IDLE", "NTC1", "NTC2", "REF1", "REF2", "VBUS", "HTR_N", "+3V3"]


def route(bd, c, variant):
    r = Router(bd.b, to_kicad(tail_region(0.0)), grid=0.05, clearance=0.2, edge_clearance=0.4, via=G.VIA)
    for x0, y0, x1, y1 in npth_rects(bd, 0.12):           # the router only knows round holes: block the
        res = r._poly_mask(to_kicad([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))     # real shape, even over
        if res is not None:                                                         # the part's own pads
            (i0_, i1_, j0_, j1_), m = res
            for layer in r.layers:
                r.owner[layer][i0_:i1_, j0_:j1_][m] = -1
    results = {}
    done, missing = gnd_vias(r, bd)
    results["GND vias"] = f"{done} placed" + (f", no room at {missing}" if missing else "")
    pos = {}
    for fp in bd.b.Footprints():
        for pd in fp.Pads():
            if pd.GetNetname():
                pos.setdefault(pd.GetNetname(), []).append((pd.GetPosition().x, pd.GetPosition().y))

    def hpwl(n):
        p = pos.get(n, [(0, 0)])
        return (max(x for x, _ in p) - min(x for x, _ in p)) + (max(y for _, y in p) - min(y for _, y in p))

    todo = [n for n in c.nets() if n != "GND"]
    todo.sort(key=lambda n: (0 if n in FIRST else 1, FIRST.index(n) if n in FIRST else 0, hpwl(n)))
    failed = []
    for n in todo:
        res = r.route_net(n, WIDTH.get(n, 0.2))
        if res != "ok":
            results[n] = res
            failed.append(n)
    padpts = lambda n: [(P.ToMM(x), P.ToMM(y)) for x, y in pos.get(n, [])]
    for attempt in range(4):                              # rip up the neighbours of a stuck net and retry
        if not failed:
            break
        n = failed.pop(0)
        victims = sorted(r.items_near(padpts(n), 2.5) - {n, "GND"})
        r.rip(victims)
        res = r.route_net(n, WIDTH.get(n, 0.2))
        results[f"{n} retry {attempt} (ripped {victims})"] = res
        if res != "ok":
            failed.append(n)
        for v in victims:
            if r.route_net(v, WIDTH.get(v, 0.2)) != "ok":
                failed.append(v)
    return r, results, failed


def pours(bd, r, variant):
    holes = [K.ps_rect(*rc) for rc in npth_rects(bd, 0.45)]
    top = K.ps_sub(K.ps_poly(tail_region(0.35)), *holes)
    bot = K.ps_sub(K.ps_poly(tail_region(0.35)), *holes)
    K.zone(bd, top, P.F_Cu, "GND", clearance=0.25, priority=0, thermal=True, name="tail_gnd_top")
    K.zone(bd, bot, P.B_Cu, "GND", clearance=0.25, priority=0, thermal=True, name="tail_gnd_bottom")
    taken = via_points(bd)
    pts = [(ORIGIN[0] + x, ORIGIN[1] - y) for x in [-32.0 + 4.0 * i for i in range(17)]
           for y in [G.Y_TAIL - 1.5 - 3.5 * j for j in range(6)] if y > G.Y_BOT + 1.0]
    pts = [q for q in pts if all(math.hypot(q[0] - vx, q[1] - vy) >= 0.9 for vx, vy in taken)]
    return r.stitch("GND", pts)


def silk(bd, variant, h):
    T = K.text
    T(bd, f"USB-C PCB HEATER 100C  rev {circuits.REV}  {variant}", (0.0, G.Y_TAIL - 6.4), P.F_SilkS, 1.3)
    T(bd, f"HOT SURFACE   up to 20 V   R20 {h.r20:.1f} ohm", (0.0, G.Y_TAIL - 9.0), P.F_SilkS, 1.0)
    T(bd, "parts and legs on the other side", (0.0, G.Y_TAIL - 11.0), P.F_SilkS, 0.8)
    T(bd, "JLCJLCJLCJLC", (-25.0, G.Y_TAIL - 1.3), P.B_SilkS, 0.8)
    short = {"+3V3": "3V3", "HTR_N": "HTR-"}
    for fp in bd.b.Footprints():
        if fp.GetReference().startswith("TP"):
            x, y = K.padxy(bd, fp.GetReference(), "1")
            fp.Reference().SetVisible(False)
            T(bd, short.get(fp.GetValue(), fp.GetValue()), (x, y + 1.6), P.B_SilkS, 0.8)
    notes = [f"FAB NOTES  heater {variant} rev {circuits.REV}",
             "JLCPCB 2 layer FR-4, 1.6 mm, 1 oz finished copper (sets the heater resistance), HASL lead-free.",
             "The heater is the top copper under solder mask. The underside of the heater zone is bare copper on purpose.",
             "Slots: internal cut-outs between heater zone and tail (1.2 mm), 6 plated slots 7.4 x 1.9 mm.",
             "The eight small pieces beside the heater zone are break-off legs of the same board (mouse-bite tabs).",
             "The two 1.152 mm unplated holes in the bottom corners of the tail are assembly tooling holes.",
             "Vias 0.6 / 0.3 mm, tented. Do not add copper thieving."]
    T(bd, "\n".join(notes), (55.0, 30.0), P.Cmts_User, 1.2, mirror=False, justify="left")


def plot(bd, path, title=""):
    """Quick layer view for checking: outline, pads, tracks, vias (F red, B blue)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    fx = lambda v: P.ToMM(v.x) - ORIGIN[0]
    fy = lambda v: ORIGIN[1] - P.ToMM(v.y)
    fig, axs = plt.subplots(1, 2, figsize=(22, 9), dpi=120, gridspec_kw=dict(width_ratios=[1, 1.9]))
    for ax, (y0, y1, x0, x1) in zip(axs, ((G.Y_BOT - 1, G.HALF + 1, -50, 50), (G.Y_BOT - 0.5, G.Y_HEAT + 1.5, -36, 36))):
        for d in bd.b.GetDrawings():
            if d.GetLayer() == P.Edge_Cuts and d.GetClass() == "PCB_SHAPE":
                ps = d.GetPolyShape()
                for k in range(ps.OutlineCount()):
                    ol = ps.COutline(k)
                    pts = [(P.ToMM(ol.CPoint(i).x) - ORIGIN[0], ORIGIN[1] - P.ToMM(ol.CPoint(i).y)) for i in range(ol.PointCount())]
                    pts.append(pts[0])
                    ax.plot([p[0] for p in pts], [p[1] for p in pts], "k-", lw=0.6)
        for fp in bd.b.Footprints():
            for pd in fp.Pads():
                bb = pd.GetBoundingBox()
                px0, px1 = P.ToMM(bb.GetX()) - ORIGIN[0], P.ToMM(bb.GetRight()) - ORIGIN[0]
                py0, py1 = ORIGIN[1] - P.ToMM(bb.GetBottom()), ORIGIN[1] - P.ToMM(bb.GetY())
                col = "#4060c0" if pd.IsOnLayer(P.B_Cu) and not pd.IsOnLayer(P.F_Cu) else ("#c04040" if not pd.IsOnLayer(P.B_Cu) else "#808080")
                ax.add_patch(Rectangle((px0, py0), px1 - px0, py1 - py0, fc=col, ec="none", alpha=0.75))
            if fp.GetReference() and fp.GetReference() != "HTR1":
                p = fp.GetPosition()
                ax.text(fx(p), fy(p), fp.GetReference(), fontsize=6, ha="center", va="center", color="k")
        k = 9 * 72 / (y1 - y0) * 0.55                    # points per mm, roughly
        for t in bd.b.GetTracks():
            if t.GetClass() == "PCB_VIA":
                ax.plot([fx(t.GetPosition())], [fy(t.GetPosition())], "o", ms=max(1.2, 0.6 * k), color="k")
            else:
                col = "#d03030" if t.GetLayer() == P.F_Cu else "#3050d0"
                ax.plot([fx(t.GetStart()), fx(t.GetEnd())], [fy(t.GetStart()), fy(t.GetEnd())], color=col,
                        lw=max(0.3, P.ToMM(t.GetWidth()) * k), alpha=0.75, solid_capstyle="round")
        ax.set_aspect("equal")
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
    axs[0].set_title(title + "  (top view; F.Cu red, B.Cu blue)", fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ============================================================================ main entry
def build(variant, verbose=True, cam=True):
    t0 = time.time()
    say = print if verbose else (lambda *a, **k: None)
    out = os.path.join(ROOT, "hw", variant)
    os.makedirs(out, exist_ok=True)
    h = H.design()
    library(h)
    K.write_lib_tables(out)
    c = circuits.make(variant)
    symlib = SC.Lib()
    sch = os.path.join(out, f"{variant}.kicad_sch")
    sheet = sheets.draw(c, variant, symlib)              # raises if the drawing is not the circuit
    named = sheet.write(sch)
    v = SC.verify(c, sch, symlib, named)
    res = dict(variant=variant, r20=h.r20, lanes=h.n, min_gap=h.min_gap, nets=v["n_nets"],
               net_mismatch=v["mismatches"], extra_nets=v["extra_nets"])

    bd, report = place(c, out, symlib, variant)
    for rp in report:
        say("   place:", rp)
    ps, bites = outline_ps()
    K.edge_cuts(bd, ps)
    bb = K.ps_bbox(ps)
    res["bbox"] = (bb[2] - bb[0], bb[3] - bb[1])
    for _, xc, ys in leg_origins():
        K.add_board_fp(bd, "Leg", (xc, ys))
    for p in bites:
        K.add_board_fp(bd, "MouseBite", p)
    for cx, cy, orient in G.LEG_SLOTS:
        K.add_board_fp(bd, "LegSlot", (cx, cy), rot=0 if orient == "h" else 90, net_by_pad={"1": "GND"})
    for pt in G.TOOLING:
        K.add_board_fp(bd, "ToolingHole", pt)
    heater_zone(bd, h)
    power_copper(bd, variant)
    t1 = time.time()
    r, results, failed = route(bd, c, variant)
    for k, val in results.items():
        say(f"   route {k}: {val}")
    res["unrouted"] = failed
    res["stitch"] = pours(bd, r, variant)
    silk(bd, variant, h)
    K.rename_nets(bd, v["names"])                        # the board takes the net names of the schematic
    bd.fill_and_save()
    counts, unc, parity, rep = K.run_drc(bd.path)
    dang = [(it["pos"]["x"], it["pos"]["y"]) for vio in rep.get("violations", []) if vio["type"] == "via_dangling"
            for it in vio["items"]]
    if dang:                                             # tail stitching vias that reached copper on one side only
        for t in list(bd.b.GetTracks()):
            if (t.GetClass() == "PCB_VIA" and t.GetNetname() == "GND" and ORIGIN[1] - P.ToMM(t.GetPosition().y) < G.Y_TAIL
                    and any(abs(P.ToMM(t.GetPosition().x) - x) < 0.01 and abs(P.ToMM(t.GetPosition().y) - y) < 0.01
                            for x, y in dang)):
                bd.b.Remove(t)
        bd.fill_and_save()
        counts, unc, parity, rep = K.run_drc(bd.path)
    v = SC.verify(c, sch, symlib, named)                 # ERC, now that the project file exists
    res["erc"] = {f"{k[0]}:{k[1]}": len(x) for k, x in v["violations"].items()}
    res.update(drc={f"{k[0]}:{k[1]}": n for k, n in counts.items()}, unconnected=unc, parity=parity)
    a_v = G.HALF - G.ANCHOR_INSET
    res["anchor_vias"] = sum(1 for t in bd.b.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == "GND"
                             and abs(max(abs(P.ToMM(t.GetPosition().x) - ORIGIN[0]),
                                         abs(ORIGIN[1] - P.ToMM(t.GetPosition().y))) - a_v) < 0.01)
    res["top_side_parts"] = [fp.GetReference() for fp in bd.b.Footprints()
                             if not fp.IsFlipped() and fp.GetReference() not in ("HTR1", "")]
    plot(bd, os.path.join(out, "layout.png"), f"{variant}")
    res["bom"] = K.write_bom(c, os.path.join(out, f"{variant}_bom.csv"))
    res["zip"], res["cam_rc"] = K.cam(bd.path, sch, out, variant) if cam else ("", (0, 0))
    if cam:
        res["jlc"] = K.jlc_files(c, out, variant, skip=circuits.HAND_SOLDERED.get(variant, ()))
    res["seconds"] = time.time() - t0
    say(f"[{variant}] {v['n_nets']} nets, netlist mismatches {res['net_mismatch']}, ERC {res['erc']}")
    say(f"[{variant}] DRC {res['drc']}  unconnected {unc}  parity issues {parity}  unrouted {failed}  "
        f"bbox {res['bbox'][0]:.1f} x {res['bbox'][1]:.1f} mm  top-side parts {res['top_side_parts']}  "
        f"anchor vias {res['anchor_vias']}  "
        f"(routing {time.time() - t1:.0f} s, total {res['seconds']:.0f} s)")
    return res
