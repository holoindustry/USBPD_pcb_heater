#!/usr/bin/env python3
"""Control simulation on the 1-D plant model of calc/thermal.py.

Analog variant: the thermostat and limiter thresholds are computed from the actual resistor
values (NTC pull-up, reference divider with the set-point pot, hysteresis resistor), then
simulated as on/off control.
STM32 variant: PI control with ideal PWM, on the NTC alone and on the heater-resistance
reading corrected slowly by the NTC.

analog_design() is also imported by gen/circuits.py, so the schematic uses the same values.

Run:  python3 calc/control_sim.py        table + calc/out/control.png
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "gen"))
sys.path.insert(0, HERE)

import heater as H  # noqa: E402
import parts as P  # noqa: E402
import thermal as TH  # noqa: E402

VDD = 3.3
T_SET = 100.0
R_PULL = 22e3           # pull-up on the comparator output nodes (R12, R13)
V_OL = 0.1              # comparator output low level

# The fitted resistors of the analog variant are JLCPCB basic parts (3.3k, 4.7k, 22k, 68k)
# and one 3M, a "preferred" extended part that carries no fee.
#                    NTC pull-up, reference top, reference bottom, feedback to the NTC node
THERMOSTAT = (68e3, 4.7e3, 3.3e3, 3e6)    # R3, R6, R7, R10; the pot RV1 is in series with R6
LIMITER = (22e3, 22e3, 3.3e3, 68e3)       # R5, R8, R9, R11
# RV1 is wired as a variable resistor between +3V3 and R6: 0 ohm is the coldest setting, the
# full 50k the hottest. Only the ratio R6 : R7 : RV1 matters (the feedback goes to the NTC node),
# so another pot value works with R6 = 0.094 x and R7 = 0.066 x the pot. R6 = 4.7k shares a BOM
# line with the LED resistor R4; 6.2k would give 50 to 122 C instead of 43 to 121 C. With 4.7k
# REF1 is 1.36 V at the coldest end: above the 1.3 V input range the LM393 guarantees over
# temperature (VCC - 2 V) for the last 1 % of travel, inside its 25 C range (VCC - 1.5 V).
POT = 50e3
POT_TOL = 0.10          # 3362P-1-503


def _trip_r(r_pu, r_top, r_bot, r_h, out_high):
    """NTC resistance at which the NTC node equals the reference, for one output state."""
    v_ref = VDD * r_bot / (r_top + r_bot)
    vg, rh = (VDD, r_h + R_PULL) if out_high else (V_OL, r_h)
    return v_ref / ((VDD - v_ref) / r_pu + (vg - v_ref) / rh)


def thresholds(r_pu, r_top, r_bot, r_h):
    """(temperature where the output goes low, temperature where it is released again)."""
    return P.ntc_t(_trip_r(r_pu, r_top, r_bot, r_h, True)), P.ntc_t(_trip_r(r_pu, r_top, r_bot, r_h, False))


def tolerance(vals, tol_r=0.01, tol_ntc=0.01, tol_b=0.01):
    """Worst-case shift of the upper threshold in K: 1 % resistors, NTC 1 % at 25 C and 1 % on B."""
    r_pu, r_top, r_bot, r_h = vals
    nom = _trip_r(r_pu, r_top, r_bot, r_h, True)
    lo = _trip_r(r_pu * (1 - tol_r), r_top * (1 + tol_r), r_bot * (1 - tol_r), r_h, True)
    hi = _trip_r(r_pu * (1 + tol_r), r_top * (1 - tol_r), r_bot * (1 + tol_r), r_h, True)

    def t_of(r, k_r, k_b):
        return 1 / (1 / 298.15 + math.log(r / (P.NTC_R25 * k_r)) / (P.NTC_B * k_b)) - 273.15
    t0 = t_of(nom, 1, 1)
    ts = [t_of(r, kr, kb) for r in (lo, hi) for kr in (1 - tol_ntc, 1 + tol_ntc) for kb in (1 - tol_b, 1 + tol_b)]
    return min(ts) - t0, max(ts) - t0


def thermostat(x, pot=POT):
    """(off, on) temperature of the thermostat with the pot at fraction x of its travel (0 = coldest)."""
    r_pu, r_top, r_bot, r_h = THERMOSTAT
    return thresholds(r_pu, r_top + x * pot, r_bot, r_h)


def pot_for(t_off):
    """Pot position (0..1) at which the heater switches off at t_off."""
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if thermostat(mid)[0] < t_off else (lo, mid)
    return (lo + hi) / 2


def scale(steps=(0.0, 0.25, 0.5, 0.75, 1.0)):
    """[(pot position, off temperature, on temperature, reference voltage)] over the pot travel."""
    _, r_top, r_bot, _ = THERMOSTAT
    return [(x, *thermostat(x), VDD * r_bot / (r_top + x * POT + r_bot)) for x in steps]


def analog_design(x=None):
    """Resistor values and the resulting switching temperatures. x is the pot position, 0..1;
    None stands for the position that switches off at T_SET."""
    if x is None:
        x = pot_for(T_SET)
    t_off, t_on = thermostat(x)
    t_trip, t_reset = thresholds(*LIMITER)
    return dict(r_pull=R_PULL, r_pu1=THERMOSTAT[0], r_top1=THERMOSTAT[1], r_set=THERMOSTAT[2], r_h1=THERMOSTAT[3],
                r_pot=POT, pot_x=x, t_min=thermostat(0.0)[0], t_max=thermostat(1.0)[0],
                r_pu2=LIMITER[0], r_top2=LIMITER[1], r_lim=LIMITER[2], r_h2=LIMITER[3],
                t_on=t_on, t_off=t_off, t_trip=t_trip, t_reset=t_reset,
                v_ref1=VDD * THERMOSTAT[2] / (THERMOSTAT[1] + x * POT + THERMOSTAT[2]),
                v_ref2=VDD * LIMITER[2] / (LIMITER[1] + LIMITER[2]))


def sim_analog(h, d, volts=20.0, t_end=300.0, load_at=None, load_h=30.0, fet_short=False, rt1_open=False):
    pl = TH.Plant(h.r20)
    heat, tripped, vbus, t_v = True, False, volts, 0.0
    log, t = [], 0.0
    while t < t_end:
        if load_at is not None and t >= load_at:
            pl.h_extra_top = load_h
        ts = pl.t_sensor
        if rt1_open:
            heat = True
        elif heat and ts > d["t_off"]:
            heat = False
        elif not heat and ts < d["t_on"]:
            heat = True
        if not tripped and ts > d["t_trip"]:
            tripped, t_v = True, t
        elif tripped and ts < d["t_reset"]:
            tripped, t_v = False, t
        # the PD chip follows the limiter with ~0.3 s delay
        if t - t_v > 0.3:
            vbus = 5.0 if tripped else volts
        on = fet_short or (heat and not tripped)
        pl.step(vbus ** 2 / pl.r_heater() if on else 0.0, TH.DT)
        t += TH.DT
        log.append((t, pl.t_top, pl.t_bottom, ts, 1.0 if on else 0.0, vbus))
    return log


def sim_pi(h, volts=20.0, t_end=300.0, load_at=None, load_h=30.0, use_r=True, kp=0.25, ki=0.012):
    pl = TH.Plant(h.r20)
    integ, offs = 0.0, 0.0
    log, t = [], 0.0
    while t < t_end:
        if load_at is not None and t >= load_at:
            pl.h_extra_top = load_h
        if use_r:                                   # trace temperature, pulled slowly towards the NTC
            est = pl.t_top + offs
            offs += (pl.t_sensor - est) / 20.0 * TH.DT
        else:
            est = pl.t_sensor
        e = T_SET - est
        u = kp * e + integ
        duty = min(1.0, max(0.0, u))
        if 0.0 < u < 1.0 or (u >= 1.0 and e < 0) or (u <= 0.0 and e > 0):
            integ += ki * e * TH.DT
        pl.step(duty * volts ** 2 / pl.r_heater(), TH.DT)
        t += TH.DT
        log.append((t, pl.t_top, pl.t_bottom, pl.t_sensor, duty, volts))
    return log


def stats(log, t_from, t_to):
    seg = [r for r in log if t_from <= r[0] <= t_to]
    top = [r[1] for r in seg]
    edges = sum(1 for a, b in zip(seg, seg[1:]) if a[4] != b[4] and (a[4] in (0.0, 1.0)) and (b[4] in (0.0, 1.0)))
    period = 2 * (t_to - t_from) / edges if edges > 1 else 0.0
    return min(top), max(top), sum(r[4] for r in seg) / len(seg), period


def main():
    h = H.design()
    d = analog_design()
    f = P.fmt_r
    print("Analog variant (NTC 100 k B3950; 3.3k, 4.7k, 22k, 68k, 3M and a 50k pot):")
    print(f"  thermostat: NTC pull-up {f(d['r_pu1'])}, reference ({f(d['r_top1'])} + pot {f(d['r_pot'])}) / {f(d['r_set'])}, "
          f"feedback {f(d['r_h1'])} -> {d['t_min']:.1f} .. {d['t_max']:.1f} C")
    print("  pot travel   off      on     REF1")
    for x, t_off, t_on, v in scale((0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0)):
        print(f"    {x * 100:5.1f} %  {t_off:6.1f}  {t_on:6.1f} C  {v:.3f} V")
    print(f"  hottest setting with the pot {POT_TOL * 100:.0f} % low / high: {thermostat(1.0, POT * (1 - POT_TOL))[0]:.1f} / "
          f"{thermostat(1.0, POT * (1 + POT_TOL))[0]:.1f} C")
    print(f"  simulated below with the pot at {d['pot_x'] * 100:.1f} %: off at {d['t_off']:.1f} C, on at {d['t_on']:.1f} C "
          f"(REF1 {d['v_ref1']:.3f} V)")
    print(f"  limiter:    NTC pull-up {f(d['r_pu2'])}, reference {f(d['r_top2'])} / {f(d['r_lim'])} ({d['v_ref2']:.3f} V), "
          f"feedback {f(d['r_h2'])} -> trips at {d['t_trip']:.1f} C, resets at {d['t_reset']:.1f} C")
    lo, hi = tolerance(LIMITER)
    print(f"  limiter worst case with 1 % resistors and a 1 % / B 1 % NTC: {lo:+.1f} .. {hi:+.1f} K")
    d_max, d_min = analog_design(1.0), analog_design(0.0)
    runs = [
        ("analog 20 V", sim_analog(h, d, load_at=150.0)),
        ("analog 12 V", sim_analog(h, d, volts=12.0, t_end=420.0)),
        ("analog 20 V, switch shorted", sim_analog(h, d, fet_short=True)),
        ("analog 20 V, RT1 open", sim_analog(h, d, rt1_open=True)),
        ("STM32 PI on NTC, 20 V", sim_pi(h, use_r=False, load_at=150.0)),
        ("STM32 PI on trace R + NTC, 20 V", sim_pi(h, use_r=True, load_at=150.0)),
        ("STM32 PI on trace R + NTC, 12 V", sim_pi(h, volts=12.0, t_end=420.0)),
        (f"analog 20 V, pot at maximum ({d_max['t_off']:.0f} C)", sim_analog(h, d_max, t_end=420.0)),
        (f"analog 15 V, pot at maximum ({d_max['t_off']:.0f} C)", sim_analog(h, d_max, volts=15.0, t_end=420.0)),
        (f"analog 20 V, pot at minimum ({d_min['t_off']:.0f} C)", sim_analog(h, d_min, t_end=420.0)),
        ("analog 20 V, maximum, switch shorted", sim_analog(h, d_max, fet_short=True, t_end=420.0)),
        ("analog 20 V, maximum, RT1 open", sim_analog(h, d_max, rt1_open=True, t_end=420.0)),
    ]
    print(f"\n{'run':38s} {'99 C at':>8s} {'peak':>6s}  {'top copper, settled':>20s} {'duty':>5s} {'period':>7s}   after load (+30 W/m2K at 150 s)")
    for name, log in runs:
        t99 = next((r[0] for r in log if r[1] >= 99.0), None)
        peak = max(r[1] for r in log)
        end = log[-1][0]
        loaded = end < 301 and "short" not in name and "open" not in name
        a0, a1 = (100.0, 148.0) if loaded else (end - 60, end)
        lo, hi, duty, per = stats(log, a0, a1)
        line = (f"{name:38s} {(f'{t99:.0f} s' if t99 else 'never'):>8s} {peak:6.1f}  {lo:8.1f} .. {hi:5.1f} C  {duty * 100:4.0f}% "
                f"{(f'{per:.1f} s' if per else '-'):>7s}")
        if loaded:
            lo2, hi2, duty2, _ = stats(log, 240.0, 298.0)
            dip = min(r[1] for r in log if 150.0 <= r[0] <= 200.0)
            line += f"   dip to {dip:.1f}, then {lo2:.1f} .. {hi2:.1f} C at {duty2 * 100:.0f}%"
        print(line)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, axs = plt.subplots(2, 2, figsize=(12, 7), dpi=110, sharey=False)
    for ax, k in zip(axs.ravel(), (0, 5, 2, 1)):
        name, log = runs[k]
        ts = [r[0] for r in log[::25]]
        ax.plot(ts, [r[1] for r in log[::25]], label="top copper", lw=1.0)
        ax.plot(ts, [r[3] for r in log[::25]], label="NTC", lw=1.0)
        ax.plot(ts, [r[2] for r in log[::25]], label="underside", lw=1.0)
        ax.axhline(T_SET, color="k", lw=0.5, ls=":")
        ax.set_title(name, fontsize=9)
        ax.set_xlabel("s")
        ax.set_ylabel("C")
        ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    out = os.path.join(HERE, "out", "control.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out)
    print("plot:", out)


if __name__ == "__main__":
    main()
