"""pcbnew helpers for the heater boards: polygons, zones, tracks, project library, DRC, CAM.

Board frame as in gen/geom.py (mm, origin at the heater-zone centre, +y up). The sibling
toolkit's eda.kicad_pcb.xy() maps it to KiCad coordinates.
The zone/track/via/DRC/CAM helpers follow the patterns of ../gen/boards/poc.py and
../gen/boards/common.py, re-done here for a 2-layer board with its own library paths.
"""
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SIB = os.path.dirname(ROOT)                       # the pcb_heater project
sys.path.insert(0, HERE)
sys.path.append(os.path.join(SIB, "gen"))

import pcbnew as P  # noqa: E402
from eda.kicad_pcb import ORIGIN, mm, xy  # noqa: E402

LIBDIR = os.path.join(ROOT, "hw", "lib")
FPLIB = os.path.join(LIBDIR, "fable.pretty")
MAX_ERR = P.FromMM(0.005)


# ---------------------------------------------------------------------------- polygons
def ps_poly(pts):
    ps = P.SHAPE_POLY_SET()
    ps.NewOutline()
    for p in pts:
        v = xy(*p)
        ps.Append(v.x, v.y)
    return ps


def ps_rect(x0, y0, x1, y1):
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    return ps_poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def ps_circle(c, r, n=48):
    return ps_poly([(c[0] + r * math.cos(2 * math.pi * k / n), c[1] + r * math.sin(2 * math.pi * k / n))
                    for k in range(n)])


def ps_union(*sets):
    out = P.SHAPE_POLY_SET(sets[0])
    for s in sets[1:]:
        out.BooleanAdd(s)
    return out


def ps_sub(base, *cuts):
    out = P.SHAPE_POLY_SET(base)
    for s in cuts:
        out.BooleanSubtract(s)
    return out


def ps_round_inside(ps, r):
    """Round the inside (concave) corners of a board polygon with radius r (closing)."""
    out = P.SHAPE_POLY_SET(ps)
    out.Inflate(P.FromMM(r), P.CORNER_STRATEGY_ROUND_ALL_CORNERS, MAX_ERR)
    out.Inflate(-P.FromMM(r), P.CORNER_STRATEGY_ROUND_ALL_CORNERS, MAX_ERR)
    return out


def ps_bbox(ps):
    """(x0, y0, x1, y1) in board frame."""
    bb = ps.BBox()
    return (P.ToMM(bb.GetX()) - ORIGIN[0], ORIGIN[1] - P.ToMM(bb.GetBottom()),
            P.ToMM(bb.GetRight()) - ORIGIN[0], ORIGIN[1] - P.ToMM(bb.GetY()))


def ps_kicad_pts(ps):
    """Outer outlines as lists of KiCad-mm points (for the router region)."""
    out = []
    for k in range(ps.OutlineCount()):
        ol = ps.COutline(k)
        out.append([(P.ToMM(ol.CPoint(i).x), P.ToMM(ol.CPoint(i).y)) for i in range(ol.PointCount())])
    return out


# ---------------------------------------------------------------------------- board items
def edge_cuts(bd, ps):
    """Draw every outline and hole of ps on Edge.Cuts as a closed polygon."""
    n = 0
    for k in range(ps.OutlineCount()):
        chains = [ps.COutline(k)] + [ps.CHole(k, j) for j in range(ps.HoleCount(k))]
        for ch in chains:
            one = P.SHAPE_POLY_SET()
            one.NewOutline()
            for i in range(ch.PointCount()):
                one.Append(ch.CPoint(i).x, ch.CPoint(i).y)
            s = P.PCB_SHAPE(bd.b)
            s.SetShape(P.SHAPE_T_POLY)
            s.SetLayer(P.Edge_Cuts)
            s.SetPolyShape(one)
            s.SetFilled(False)
            s.SetWidth(mm(0.05))
            bd.b.Add(s)
            n += 1
    return n


