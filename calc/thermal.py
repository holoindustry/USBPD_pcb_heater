#!/usr/bin/env python3
"""Thermal model of the heater zone.

1. steady(): 2-D thin-plate finite differences of the 70 x 70 mm zone. Heat is put where the
   generated trace is; in-plane conduction is the underside copper plane plus FR-4, plus the
   top copper along the lanes; losses are the top face (convection + radiation), the bare
   HASL underside over the leg gap, the edge faces, the four legs and the two links.
   The controller holds the sensor (pickup bar at RT1) at the set-point.
2. Plant: 1-D through-thickness transient model (top copper, FR-4 slices, underside plane)
   plus the sensor, used by control_sim.py.

Run:  python3 calc/thermal.py            report + calc/out/evenness.png
      python3 calc/thermal.py --tune     search the trace-width grading
"""
import math
import os
import sys

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "gen"))
sys.path.append(os.path.join(os.path.dirname(ROOT), "calc"))

import geom as G  # noqa: E402
import heater as H  # noqa: E402
from thermal_budget import h_conv, h_rad, air  # noqa: E402  (sibling project)

T_AMB = 25.0
K_CU, K_FR4_IN, K_FR4_Z = 385.0, 0.8, 0.30       # W/mK
EPS_TOP, EPS_BOT = 0.90, 0.15                    # solder mask / bare HASL
RHO_C_FR4 = 1850.0 * 1100.0                      # J/m3K
RHO_C_CU = 8960.0 * 385.0
G_LEG = 1.3e-3                                   # W/K per FR-4 leg (fin, 11 x 1.6 mm)
G_LINK = 1.7e-3                                  # W/K per link (copper traces + FR-4, ~23 mm)
T_TAIL = 40.0


def coeffs(t_plate):
    """Surface coefficients W/m2K: top, underside, edge face."""
    lc = (2 * G.HALF / 1000) / 4                 # area / perimeter of the square plate
    top = h_conv(t_plate, lc, True) + h_rad(t_plate, EPS_TOP)
    k_air = air((t_plate + T_AMB) / 2)[0]
    bot = max(k_air / (G.LEG_H / 1000), h_conv(t_plate, lc, False)) + h_rad(t_plate, EPS_BOT)
    edge = h_conv(t_plate, lc, True) + h_rad(t_plate, EPS_TOP)
    return top, bot, edge


