"""Heater trace geometry (pure Python, no KiCad needed).

Serpentine of vertical lanes on the top layer, terminals at the two bottom corners:

  * constant copper gap between lanes; the trace gets narrower towards the left/right
    edges and next to the centre channel, and narrower again in a band along the top and
    bottom edges. Heat per area goes with 1/(width * pitch), so this puts more heat where
    the plate loses more.
  * a channel between the two centre lanes holds the temperature pickup bar.
  * lanes that would run into a leg slot land are cut short.

Run:  python3 gen/heater.py
"""
import math
import os
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "gen"))

import geom as G  # noqa: E402
from heater_geom import seg_dist  # noqa: E402  (sibling project: segment-segment distance)

RHO_CU_20 = 1.72e-8     # ohm m
ALPHA_CU = 0.00393      # 1/K


@dataclass
class Params:
    r_target: float = G.R20_TARGET
    cu_um: float = G.CU_UM
    gap: float = G.GAP
    # grading tuned with calc/thermal.py --tune (2026-11-10)
    edge_e: float = 0.36        # width reduction of the outermost lanes (fraction)
    edge_L: float = 7.0         # decay length of that reduction, mm
    ch_e: float = 0.12          # width reduction next to the centre channel
    ch_L: float = 1.5
    end_f: float = 0.74         # width factor inside the top/bottom edge bands
    end_L: float = 8.0          # depth of those bands, mm
    w_min: float = 0.20
    keep: float = 0.30          # copper clearance to slot lands


@dataclass
class Heater:
    p: Params
    n: int                      # number of lanes
    w_c: float                  # full trace width (centre of each half), mm
    xs: list                    # lane centre x, left to right
    ws: list                    # lane width outside the edge bands
    segs: list                  # [(a, b, width)] in electrical order, a/b = (x, y)
    term: tuple                 # ((x, y) HTR+, (x, y) HTR-)
    bar: tuple                  # pickup bar ((x, y0), (x, y1))
    r20: float
    length: float               # mm
    min_gap: float = 0.0
    notes: dict = field(default_factory=dict)

    @property
    def sheet_r(self):
        return RHO_CU_20 / (self.p.cu_um * 1e-6)

    def power_w(self, volts, temp_c=20.0):
        return volts ** 2 / (self.r20 * (1 + ALPHA_CU * (temp_c - 20.0)))


def _lane_widths(p, m, span):
    """Widths and centre x of the m lanes of the right half, channel -> edge."""
    x_in, x_out = G.CHANNEL / 2, G.CHANNEL / 2 + span
    s = [1.0] * m
    xs, ws = [], []
    for _ in range(8):
        w_c = (span - (m - 1) * p.gap) / sum(s)
        xs, ws, x = [], [], x_in
        for j in range(m):
            w = w_c * s[j]
            xs.append(x + w / 2)
            ws.append(w)
            x += w + p.gap
        s = [1 - p.edge_e * math.exp(-(x_out - xc) / p.edge_L) - p.ch_e * math.exp(-(xc - x_in) / p.ch_L)
             for xc in xs]
    return w_c, xs, ws


def _limits(p, x, w):
    """Lowest and highest y the centre line of a turn may take for a lane at x."""
    edge = G.HALF - G.EDGE
    lo, hi = -edge, edge
    for cx, cy, orient in G.LEG_SLOTS:
        x0, y0, x1, y1 = G.slot_rect(cx, cy, orient, grow=p.keep)
        if y0 > G.HALF or y1 < -G.HALF:
            continue                               # tail slots
        if x + w / 2 > x0 and x - w / 2 < x1:
            if cy > 0:
                hi = min(hi, y0)
            else:
                lo = max(lo, y1)
    return lo, hi


def build(p, n):
    if n % 4 != 2:
        raise ValueError("lane count must be 4k+2 so that the centre turn is at the top")
    m = n // 2
    span = G.HALF - G.EDGE - G.CHANNEL / 2
    w_c, xr, wr = _lane_widths(p, m, span)
    if min(wr) * p.end_f < p.w_min:
        raise ValueError("trace too narrow")
    xs = [-x for x in reversed(xr)] + xr
    ws = list(reversed(wr)) + wr
    band = G.HALF - G.EDGE - p.end_L                # |y| beyond this is the edge band
    wend = [w * p.end_f for w in ws]
    lim = [_limits(p, x, w) for x, w in zip(xs, ws)]

    # turn heights: lane i (0-based) and i+1 are joined at the top when i is even
    top = [0.0] * n
    bot = [0.0] * n
    for i in range(0, n - 1, 2):
        y = min(lim[i][1], lim[i + 1][1]) - max(wend[i], wend[i + 1]) / 2
        top[i] = top[i + 1] = y
    y_term = -(G.HALF - 1.1)
    bot[0] = bot[n - 1] = y_term
    for i in range(1, n - 1, 2):
        y = max(lim[i][0], lim[i + 1][0]) + max(wend[i], wend[i + 1]) / 2
        if i == 1 or i == n - 3:                    # keep clear of the terminal pads
            y = max(y, -(G.HALF - 2.1))
        bot[i] = bot[i + 1] = y

    def lane(i, up):
        """Segments of lane i from bottom to top (or reversed), split at the edge bands."""
        x = xs[i]
        cuts = [bot[i]] + [c for c in (-band, band) if bot[i] < c < top[i]] + [top[i]]
        out = []
        for y0, y1 in zip(cuts, cuts[1:]):
            mid = (y0 + y1) / 2
            w = wend[i] if abs(mid) > band else ws[i]
            out.append(((x, y0), (x, y1), w))
        return out if up else [(b, a, w) for a, b, w in reversed(out)]

    segs = []
    for i in range(n):
        up = i % 2 == 0
        segs += lane(i, up)
        if i < n - 1:
            y = top[i] if up else bot[i]
            w = max(wend[i], wend[i + 1]) if abs(y) > band else max(ws[i], ws[i + 1])
            segs.append(((xs[i], y), (xs[i + 1], y), w))

    rs = RHO_CU_20 / (p.cu_um * 1e-6)
    squares = sum(math.dist(a, b) / w for a, b, w in segs)
    squares -= 0.44 * 2 * (n - 1)                   # a 90 degree corner counts 0.56 square
    length = sum(math.dist(a, b) for a, b, _ in segs)
    crossing = top[m - 1]                           # the turn that crosses the channel
    bar = ((0.0, -(G.HALF - G.EDGE) + 0.6), (0.0, crossing - max(ws[m - 1], ws[m]) / 2 - G.BAR_W / 2 - 0.6))
    return Heater(p, n, w_c, xs, ws, segs, ((xs[0], y_term), (xs[-1], y_term)), bar, squares * rs, length)