def fill_poly(bd, ps, layer):
    """Filled graphic polygon (e.g. a solder-mask opening). Holes are fractured in."""
    q = P.SHAPE_POLY_SET(ps)
    q.Fracture()
    for k in range(q.OutlineCount()):
        one = P.SHAPE_POLY_SET()
        one.NewOutline()
        ch = q.COutline(k)
        for i in range(ch.PointCount()):
            one.Append(ch.CPoint(i).x, ch.CPoint(i).y)
        s = P.PCB_SHAPE(bd.b)
        s.SetShape(P.SHAPE_T_POLY)
        s.SetLayer(layer)
        s.SetPolyShape(one)
        s.SetFilled(True)
        s.SetWidth(0)
        bd.b.Add(s)


def zone(bd, ps, layer, net=None, clearance=0.25, priority=0, thermal=True, name="", min_w=0.2):
    z = P.ZONE(bd.b)
    z.SetLayer(layer)
    if net:
        z.SetNet(bd.net(net))
    q = P.SHAPE_POLY_SET(ps)
    q.thisown = False                       # ZONE::SetOutline takes ownership
    z.SetOutline(q)
    z.SetLocalClearance(mm(clearance))
    z.SetMinThickness(mm(min_w))
    z.SetAssignedPriority(priority)
    z.SetPadConnection(P.ZONE_CONNECTION_THERMAL if thermal else P.ZONE_CONNECTION_FULL)
    if not net:
        z.SetPadConnection(P.ZONE_CONNECTION_NONE)
    z.SetIslandRemovalMode(P.ISLAND_REMOVAL_MODE_ALWAYS)
    if name:
        z.SetZoneName(name)
    bd.b.Add(z)
    return z


def track(bd, a, b, w, layer, net):
    if math.dist(a, b) < 1e-6:
        return None
    t = P.PCB_TRACK(bd.b)
    t.SetStart(xy(*a))
    t.SetEnd(xy(*b))
    t.SetWidth(mm(w))
    t.SetLayer(layer)
    t.SetNet(bd.net(net))
    bd.b.Add(t)
    return t


def path(bd, pts, w, layer, net):
    for a, b in zip(pts, pts[1:]):
        track(bd, a, b, w, layer, net)


def via(bd, p, net, d=0.6, drill=0.3):
    v = P.PCB_VIA(bd.b)
    v.SetPosition(xy(*p))
    v.SetWidth(mm(d))
    v.SetDrill(mm(drill))
    v.SetNet(bd.net(net))
    bd.b.Add(v)
    return v


def text(bd, txt, at, layer, size=1.0, mirror=None, angle=0.0, thick=0.15, justify=None):
    t = P.PCB_TEXT(bd.b)
    t.SetText(txt)
    t.SetLayer(layer)
    t.SetTextSize(P.VECTOR2I(mm(size), mm(size)))
    t.SetTextThickness(mm(size * thick))
    t.SetPosition(xy(*at))
    if angle:
        t.SetTextAngleDegrees(angle)
    t.SetMirrored(layer in (P.B_SilkS, P.B_Fab) if mirror is None else mirror)
    if justify == "left":
        t.SetHorizJustify(P.GR_TEXT_H_ALIGN_LEFT)
    bd.b.Add(t)
    return t


def padbox(bd, ref, num):
    """Bounding box (board frame) of all pads `num` of footprint `ref`."""
    fp = bd.b.FindFootprintByReference(ref)
    xs, ys = [], []
    for p in fp.Pads():
        if p.GetNumber() != num:
            continue
        bb = p.GetBoundingBox()
        xs += [P.ToMM(bb.GetX()) - ORIGIN[0], P.ToMM(bb.GetRight()) - ORIGIN[0]]
        ys += [ORIGIN[1] - P.ToMM(bb.GetY()), ORIGIN[1] - P.ToMM(bb.GetBottom())]
    if not xs:
        raise KeyError(f"{ref} has no pad {num}")
    return min(xs), min(ys), max(xs), max(ys)


