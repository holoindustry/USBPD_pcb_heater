"""Hand-arranged KiCad schematic: symbols placed in functional groups and joined by wires.

The writer of the sibling toolkit (../gen/eda/kicad_sch.py) hangs a net label on every pin.
Here a layout function (gen/sheets.py) places each symbol and draws each wire, and this module
turns that into the .kicad_sch file and proves it against the Circuit:

  - before writing (Sheet.check): every net of the Circuit is one connected piece of wire, no
    two nets touch, no wire end hangs free, every label and power symbol sits on its own net;
  - after writing (verify): KiCad's ERC and KiCad's netlist export, compared pin by pin.

Sheet coordinates are whole grid steps of 1.27 mm, x to the right, y down.
Nets get their name from a power symbol or from a local label; a net with neither keeps the
name KiCad derives from a pin (verify() returns the names, the PCB takes them over).
"""
import copy
import json
import math
import os
import re
import subprocess
import uuid as _uuid

from eda import kicad_sch
from eda import sexpr as S
from eda.sexpr import Q

G = 1.27                       # grid step, mm
PAPER = {"A4": (297, 210), "A3": (420, 297)}
_NS = _uuid.UUID("6f1c1f0e-5b7a-4c56-9d0e-0a1b2c3d4e5f")


def mm(g):
    return round(g * G, 4)


class Lib(kicad_sch.SymLib):
    """KiCad symbol libraries; pins() covers all units of a multi-unit symbol (the PCB side and
    the netlist need the whole component, whatever unit a pin is drawn in)."""

    def get(self, lib_id):
        """Flattened symbol; a derived symbol also keeps the parent's fields it does not redefine
        (ki_locked of multi-unit parts), as KiCad does: otherwise ERC reports a library mismatch."""
        if lib_id in self._sym:
            return self._sym[lib_id]
        lib, name = lib_id.split(":", 1)
        ext = S.find(self._raw(lib, name), "extends")
        sym = super().get(lib_id)
        if ext:
            have = {str(p[1]) for p in S.find_all(sym, "property")}
            extra = [copy.deepcopy(p) for p in S.find_all(self.get(f"{lib}:{ext[1]}"), "property") if str(p[1]) not in have]
            k = max(i for i, x in enumerate(sym) if isinstance(x, list) and x[0] == "property") + 1
            sym[k:k] = extra
        return sym

    def pins(self, lib_id, unit=None):
        out = []
        for sub in S.find_all(self.get(lib_id), "symbol"):
            m = re.match(r".*_(\d+)_(\d+)$", str(sub[1]))
            if int(m.group(2)) not in (0, 1):
                continue
            for p in S.find_all(sub, "pin"):
                at = S.find(p, "at")
                hidden = any(isinstance(e, list) and e[:2] == ["hide", "yes"] for e in p) or "hide" in p
                out.append(dict(type=p[1], number=str(S.find(p, "number")[1]), name=str(S.find(p, "name")[1]),
                                x=float(at[1]), y=float(at[2]), rot=int(float(at[3])) if len(at) > 3 else 0,
                                length=float(S.find(p, "length")[1]), hidden=hidden, unit=int(m.group(1))))
        return out

    def units(self, lib_id):
        us = {int(re.match(r".*_(\d+)_(\d+)$", str(sub[1])).group(1)) for sub in S.find_all(self.get(lib_id), "symbol")}
        return sorted(us - {0}) or [1]

    def outline(self, lib_id, unit):
        """Corner points (library mm, y up) of the body graphics drawn for one unit."""
        pts = []
        for sub in S.find_all(self.get(lib_id), "symbol"):
            m = re.match(r".*_(\d+)_(\d+)$", str(sub[1]))
            if int(m.group(1)) not in (0, unit) or int(m.group(2)) not in (0, 1):
                continue
            for g in sub[2:]:
                if g[0] == "rectangle":
                    pts += [tuple(map(float, S.find(g, k)[1:3])) for k in ("start", "end")]
                elif g[0] in ("polyline", "bezier"):
                    pts += [tuple(map(float, p[1:3])) for p in S.find_all(S.find(g, "pts"), "xy")]
                elif g[0] == "circle":
                    (cx, cy), r = map(float, S.find(g, "center")[1:3]), float(S.find(g, "radius")[1])
                    pts += [(cx - r, cy - r), (cx + r, cy + r)]
                elif g[0] == "arc":
                    pts += [tuple(map(float, S.find(g, k)[1:3])) for k in ("start", "mid", "end")]
        return pts

    def field(self, lib_id, name):
        """(x, y, angle, justify words) of a field in the library symbol."""
        for pr in S.find_all(self.get(lib_id), "property"):
            if pr[1] == name:
                at = S.find(pr, "at")
                j = S.find(S.find(pr, "effects") or [], "justify") or []
                return float(at[1]), float(at[2]), int(float(at[3])), [str(w) for w in j[1:]]
        return 0.0, 0.0, 0, []