def min_gap(h):
    """Smallest copper gap between heater segments that are not electrically adjacent."""
    segs = h.segs
    cell = 2.0
    grid = {}
    for k, (a, b, w) in enumerate(segs):
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        for gx in range(int(math.floor(x0 / cell)) - 1, int(math.floor(x1 / cell)) + 2):
            for gy in range(int(math.floor(y0 / cell)) - 1, int(math.floor(y1 / cell)) + 2):
                grid.setdefault((gx, gy), []).append(k)
    worst, seen = 1e9, set()
    for bucket in grid.values():
        for ii in range(len(bucket)):
            for jj in range(ii + 1, len(bucket)):
                i, j = bucket[ii], bucket[jj]
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                a, b, wa = segs[i]
                c, d, wb = segs[j]
                if min(math.dist(a, c), math.dist(a, d), math.dist(b, c), math.dist(b, d)) < 1e-6:
                    continue                        # connected copper
                worst = min(worst, seg_dist(a, b, c, d) - (wa + wb) / 2)
    return worst


def design(p=None, verbose=False):
    """Largest lane count that stays at or below r_target with the nominal gap; the gap is
    then widened (never narrowed) until the resistance is exactly r_target."""
    p = p or Params()
    best = None
    for n in range(42, 200, 4):
        try:
            h = build(p, n)
        except ValueError:
            continue
        if verbose:
            print(f"  n={n:3d}  w_c={h.w_c:.3f}  R20={h.r20:.2f}")
        if h.r20 <= p.r_target:
            best = h
    if best is None:
        raise RuntimeError("no feasible lane count")
    n = best.n
    lo, hi = p.gap, p.gap + 0.15                     # wider gap = narrower trace = more ohms
    for _ in range(40):
        mid = (lo + hi) / 2
        q = Params(**{**p.__dict__, "gap": mid})
        try:
            r = build(q, n).r20
        except ValueError:
            r = 1e9
        lo, hi = (mid, hi) if r < p.r_target else (lo, mid)
    h = build(Params(**{**p.__dict__, "gap": round(lo, 4)}), n)
    h.min_gap = min_gap(h)
    return h


def raster(h, dx=0.5):
    """Relative heat per cell (sum = 1) on a grid covering the heater zone. Returns (q, n)."""
    import numpy as np
    n = int(round(2 * G.HALF / dx))
    q = np.zeros((n, n))
    for a, b, w in h.segs:
        L = math.dist(a, b)
        k = max(1, int(L / (dx / 3)))
        t = (np.arange(k) + 0.5) / k
        ix = np.clip(((a[0] + t * (b[0] - a[0]) + G.HALF) / dx).astype(int), 0, n - 1)
        iy = np.clip(((a[1] + t * (b[1] - a[1]) + G.HALF) / dx).astype(int), 0, n - 1)
        np.add.at(q, (iy, ix), (L / k) / w)
    return q / q.sum(), n


if __name__ == "__main__":
    h = design(verbose="-v" in sys.argv)
    print(f"lanes {h.n}, trace {min(h.ws) * h.p.end_f:.3f}..{max(h.ws):.3f} mm (centre {h.w_c:.3f}), "
          f"gap {h.p.gap:.3f} mm, min copper gap {h.min_gap:.3f} mm")
    print(f"length {h.length / 1000:.2f} m, R20 {h.r20:.2f} ohm, sheet {h.sheet_r * 1e3:.3f} mohm/sq")
    for v in (20.0, 15.0, 12.0, 9.0, 5.0):
        print(f"  {v:4.0f} V: {v / h.r20:.2f} A cold, {h.power_w(v):5.1f} W cold, {h.power_w(v, 100):5.1f} W at 100 C")
    print(f"terminals {h.term}, pickup bar y {h.bar[0][1]:.1f}..{h.bar[1][1]:.1f}")