def padxy(bd, ref, num):
    x0, y0, x1, y1 = padbox(bd, ref, num)
    return (x0 + x1) / 2, (y0 + y1) / 2


def pads_of(bd, ref, num):
    """Centres (board frame) of every pad `num` of footprint `ref`."""
    fp = bd.b.FindFootprintByReference(ref)
    out = []
    for p in fp.Pads():
        if p.GetNumber() == num:
            c = p.GetPosition()
            out.append((P.ToMM(c.x) - ORIGIN[0], ORIGIN[1] - P.ToMM(c.y)))
    return out


def orient(bd, ref, ok):
    """Turn footprint `ref` in 90 degree steps until ok() is true; returns the angle."""
    fp = bd.b.FindFootprintByReference(ref)
    for rot in (0, 90, 180, 270):
        fp.SetOrientationDegrees(rot)
        if ok():
            return rot
    raise RuntimeError(f"no orientation of {ref} satisfies the layout rule")


def move_fp(bd, ref, dx, dy):
    fp = bd.b.FindFootprintByReference(ref)
    p = fp.GetPosition()
    fp.SetPosition(P.VECTOR2I(p.x + mm(dx), p.y - mm(dy)))


def set_rules(bd, clearance=0.2, track=0.2):
    ds = bd.b.GetDesignSettings()
    for attr, val in (("m_TrackMinWidth", 0.15), ("m_MinClearance", 0.15), ("m_CopperEdgeClearance", 0.3),
                      ("m_HoleClearance", 0.2), ("m_MinThroughDrill", 0.3), ("m_ViasMinSize", 0.5),
                      ("m_HoleToHoleMin", 0.25)):
        setattr(ds, attr, mm(val))
    ds.m_TentViasFront = True
    ds.m_TentViasBack = True
    ds.m_MinResolvedSpokes = 1              # one thermal spoke is enough for a hand-soldered ground pad
    nc = ds.m_NetSettings.GetDefaultNetclass()
    nc.SetClearance(mm(clearance))
    nc.SetTrackWidth(mm(track))


# ---------------------------------------------------------------------------- footprints
def lset(*layers):
    ls = P.LSET()
    for layer in layers:
        ls.AddLayer(layer)
    return ls


def fp_new(name, descr, attrs):
    fp = P.FOOTPRINT(None)
    fp.SetFPIDAsString(f"fable:{name}")
    fp.SetLibDescription(descr)
    fp.SetAttributes(attrs)
    fp.Reference().SetText("REF**")
    fp.Reference().SetVisible(False)
    fp.Value().SetText(name)
    fp.Value().SetVisible(False)
    return fp


def fp_seg(fp, a, b, w, layer):
    """Copper/graphic segment in footprint coordinates given in board frame (y up)."""
    if math.dist(a, b) < 1e-6:
        return
    g = P.PCB_SHAPE(fp)
    g.SetShape(P.SHAPE_T_SEGMENT)
    g.SetLayer(layer)
    g.SetWidth(mm(w))
    g.SetStart(P.VECTOR2I(mm(a[0]), mm(-a[1])))
    g.SetEnd(P.VECTOR2I(mm(b[0]), mm(-b[1])))
    fp.Add(g)


def fp_poly(fp, pts, layer):
    """Filled polygon in a footprint; pts in board-frame orientation (y up) relative to the origin."""
    ps = P.SHAPE_POLY_SET()
    ps.NewOutline()
    for x, y in pts:
        ps.Append(mm(x), mm(-y))
    g = P.PCB_SHAPE(fp)
    g.SetShape(P.SHAPE_T_POLY)
    g.SetLayer(layer)
    g.SetPolyShape(ps)
    g.SetFilled(True)
    g.SetWidth(0)
    fp.Add(g)