class Placed:
    """One drawn symbol unit."""

    def __init__(self, lib, ref, lib_id, unit, x, y, rot, mirror):
        self.lib, self.ref, self.lib_id, self.unit = lib, ref, lib_id, unit
        self.x, self.y, self.rot, self.mirror = x, y, rot % 360, mirror
        self.pins = [p for p in lib.pins(lib_id) if p["unit"] in (0, unit)]
        self.ref_at = self.val_at = None
        self.show_val = True

    def xf(self, px, py):
        """Library point (mm, y up) -> offset from the symbol origin in grid steps, y down.
        KiCad turns the symbol first and mirrors it on the sheet after ('x': top to bottom)."""
        qx, qy = px / G, -py / G
        c, s = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[self.rot]
        qx, qy = qx * c + qy * s, -qx * s + qy * c
        return (qx, -qy) if self.mirror == "x" else (-qx, qy) if self.mirror == "y" else (qx, qy)

    def vec(self, vx, vy):
        """Direction (sheet frame of the unturned symbol, y down) -> direction as drawn."""
        return tuple(round(v) for v in self.xf(vx * G, -vy * G))

    def pin_xy(self, pin):
        dx, dy = self.xf(pin["x"], pin["y"])
        x, y = self.x + dx, self.y + dy
        if abs(x - round(x)) > 1e-6 or abs(y - round(y)) > 1e-6:
            raise ValueError(f"{self.ref} pin {pin['number']} is off the 1.27 mm grid at ({x}, {y})")
        return round(x), round(y)

    def side(self, pin):
        """Side of the body a pin leaves from, as drawn: 'l', 'r', 't' or 'b'."""
        a = math.radians(pin["rot"])
        dx, dy = self.xf(math.cos(a) * G, math.sin(a) * G)          # from the pin end towards the body
        return {(1, 0): "l", (-1, 0): "r", (0, 1): "t", (0, -1): "b"}[(round(dx), round(dy))]

    def body(self):
        pts = [self.xf(*p) for p in self.lib.outline(self.lib_id, self.unit)]
        if not pts:
            pts = [self.xf(p["x"], p["y"]) for p in self.pins] or [(0, 0)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return self.x + min(xs), self.y + min(ys), self.x + max(xs), self.y + max(ys)

    def fields(self):
        """Where the reference and the value go: (x, y, 'l' | 'c' | 'r') each, text horizontal."""
        if self.ref_at and self.val_at:
            return [(self.x + a[0], self.y + a[1], a[2]) for a in (self.ref_at, self.val_at)]
        out = []
        lib_ok = self.rot in (0, 180) and self.lib.field(self.lib_id, "Reference")[2] == 0
        x0, y0, x1, y1 = self.body()
        sides = {self.side(p) for p in self.pins if not p["hidden"]}
        for k, name in enumerate(("Reference", "Value")):
            fx, fy, _, just = self.lib.field(self.lib_id, name)
            if lib_ok:
                dx, dy = self.xf(fx, fy)
                h = "l" if "left" in just else "r" if "right" in just else "c"
                if self.vec(1, 0)[0] < 0:
                    h = {"l": "r", "r": "l", "c": "c"}[h]
                v = self.vec(0, -1)[1] * (0.6 if "bottom" in just else -0.6 if "top" in just else 0.0)
                pos = (self.x + dx, self.y + dy + v, h)
            elif "r" not in sides:
                pos = (x1 + 0.9, (y0 + y1) / 2 + (-1.0, 1.0)[k], "l")
            elif sides == {"l", "r"}:
                pos = ((x0 + x1) / 2, (y0 - 1.2, y1 + 1.2)[k], "c")
            elif "t" not in sides:
                pos = ((x0 + x1) / 2, y0 - (2.6, 1.2)[k], "c")
            elif "l" not in sides:
                pos = (x0 - 0.9, (y0 + y1) / 2 + (-1.0, 1.0)[k], "r")
            else:
                pos = ((x0 + x1) / 2, y1 + (1.2, 2.6)[k], "c")
            out.append(pos)
        given = (self.ref_at, self.val_at)
        return [(self.x + g[0], self.y + g[1], g[2]) if g else o for g, o in zip(given, out)]

    def file_just(self, h):
        """Justification to store so that the text is drawn with justification h. KiCad keeps
        field text in the symbol's frame: a field of a symbol turned by 90 degrees needs angle 90
        to read horizontally, and left/right swap when the frame's text direction is reversed."""
        angle = 0 if self.rot in (0, 180) else 90
        along = self.vec(1, 0) if angle == 0 else self.vec(0, -1)
        if along[0] < 0:
            h = {"l": "r", "r": "l", "c": "c"}[h]
        return angle, {"l": ["left"], "r": ["right"], "c": []}[h]


class Sheet:
    def __init__(self, circuit, lib, paper="A3"):
        self.c, self.lib, self.paper = circuit, lib, paper
        self.parts = {p.ref: p for p in circuit.parts}
        self.placed = []
        self.pin_at = {}                 # (ref, pin number) -> (x, y)
        self.pin_net = {}                # (ref, pin number) -> net of the Circuit, None = not connected
        self.power = []                  # (net, x, y)
        self.segs = []
        self.labels = []                 # (net, x, y, 'l' | 'r')
        self.texts = []                  # (text, x, y, size mm, bold)
        self.boxes = []                  # (x0, y0, x1, y1)
        self._n = 0
        for p in circuit.parts:
            for key, net in p.pins.items():
                num = kicad_sch.resolve_pin(lib, p, key)["number"]
                self.pin_net[(p.ref, num)] = None if net in (None, "NC") else net

    # ------------------------------------------------------------------ drawing
    def sym(self, ref, x, y, rot=0, mirror=None, unit=1, ref_at=None, val_at=None, val=True):
        """Place (one unit of) a part of the Circuit. ref_at / val_at = (dx, dy, 'l'|'c'|'r')."""
        part = self.parts[ref]
        pl = Placed(self.lib, ref, part.lib_id, unit, x, y, rot, mirror)
        pl.ref_at, pl.val_at, pl.show_val = ref_at, val_at, val
        for pin in pl.pins:
            if (ref, pin["number"]) not in self.pin_net:
                if pin["type"] == "no_connect":
                    continue
                raise ValueError(f"{ref} ({part.lib_id}): pin {pin['number']} has no net in the Circuit")
            self.pin_at[(ref, pin["number"])] = pl.pin_xy(pin)
        self.placed.append(pl)
        return pl

    def pwr(self, net, at, rot=0):
        """Power symbol (power:<net>) with its pin on a point or pin."""
        x, y = self.pt(at)
        self._n += 1
        pl = Placed(self.lib, f"#PWR{self._n:02d}", f"power:{net}", 1, x, y, rot, None)
        self.placed.append(pl)
        self.power.append((net, x, y))
        return pl

    def pin(self, spec):
        ref, key = spec.split(".", 1)
        part = self.parts[ref]
        pins = self.lib.pins(part.lib_id)
        hit = [p for p in pins if p["number"] == key] or [p for p in pins if p["name"] == key]
        try:
            at = {self.pin_at[(ref, p["number"])] for p in hit}
        except KeyError:
            raise KeyError(f"{spec}: that unit of {ref} is not placed yet") from None
        if len(at) != 1:                                 # several pins only if they are stacked on one point
            raise KeyError(f"pin {spec!r} not found or ambiguous")
        return at.pop()

    def pt(self, spec, prev=None):
        """A point: 'REF.PIN', or (x, y) whose items are a number, None (as the previous point),
        '+n' / '-n' (from the previous point) or 'REF.PIN' (that pin's x or y)."""
        if isinstance(spec, str):
            return self.pin(spec)
        out = []
        for i, v in enumerate(spec):
            if v is None:
                out.append(prev[i])
            elif isinstance(v, str) and re.fullmatch(r"[+-]\d+", v):
                out.append(prev[i] + int(v))
            elif isinstance(v, str):
                out.append(self.pin(v)[i])
            else:
                out.append(v)
        return tuple(out)

    def wire(self, *specs):
        """Polyline through the points; each leg must be horizontal or vertical."""
        pts = []
        for s in specs:
            pts.append(self.pt(s, pts[-1] if pts else None))
        for a, b in zip(pts, pts[1:]):
            if a == b:
                continue
            if a[0] != b[0] and a[1] != b[1]:
                raise ValueError(f"wire leg {a} -> {b} is not horizontal or vertical ({specs})")
            self.segs.append((*a, *b))
        return pts

    def label(self, net, at, side="l"):
        """Local label on a wire; side 'l': the text starts at the point, 'r': it ends there."""
        x, y = self.pt(at)
        self.labels.append((net, x, y, side))

    def text(self, txt, x, y, size=1.27, bold=False):
        self.texts.append((txt, x, y, size, bold))

    def box(self, x0, y0, x1, y1, title=""):
        self.boxes.append((x0, y0, x1, y1))
        if title:
            self.text(title, x0 + 1.5, y0 + 1.2, size=2.0, bold=True)

    # ------------------------------------------------------------------ connectivity
    def _split(self):
        """Wire pieces cut at every wire end, pin and label, without duplicates."""
        cuts = {s[:2] for s in self.segs} | {s[2:] for s in self.segs} | set(self.pin_at.values())
        cuts |= {(x, y) for _, x, y in self.power} | {(x, y) for _, x, y, _ in self.labels}
        out = set()
        for x0, y0, x1, y1 in self.segs:
            a, b = min((x0, y0), (x1, y1)), max((x0, y0), (x1, y1))
            inner = sorted(p for p in cuts if (a[0] == b[0] == p[0] and a[1] < p[1] < b[1])
                           or (a[1] == b[1] == p[1] and a[0] < p[0] < b[0]))
            chain = [a] + inner + [b]
            out |= set(zip(chain, chain[1:]))
        return sorted(out)

    def check(self):
        """Compare the drawing with the Circuit. Returns (wire pieces, junction points, the nets
        named by a label or power symbol); raises ValueError listing every difference."""
        errors = []
        need = {}
        for p in self.c.parts:
            need[p.ref] = set(self.lib.units(p.lib_id))
        for pl in self.placed:
            if pl.ref in need:
                if pl.unit not in need[pl.ref]:
                    errors.append(f"{pl.ref}: unit {pl.unit} placed twice or unknown")
                need[pl.ref].discard(pl.unit)
        errors += [f"{ref}: unit(s) {sorted(u)} not placed" for ref, u in need.items() if u]

        pieces = self._split()
        parent = {}

        def find(p):
            parent.setdefault(p, p)
            while parent[p] != p:
                parent[p] = parent[parent[p]]
                p = parent[p]
            return p

        ends = {}
        for a, b in pieces:
            parent[find(a)] = find(b)
            for p in (a, b):
                ends[p] = ends.get(p, 0) + 1
        pins_at = {}
        for key, p in self.pin_at.items():
            pins_at.setdefault(p, []).append(key)
        for _, x, y in self.power:
            pins_at.setdefault((x, y), []).append(("#PWR", ""))
        name_at = [(net, (x, y)) for net, x, y in self.power]
        for net, x, y, _ in self.labels:
            if (x, y) in ends:
                name_at.append((net, (x, y)))
            else:
                errors.append(f"label {net} at ({x}, {y}) is not on a wire")
        first = {}
        for net, p in name_at:                           # equal names join, as they do in KiCad
            parent[find(p)] = find(first.setdefault(net, p))
        groups = {}
        for p, keys in pins_at.items():
            g = groups.setdefault(find(p), dict(pins=[], names=set()))
            g["pins"] += [k for k in keys if k[0] != "#PWR"]
        named = set()
        for net, p in name_at:
            groups.setdefault(find(p), dict(pins=[], names=set()))["names"].add(net)
        where = {}
        for root, g in groups.items():
            nets = {self.pin_net[k] for k in g["pins"]}
            if None in nets and len(g["pins"]) > 1:
                errors.append(f"not-connected pin wired to {sorted(g['pins'])}")
            nets.discard(None)
            if len(nets) > 1:
                errors.append(f"short between {sorted(nets)} (pins {sorted(g['pins'])})")
            for n in g["names"]:
                if nets and n not in nets:
                    errors.append(f"label or power symbol {n} sits on net {sorted(nets)}")
                named.add(n)
            for n in nets:
                where.setdefault(n, []).append(sorted(k for k in g["pins"] if self.pin_net[k] == n))
        for net, parts in sorted(where.items()):
            if len(parts) > 1:
                errors.append(f"net {net} is drawn in {len(parts)} separate pieces: {parts}")
        for key, net in self.pin_net.items():
            if net and key not in self.pin_at:
                errors.append(f"{key[0]} pin {key[1]} ({net}) is not drawn")
        labelled = {(x, y) for _, x, y, _ in self.labels}
        for p, n in sorted(ends.items()):
            if n == 1 and p not in pins_at and p not in labelled:
                errors.append(f"wire end at {p} hangs free")
        if errors:
            raise ValueError(f"schematic {self.c.name} does not match the circuit:\n  " + "\n  ".join(errors))
        junctions = sorted(p for p, n in ends.items() if n >= 3 or (n == 2 and p in pins_at))
        return pieces, junctions, named

    # ------------------------------------------------------------------ lint (drawing quality)
    def _text_boxes(self):
        """Approximate boxes of all visible text: (what, x0, y0, x1, y1)."""
        out = []

        def box(what, x, y, txt, h, size=1.27, v="c"):
            lines = txt.split("\n")
            w = max(len(ln) for ln in lines) * size * 0.85 / G
            ht = len(lines) * size * 1.45 / G
            x0 = x if h == "l" else x - w if h == "r" else x - w / 2
            y0 = y - ht / 2 if v == "c" else y if v == "t" else y - ht
            out.append((what, x0, y0, x0 + w, y0 + ht))

        for pl in self.placed:
            (rx, ry, rh), (vx, vy, vh) = pl.fields()
            part = self.parts.get(pl.ref)
            if part is not None:
                units = self.lib.units(pl.lib_id)
                box(f"{pl.ref} reference", rx, ry, pl.ref + ("A" if len(units) > 1 else ""), rh)
                if pl.show_val:
                    box(f"{pl.ref} value", vx, vy, part.value, vh)
            elif not pl.lib_id.endswith("PWR_FLAG"):
                box(f"{pl.lib_id.split(':')[1]} symbol text", vx, vy, pl.lib_id.split(":")[1], vh)
        for net, x, y, side in self.labels:
            box(f"label {net}", x, y - 0.2, net, side, v="b")
        for txt, x, y, size, _ in self.texts:
            box(f"text {txt[:18]!r}", x, y, txt, "l", size, v="t")
        return out

    def lint(self):
        """Overlaps a reader would trip over; returns a list of messages (empty = tidy)."""
        msgs = []
        hit = lambda a, b, m=0.0: a[0] < b[2] - m and b[0] < a[2] - m and a[1] < b[3] - m and b[1] < a[3] - m
        bodies = [(pl.ref if pl.ref in self.parts else pl.lib_id.split(":")[1], pl.body()) for pl in self.placed]
        for i, (ra, a) in enumerate(bodies):
            for rb, b in bodies[i + 1:]:
                if hit(a, b):
                    msgs.append(f"symbols {ra} and {rb} overlap")
        pieces = self._split()
        own = {}                                         # a symbol's own pin wires may graze its outline
        for (ref, _), p in self.pin_at.items():
            own.setdefault(ref, set()).add(p)
        for (x0, y0), (x1, y1) in pieces:
            for ref, b in bodies:
                if {(x0, y0), (x1, y1)} & own.get(ref, set()):
                    continue
                if hit((x0, y0, x1, y1), (b[0] + 0.3, b[1] + 0.3, b[2] - 0.3, b[3] - 0.3)):
                    msgs.append(f"wire ({x0},{y0})-({x1},{y1}) runs through {ref}")
        texts = self._text_boxes()
        for i, (wa, *a) in enumerate(texts):
            for wb, *b in texts[i + 1:]:
                if hit(a, b, 0.1):
                    msgs.append(f"{wa} overlaps {wb}")
            for ref, b in bodies:
                if not wa.startswith(ref + " ") and hit(a, b, 0.1):
                    msgs.append(f"{wa} overlaps symbol {ref}")
            for (x0, y0), (x1, y1) in pieces:
                if a[0] + 0.1 < max(x0, x1) and min(x0, x1) < a[2] - 0.1 and a[1] + 0.1 < max(y0, y1) and min(y0, y1) < a[3] - 0.1 or \
                        (x0 == x1 and a[0] + 0.1 < x0 < a[2] - 0.1 and y0 < a[3] - 0.1 and a[1] + 0.1 < y1) or \
                        (y0 == y1 and a[1] + 0.1 < y0 < a[3] - 0.1 and x0 < a[2] - 0.1 and a[0] + 0.1 < x1):
                    msgs.append(f"{wa} is crossed by wire ({x0},{y0})-({x1},{y1})")
        W, H = (v / G for v in PAPER[self.paper])
        for what, *a in texts + [(r, *b) for r, b in bodies]:
            if a[0] < 9 or a[1] < 9 or a[2] > W - 9 or a[3] > H - 9 or (a[2] > W - 95 and a[3] > H - 36):
                msgs.append(f"{what} is off the sheet or in the title block")
        hs = [(a, b) for a, b in pieces if a[1] == b[1]]
        vs = [(a, b) for a, b in pieces if a[0] == b[0]]
        cross = sum(1 for (a, b) in hs for (c, d) in vs if a[0] < c[0] < b[0] and c[1] < a[1] < d[1])
        return msgs, cross

    # ------------------------------------------------------------------ file
    def _uid(self):
        self._n += 1
        return Q(str(_uuid.uuid5(_NS, f"{self.c.name}/{self._n}")))

    @staticmethod
    def _fx(size=1.27, just=(), hide=False, bold=False):
        font = ["font", ["size", size, size]] + ([["bold", "yes"]] if bold else [])
        e = ["effects", font] + ([["justify"] + list(just)] if just else [])
        return ([["hide", "yes"]] if hide else []) + [e]

    def write(self, path):
        pieces, junctions, named = self.check()
        self._n = 1000
        root = Q(str(_uuid.uuid5(_NS, self.c.name)))
        used = []
        for pl in self.placed:
            if pl.lib_id not in used:
                used.append(pl.lib_id)
        items = []
        for pl in self.placed:
            part = self.parts.get(pl.ref)
            power = part is None or pl.ref.startswith("#")
            value = part.value if part else pl.lib_id.split(":")[1]
            fields = dict(part.fields) if part else {}
            sx, sy = mm(pl.x), mm(pl.y)
            inst = ["symbol", ["lib_id", Q(pl.lib_id)], ["at", sx, sy, pl.rot]]
            if pl.mirror:
                inst.append(["mirror", pl.mirror])
            inst += [["unit", pl.unit], ["exclude_from_sim", "no"],
                     ["in_bom", "no" if power or not part.in_bom else "yes"], ["on_board", "no" if power else "yes"],
                     ["dnp", "yes" if part is not None and part.dnp else "no"], ["uuid", self._uid()]]
            (rx, ry, rh), (vx, vy, vh) = pl.fields()
            for name, val, (x, y, h), hide in (("Reference", pl.ref, (rx, ry, rh), power),
                                               ("Value", value, (vx, vy, vh), not pl.show_val)):
                angle, just = pl.file_just(h)
                inst.append(["property", Q(name), Q(val), ["at", mm(x), mm(y), angle]] + self._fx(just=just, hide=hide))
            inst.append(["property", Q("Footprint"), Q(part.footprint if part else ""), ["at", sx, sy, 0]] + self._fx(hide=True))
            for k in ("Datasheet", "Description"):
                inst.append(["property", Q(k), Q(str(fields.get(k, ""))), ["at", sx, sy, 0]] + self._fx(hide=True))
            for k, v in fields.items():
                if k not in ("Datasheet", "Description", "pcb"):
                    inst.append(["property", Q(k), Q(str(v)), ["at", sx, sy, 0]] + self._fx(hide=True))
            for pin in pl.pins:
                inst.append(["pin", Q(pin["number"]), ["uuid", self._uid()]])
            inst.append(["instances", ["project", Q(self.c.name),
                                       ["path", Q("/" + root), ["reference", Q(pl.ref)], ["unit", pl.unit]]]])
            items.append(inst)
            for pin in pl.pins:
                if part is not None and self.pin_net.get((pl.ref, pin["number"])) is None and pin["type"] != "no_connect":
                    x, y = pl.pin_xy(pin)
                    items.append(["no_connect", ["at", mm(x), mm(y)], ["uuid", self._uid()]])
        for (x0, y0), (x1, y1) in pieces:
            items.append(["wire", ["pts", ["xy", mm(x0), mm(y0)], ["xy", mm(x1), mm(y1)]],
                          ["stroke", ["width", 0], ["type", "default"]], ["uuid", self._uid()]])
        for x, y in junctions:
            items.append(["junction", ["at", mm(x), mm(y)], ["diameter", 0], ["color", 0, 0, 0, 0], ["uuid", self._uid()]])
        for net, x, y, side in self.labels:
            items.append(["label", Q(net), ["at", mm(x), mm(y), 0 if side == "l" else 180]]
                         + self._fx(just=["left" if side == "l" else "right", "bottom"]) + [["uuid", self._uid()]])
        for txt, x, y, size, bold in self.texts:
            items.append(["text", Q(txt), ["exclude_from_sim", "no"], ["at", mm(x), mm(y), 0]]
                         + self._fx(size=size, just=["left", "top"], bold=bold) + [["uuid", self._uid()]])
        for x0, y0, x1, y1 in self.boxes:
            items.append(["rectangle", ["start", mm(x0), mm(y0)], ["end", mm(x1), mm(y1)],
                          ["stroke", ["width", 0], ["type", "dash"]], ["fill", ["type", "none"]], ["uuid", self._uid()]])
        doc = ["kicad_sch", ["version", "20260101"], ["generator", Q("eeschema")], ["generator_version", Q("10.0")],
               ["uuid", root], ["paper", Q(self.paper)],
               ["title_block", ["title", Q(self.c.title)], ["rev", Q(self.c.rev)], ["company", Q(self.c.company)]],
               ["lib_symbols"] + [self.lib.get(l) for l in used]] + items + \
              [["sheet_instances", ["path", Q("/"), ["page", Q("1")]]], ["embedded_fonts", "no"]]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(S.dump(doc) + "\n")
        return named


# ---------------------------------------------------------------------------- verification
def verify(circuit, path, lib, named):
    """ERC and netlist export by kicad-cli; the netlist must hold exactly the nets of the Circuit.

    Returns violations, mismatches, extra_nets and names = {net of the Circuit: its name in
    KiCad}: a power symbol gives the plain name, a local label '/NAME', anything else the name
    KiCad makes up from a pin."""
    base = os.path.splitext(path)[0]
    erc = base + "_erc.json"
    subprocess.run(["kicad-cli", "sch", "erc", "--format", "json", "--severity-all", "-o", erc, path],
                   capture_output=True, text=True)
    viol = {}
    for sheet in json.load(open(erc)).get("sheets", []):
        for v in sheet.get("violations", []):
            viol.setdefault((v["severity"], v["type"]), []).append("; ".join(i["description"] for i in v.get("items", [])))
    net_file = base + ".net"
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", net_file, path],
                   capture_output=True, text=True)
    got = {}
    for n in S.find_all(S.find(S.parse(open(net_file).read()), "nets"), "net"):
        nodes = frozenset((str(S.find(x, "ref")[1]), str(S.find(x, "pin")[1])) for x in S.find_all(n, "node")
                          if not str(S.find(x, "ref")[1]).startswith("#"))
        if nodes:
            got[str(S.find(n, "name")[1])] = nodes
    want = {k: frozenset((r, str(pn)) for r, pn in v if not r.startswith("#"))
            for k, v in circuit.nets(lambda p, k: kicad_sch.resolve_pin(lib, p, k)["number"]).items()}
    by_nodes = {v: k for k, v in got.items()}
    names, mism = {}, []
    for net, nodes in want.items():
        if not nodes:
            continue
        name = by_nodes.get(nodes)
        if name is None:
            mism.append((net, sorted(nodes), "no net of the schematic has exactly these pins"))
        elif net in named and name.lstrip("/") != net:
            mism.append((net, sorted(nodes), f"is called {name} in the schematic"))
        else:
            names[net] = name
    extra = [k for k in got if k not in names.values() and not k.startswith("unconnected-")]
    return dict(violations=viol, mismatches=mism, extra_nets=extra, n_nets=len(names), names=names)