def steady(h, t_set=100.0, dx=0.5, cover=None, h_cover=15.0):
    """Returns dict(T map [n x n, row 0 = bottom], P total W, stats).
    cover='half': an object on the right half takes h_cover W/m2K more than free air."""
    q, n = H.raster(h, dx)
    d = dx * 1e-3
    cu = K_CU * G.CU_UM * 1e-6
    fill = 0.62                                   # mean top copper fill along the lanes
    kx = cu + K_FR4_IN * G.T_PCB * 1e-3           # across the lanes
    ky = kx + cu * fill                           # along the lanes
    h_top, h_bot, h_edge = coeffs(t_set)
    htop = np.full((n, n), h_top)
    xs = (np.arange(n) + 0.5) * dx - G.HALF
    X, Y = np.meshgrid(xs, xs)
    if cover == "half":
        htop[X > 0] += h_cover
    idx = np.arange(n * n).reshape(n, n)
    diag = ((htop + h_bot) * d * d).ravel().copy()
    rhs = diag * T_AMB
    rows, cols, vals = [], [], []
    for dy, dxx, k in ((0, 1, kx), (0, -1, kx), (1, 0, ky), (-1, 0, ky)):
        src = idx[max(0, -dy):n - max(0, dy), max(0, -dxx):n - max(0, dxx)].ravel()
        dst = idx[max(0, dy):n - max(0, -dy), max(0, dxx):n - max(0, -dxx)].ravel()
        rows.append(src); cols.append(dst); vals.append(np.full(len(src), -k))
        np.add.at(diag, src, k)
    for edge_cells in (idx[0, :], idx[-1, :], idx[:, 0], idx[:, -1]):
        ge = h_edge * G.T_PCB * 1e-3 * d
        np.add.at(diag, edge_cells, ge)
        np.add.at(rhs, edge_cells, ge * T_AMB)
    sinks = [(cx, cy, G_LEG, T_AMB + 15) for cx, cy, _ in G.LEG_SLOTS if abs(cy) < G.HALF]
    sinks += [(s * (G.HALF - 2.5), -G.HALF + 0.5, G_LINK, T_TAIL) for s in (-1, 1)]
    for px, py, g, ts in sinks:
        cells = idx[(np.abs(X - px) < 2.0) & (np.abs(Y - py) < 2.0)]
        np.add.at(diag, cells, g / len(cells))
        np.add.at(rhs, cells, g / len(cells) * ts)
    rows.append(np.arange(n * n)); cols.append(np.arange(n * n)); vals.append(diag)
    M = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n * n, n * n))
    lu = spla.splu(M.tocsc())
    t0 = lu.solve(rhs)
    t1 = lu.solve(q.ravel())                       # response to 1 W
    sy = G.SENSORS[0][1]
    c = idx[int((sy + G.HALF) / dx), n // 2]
    p_tot = (t_set - t0[c]) / t1[c]
    T = (t0 + p_tot * t1).reshape(n, n)
    inner = (np.abs(X) < G.HALF - 5) & (np.abs(Y) < G.HALF - 5)
    mid = (np.abs(X) < G.HALF - 10) & (np.abs(Y) < G.HALF - 10)
    return dict(T=T, X=X, Y=Y, P=p_tot, h=(h_top, h_bot, h_edge),
                all=(T.min(), T.max()), inner=(T[inner].min(), T[inner].max()),
                mid=(T[mid].min(), T[mid].max()),
                p_leak=sum(g * (t_set - ts) for *_, g, ts in sinks))


# ---------------------------------------------------------------------------- transient plant
class Plant:
    """1-D through-thickness model of the plate (per unit area), with sensor and optional load.

    State: top copper, n FR-4 slices, underside plane. step(p_watt, dt) advances it.
    t_sensor = lagged mix of top copper and underside plane (pickup bar + vias)."""

    def __init__(self, r20, area=(2 * G.HALF / 1000) ** 2, n=8, w_top=0.7, tau_s=0.8, t0=T_AMB,
                 h_extra_top=0.0):
        self.r20, self.area, self.n = r20, area, n
        self.dz = G.T_PCB * 1e-3 / n
        self.c_slice = RHO_C_FR4 * self.dz
        self.c_top = RHO_C_CU * G.CU_UM * 1e-6 * 0.62 + 1300 * 1400 * 25e-6
        self.c_bot = RHO_C_CU * G.CU_UM * 1e-6
        self.w_top, self.tau_s = w_top, tau_s
        self.h_extra_top = h_extra_top
        self.T = [t0] * (n + 2)
        self.t_sensor = t0
        self.leak = (4 * G_LEG + 2 * G_LINK) / area       # legs + links, W/m2K equivalent

    @property
    def t_top(self):
        return self.T[0]

    @property
    def t_bottom(self):
        return self.T[-1]

    def r_heater(self):
        return self.r20 * (1 + H.ALPHA_CU * (self.T[0] - 20.0))

    def heat_capacity(self):
        return self.area * (self.c_top + self.n * self.c_slice + self.c_bot)

    def step(self, p_watt, dt):
        T, n = self.T, self.n
        h_top, h_bot, _ = coeffs(max(T[0], T_AMB + 1.0))
        g = K_FR4_Z / self.dz
        q = [0.0] * (n + 2)
        q[0] = p_watt / self.area - (h_top + self.h_extra_top) * (T[0] - T_AMB) - 2 * g * (T[0] - T[1])
        q[1] = 2 * g * (T[0] - T[1]) - g * (T[1] - T[2])
        for i in range(2, n):
            q[i] = g * (T[i - 1] - T[i]) - g * (T[i] - T[i + 1])
        q[n] = g * (T[n - 1] - T[n]) - 2 * g * (T[n] - T[n + 1])
        q[n + 1] = 2 * g * (T[n] - T[n + 1]) - (h_bot + self.leak) * (T[n + 1] - T_AMB)
        T[0] += q[0] / self.c_top * dt
        for i in range(1, n + 1):
            T[i] += q[i] / self.c_slice * dt
        T[n + 1] += q[n + 1] / self.c_bot * dt
        mix = self.w_top * T[0] + (1 - self.w_top) * T[n + 1]
        self.t_sensor += (mix - self.t_sensor) / self.tau_s * dt


DT = 0.002          # stable step for the explicit scheme above (s)


def warmup(h, volts, t_end=600.0):
    """Time to reach 99 C at full duty and the 100 %-duty equilibrium (C)."""
    pl = Plant(h.r20)
    t, t99 = 0.0, None
    while t < t_end:
        pl.step(volts ** 2 / pl.r_heater(), DT)
        t += DT
        if t99 is None and pl.t_top >= 99.0:
            t99 = t
    return t99, pl.t_top


def report(h, plot=True):
    out = os.path.join(HERE, "out")
    os.makedirs(out, exist_ok=True)
    res = {}
    for name, kw in (("open", {}), ("half covered", dict(cover="half"))):
        r = steady(h, **kw)
        res[name] = r
        print(f"{name:13s} P {r['P']:5.2f} W  whole {r['all'][0]:5.1f}..{r['all'][1]:5.1f} C  "
              f"inner 60x60 {r['inner'][0]:5.1f}..{r['inner'][1]:5.1f} C  inner 50x50 {r['mid'][0]:5.1f}..{r['mid'][1]:5.1f} C")
    r = res["open"]
    print(f"h top {r['h'][0]:.1f}, underside {r['h'][1]:.1f}, edge {r['h'][2]:.1f} W/m2K; legs+links {r['p_leak']:.2f} W")
    pl = Plant(h.r20)
    print(f"heat capacity {pl.heat_capacity():.1f} J/K")
    for v in (20.0, 15.0, 12.0, 9.0, 5.0):
        t99, teq = warmup(h, v, 900.0 if v < 15 else 400.0)
        print(f"  {v:4.0f} V: 25 -> 99 C in " + (f"{t99:5.0f} s" if t99 else "   never") + f", full-duty equilibrium {teq:5.0f} C")
    if plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axs = plt.subplots(1, 2, figsize=(11, 4.8), dpi=110)
        for ax, (name, r) in zip(axs, res.items()):
            im = ax.imshow(r["T"], origin="lower", cmap="inferno", vmin=86, vmax=104,
                           extent=[-G.HALF, G.HALF, -G.HALF, G.HALF])
            ax.contour(r["X"], r["Y"], r["T"], levels=[95, 97, 99], colors="w", linewidths=0.5)
            ax.set_title(f"{name}: {r['P']:.1f} W, {r['all'][0]:.0f}..{r['all'][1]:.0f} C", fontsize=9)
            ax.set_xlabel("x [mm] (top view, tail at the bottom)")
            fig.colorbar(im, ax=ax, shrink=0.85, label="C")
        fig.suptitle("Heater zone surface temperature, sensor held at 100 C (contours 95 / 97 / 99 C)")
        fig.tight_layout()
        fig.savefig(os.path.join(out, "evenness.png"))
        print("plot:", os.path.join(out, "evenness.png"))
    return res


def tune():
    best = None
    for edge_e in (0.20, 0.30, 0.40):
        for edge_L in (4.0, 7.0):
            for end_f in (0.70, 0.78, 0.86):
                for end_L in (5.0, 8.0):
                    p = H.Params(edge_e=edge_e, edge_L=edge_L, end_f=end_f, end_L=end_L)
                    try:
                        h = H.design(p)
                    except (RuntimeError, ValueError):
                        continue
                    r = steady(h)
                    spread = r["inner"][1] - r["inner"][0]
                    score = spread + 0.3 * (r["all"][1] - r["all"][0])
                    print(f"edge {edge_e:.2f}/{edge_L:.0f}  end {end_f:.2f}/{end_L:.0f}  n {h.n}  wmin {min(h.ws) * end_f:.3f}  "
                          f"inner {r['inner'][0]:5.1f}..{r['inner'][1]:5.1f}  all {r['all'][0]:5.1f}..{r['all'][1]:5.1f}  score {score:.2f}",
                          flush=True)
                    if best is None or score < best[0]:
                        best = (score, p)
    print("best:", best[1])


if __name__ == "__main__":
    if "--tune" in sys.argv:
        tune()
    else:
        report(H.design())