def fp_pad(fp, num, at, size, layers, attrib=P.PAD_ATTRIB_SMD, shape=P.PAD_SHAPE_RECT, drill=None):
    p = P.PAD(fp)
    p.SetAttribute(attrib)
    p.SetShape(shape)
    p.SetSize(P.VECTOR2I(mm(size[0]), mm(size[1])))
    if drill:
        if drill[0] != drill[1]:
            p.SetDrillShape(P.PAD_DRILL_SHAPE_OBLONG)
        p.SetDrillSize(P.VECTOR2I(mm(drill[0]), mm(drill[1])))
    p.SetLayerSet(layers)
    p.SetNumber(num)
    p.SetPosition(P.VECTOR2I(mm(at[0]), mm(-at[1])))
    fp.Add(p)
    return p


def fp_save(fp):
    os.makedirs(FPLIB, exist_ok=True)           # a .pretty library is just a directory
    io = P.PCB_IO_MGR.FindPlugin(P.PCB_IO_MGR.KICAD_SEXP)
    io.FootprintSave(FPLIB, fp)


def add_board_fp(bd, name, at, rot=0.0, side="F", net_by_pad=None, ref=""):
    """Place a library footprint that is not in the schematic (legs, slots, mouse bites)."""
    fp = P.FootprintLoad(FPLIB, name)
    fp.SetAttributes(fp.GetAttributes() | P.FP_BOARD_ONLY | P.FP_EXCLUDE_FROM_BOM | P.FP_EXCLUDE_FROM_POS_FILES)
    fp.SetReference(ref)
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)
    bd.b.Add(fp)
    fp.SetPosition(xy(*at))
    if side == "B":
        fp.Flip(fp.GetPosition(), P.FLIP_DIRECTION_LEFT_RIGHT)
    fp.SetOrientationDegrees(rot)
    for pad in fp.Pads():
        net = (net_by_pad or {}).get(pad.GetNumber())
        if net:
            pad.SetNet(bd.net(net))
    return fp


def write_lib_tables(out):
    with open(os.path.join(out, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table\n\t(version 7)\n\t(lib (name "fable") (type "KiCad") '
                '(uri "${KIPRJMOD}/../lib/fable.pretty") (options "") (descr "poc_fable footprints"))\n)\n')
    with open(os.path.join(out, "sym-lib-table"), "w") as f:      # every symbol comes from KiCad's own libraries
        f.write('(sym_lib_table\n\t(version 7)\n)\n')


# ---------------------------------------------------------------------------- checks and CAM
def rename_nets(bd, names):
    """Give the board's nets the names the schematic uses ({name here: name there}): a local
    label makes '/NAME', an unlabelled net is named after a pin. Call it last, just before the
    board is saved: the code that builds the board looks nets up by the names of the Circuit."""
    for old, new in names.items():
        if old != new and old in bd.nets:
            bd.nets[old].SetNetname(new)


def run_drc(pcb):
    rep = pcb.replace(".kicad_pcb", "_drc.json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--schematic-parity",
                    "-o", rep, pcb], capture_output=True, text=True)
    d = json.load(open(rep))
    counts = {}
    for v in d.get("violations", []):
        key = (v["severity"], v["type"])
        counts[key] = counts.get(key, 0) + 1
    parity = d.get("schematic_parity", [])
    return counts, len(d.get("unconnected_items", [])), len(parity), d


def bom_rows(circuit):
    """[(value, footprint, mpn, lcsc, price, src, [refs])] of the parts to buy."""
    rows = {}
    for p in circuit.parts:
        if p.ref.startswith("#") or not p.in_bom or p.dnp or not p.footprint:
            continue
        key = (p.value, p.footprint.split(":")[-1], p.fields.get("MPN", ""), p.fields.get("LCSC", ""),
               float(p.fields.get("Price", 0) or 0), p.fields.get("PriceSrc", ""))
        rows.setdefault(key, []).append(p.ref)

    def refkey(r):
        head = r.rstrip("0123456789")
        return head, int("0" + r[len(head):])
    return [(*k, sorted(v, key=refkey)) for k, v in sorted(rows.items(), key=lambda kv: refkey(sorted(kv[1], key=refkey)[0]))]


def write_bom(circuit, path_csv):
    rows = bom_rows(circuit)
    with open(path_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC", "MPN", "Qty", "Unit USD", "Price source"])
        for val, fp, mpn, lcsc, price, src, refs in rows:
            w.writerow([val, ",".join(refs), fp, lcsc, mpn, len(refs), f"{price:.3f}", src])
    return rows


def cam(pcb, sch, out, name):
    """Gerbers + drill (zipped), position file, schematic PDF, renders."""
    g = os.path.join(out, "gerbers")
    shutil.rmtree(g, ignore_errors=True)
    os.makedirs(g)
    layers = "F.Cu,B.Cu,F.Mask,B.Mask,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,Edge.Cuts"
    r1 = subprocess.run(["kicad-cli", "pcb", "export", "gerbers", "--layers", layers, "--no-protel-ext",
                         "-o", g + "/", pcb], capture_output=True, text=True)
    r2 = subprocess.run(["kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
                         "--excellon-oval-format", "alternate", "--generate-map", "--map-format", "pdf",
                         "-o", g + "/", pcb], capture_output=True, text=True)
    z = os.path.join(out, f"{name}_gerbers.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(g)):
            if not f.endswith(".pdf"):
                zf.write(os.path.join(g, f), f)
    subprocess.run(["kicad-cli", "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both",
                    "-o", os.path.join(out, f"{name}_pos.csv"), pcb], capture_output=True, text=True)
    subprocess.run(["kicad-cli", "sch", "export", "pdf", "-o", os.path.join(out, f"{name}_schematic.pdf"), sch],
                   capture_output=True, text=True)
    for side in ("top", "bottom"):
        subprocess.run(["kicad-cli", "pcb", "render", "--side", side, "--width", "1600", "--height", "1600",
                        "--quality", "basic", "-o", os.path.join(out, f"render_{side}.png"), pcb],
                       capture_output=True, text=True)
    return z, (r1.returncode, r2.returncode)


def jlc_files(circuit, out, name, skip=()):
    """BOM and placement (CPL) files in the column layout of JLCPCB's assembly order form.
    The references in `skip` are left out (hand-soldered parts).

    Taken from the BOM rows and from KiCad's position file. Underside parts: JLCPCB counts the
    rotation as seen from the underside, so the angle is mirrored (180 - angle). Their library
    part can still be turned differently from the KiCad footprint: check every polarised part in
    the placement preview of the order form."""
    rows = [(*row[:-1], [r for r in row[-1] if r not in skip]) for row in bom_rows(circuit)]
    rows = [row for row in rows if row[-1]]
    refs = {r for row in rows for r in row[-1]}
    bom = os.path.join(out, f"{name}_jlc_bom.csv")
    with open(bom, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for val, fp, mpn, lcsc, price, src, rr in rows:
            w.writerow([mpn or val, ",".join(rr), fp, lcsc])
    cpl = os.path.join(out, f"{name}_jlc_cpl.csv")
    placed = 0
    with open(os.path.join(out, f"{name}_pos.csv"), newline="") as f, open(cpl, "w", newline="") as g:
        w = csv.writer(g)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for row in csv.DictReader(f):
            if row["Ref"] not in refs:
                continue
            bottom = row["Side"].lower().startswith("b")
            rot = float(row["Rot"])
            rot = (180.0 - rot) % 360.0 if bottom else rot % 360.0
            w.writerow([row["Ref"], f"{float(row['PosX']):.3f}mm", f"{float(row['PosY']):.3f}mm",
                        "Bottom" if bottom else "Top", f"{rot:.0f}"])
            placed += 1
    return dict(bom=bom, cpl=cpl, placed=placed, expected=len(refs))
