#!/usr/bin/env python3
"""Simulation schematics of the analog heater for KiCad's built-in SPICE simulator (ngspice).

    python3 sim/make_sim.py            write the projects below (refuses to overwrite)
    python3 sim/make_sim.py --force    overwrite existing schematics, losing edits made in KiCad
    python3 sim/make_sim.py --check    also run them in ngspice and print the key figures
    python3 sim/make_sim.py manual --force     one project only (manual, loop or thresholds)

Three KiCad projects, all drawn from the same control circuit with the board's references:

  sim/manual      the control circuit alone, with stock models only: the two NTCs are trimmers
                  turned by hand in the simulator, like the set-point trimmer. No plate, no PD
                  chip, no regulator.
  sim/loop        closed loop: the control circuit heats a thermal model of the plate
                  (the numbers of calc/thermal.py as an electrical network)
  sim/thresholds  open loop: the plate temperature is a slow ramp, 10 C per second up to
                  150 C and down again, to read the switching points

Parts that are not on the board have references from 101 up. Resistor values come from
calc/control_sim.py; in loop and thresholds so do the NTC law and the plate (calc/thermal.py).
The models are in sim/models/: stock.lib for manual, heater_sim.lib for the other two.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(ROOT, "gen"))

import circuits  # noqa: E402,F401  (puts calc/ and the sibling toolkit on the path)
import heater as H  # noqa: E402
import parts as P  # noqa: E402
import schematic as SC  # noqa: E402
import sheets  # noqa: E402
import thermal as TH  # noqa: E402
from control_sim import LIMITER, POT, T_SET, THERMOSTAT, _trip_r, analog_design, pot_for  # noqa: E402
from eda.circuit import Circuit  # noqa: E402

LIB = "../models/heater_sim.lib"
STOCK = "../models/stock.lib"        # sim/manual: an unchanged LM393 macromodel and a level-1 MOSFET
NTC_POT = 100e3                      # sim/manual: the NTCs as trimmers, 100 k = the NTC at 25 C
RAMP = (15.0, 150.0)                 # thresholds: seconds up, top temperature (10 C per second)

# The plate as an electrical network: 1 V = 1 C and 1 uA = 1 W, so 1 Mohm = 1 K/W and 1 uF = 1 J/K.
# (With 1 A = 1 W the capacitors would be farads and the resistors milliohms, far from every
# other value in the circuit; microfarads and megohms keep the solver's matrix evenly scaled.)
# losses of the plate to the air, uA/K (= W/K) as a function of d = T_top - T_amb (fit of
# thermal.coeffs() between 26 and 200 C at 25 C ambient; top within 0.2 %, underside within 4 %)
G_TOP = "1u*(0.0189984*pow(d,0.25) + 0.0260752 + 9.29075e-05*d + 3.68032e-07*d*d)"
G_BOT = "1u*(0.00897928*pow(d,0.25) + 0.0136391 + 1.49858e-05*d + 2.90869e-08*d*d)"


def fmt(v):
    return f"{v:.4g}"


def make(variant):
    """The circuit of one simulation project: 'loop' or 'thresholds'."""
    d = analog_design()
    h = H.design()
    pl = TH.Plant(h.r20)
    f = P.fmt_r
    c = Circuit(variant, title=f"USB-C PCB heater, analog controller: simulation ({variant})", rev=circuits.REV,
                paper="A3", company="pcb_heater / poc_fable")
    t_plate = "V(/T_TOP)" if variant == "loop" else "V(/T_NTC)"
    # (the clamp keeps the resistance positive while the solver looks for the operating point)
    r_htr = f"{h.r20:.3f}*(1+{H.ALPHA_CU}*(max({t_plate},-50)-20))"

    def R(ref, val, a, b, **kw):
        c.add(ref, "Device:R", val, "", {"1": a, "2": b}, **kw)

    def C(ref, val, a, b):
        c.add(ref, "Device:C", val, "", {"1": a, "2": b})

    def B(ref, name, expr, p, n):
        """Behavioural source: 'v=...' between p (+) and n, or 'i=...' flowing from p through the source to n."""
        c.add(ref, "Simulation_SPICE:BSOURCE", name, "", {"1": p, "2": n},
              **{"Sim.Device": "SPICE", "Sim.Params": f'type="B" model="{expr}"'})

    def V(ref, val, p, kind="DC", params=None):
        c.add(ref, "Simulation_SPICE:VDC" if kind == "DC" else "Simulation_SPICE:VPWL", str(val), "", {"1": p, "2": "GND"},
              **{"Sim.Device": "V", "Sim.Type": kind, "Sim.Params": params or f"dc={val}", "Sim.Pins": "1=+ 2=-"})

    def ntc(ref, net):
        c.add(ref, "Device:Thermistor_NTC", "100k B3950", "", {"1": net, "2": "GND"},
              **{"Sim.Device": "R", "Sim.Type": "=",
                 "Sim.Params": f"r='{P.NTC_R25:.0f}*exp({P.NTC_B:.0f}*(1/(V(/T_NTC)+273.15)-1/298.15))'"})

    # ------------------------------------------------------------ supply and charger stand-ins
    V("V102", 3.3, "+3V3")                                           # the regulator U2
    V("V101", 20, "VCHG")                                            # what the charger gives the PD chip
    # PD chip: 5 V while VSET is held low, followed with a lag of 0.1 s (R106, C106) and without a
    # hard step. VBUS comes up within the first millisecond, so the run starts from an operating
    # point without heater power: the plate at room temperature.
    B("B101", "VBUS", "v=min(time/1m,1)*(5+(V(/VCHG)-5)*0.5*(1+tanh((V(/VSET_D)-1)/0.1)))", "VBUS", "GND")
    R("R102", "100k", "+3V3", "VSET")                                # stands for the VSET pin of U1
    R("R106", "10M", "VSET", "VSET_D")
    C("C106", "10n", "VSET_D", "GND")
    for i, net in enumerate(("+3V3", "VBUS", "GND")):
        c.add(f"#FLG0{i + 1}", "power:PWR_FLAG", "PWR_FLAG", "", {"1": net}, in_bom=False)

    # ------------------------------------------------------------ the control circuit of the board
    for ref, a, b in (("U3", ("NTC1", "REF1", "GATE_OC"), ("LIM_N", "REF2", "GATE_OC")),
                      ("U4", ("NTC2", "REF2", "LIM_N"), ("LIM_N", "REF2", "VSET"))):
        c.add(ref, "Comparator:LM393", "LM393", "",
              {"3": a[0], "2": a[1], "1": a[2], "5": b[0], "6": b[1], "7": b[2], "8": "+3V3", "4": "GND"},
              **{"Sim.Device": "SUBCKT", "Sim.Library": LIB, "Sim.Name": "LM393_DUAL",
                 "Sim.Pins": "1=outa 2=inan 3=inap 4=vee 5=inbp 6=inbn 7=outb 8=vcc"})
    R("R3", f(d["r_pu1"]), "+3V3", "NTC1")
    ntc("RT1", "NTC1")
    C("C4", "100n", "NTC1", "GND")
    c.add("RV1", "Device:R_Potentiometer", f(d["r_pot"]), "", {"1": "+3V3", "2": "TSET", "3": "TSET"},
          **{"Sim.Device": "R", "Sim.Type": "POT", "Sim.Pins": "1=r0 2=wiper 3=r1",
             "Sim.Params": f"r={POT:.0f} pos={pot_for(T_SET):.3f}"})
    R("R6", f(d["r_top1"]), "TSET", "REF1")
    R("R7", f(d["r_set"]), "REF1", "GND")
    R("R10", f(d["r_h1"]), "GATE_OC", "NTC1")
    R("R12", f(d["r_pull"]), "+3V3", "GATE_OC")
    R("R5", f(d["r_pu2"]), "+3V3", "NTC2")
    ntc("RT2", "NTC2")
    C("C6", "100n", "NTC2", "GND")
    R("R8", f(d["r_top2"]), "+3V3", "REF2")
    R("R9", f(d["r_lim"]), "REF2", "GND")
    R("R11", f(d["r_h2"]), "LIM_N", "NTC2")
    R("R13", f(d["r_pull"]), "+3V3", "LIM_N")
    R("R2", "22k", "GATE_OC", "GATE")
    c.add("Q1", "Transistor_FET:AO3400A", "AO3400A", "", {"G": "GATE", "S": "GND", "D": "HTR_N"},
          **{"Sim.Device": "NMOS", "Sim.Type": "VDMOS", "Sim.Library": LIB, "Sim.Name": "AO3400A", "Sim.Pins": "1=G 2=S 3=D"})
    c.add("HTR1", "Device:Heater", "heater 9R", "", {"1": "VBUS", "2": "HTR_N"},
          **{"Sim.Device": "R", "Sim.Type": "=", "Sim.Params": f"r='{r_htr}'"})
    R("R4", "4.7k", "LED_K", "HTR_N")
    c.add("D1", "Device:LED", "yellow", "", {"A": "VBUS", "K": "LED_K"},
          **{"Sim.Device": "D", "Sim.Library": LIB, "Sim.Name": "LED_YELLOW", "Sim.Pins": "1=K 2=A"})
    R("R105", "1G", "HTR_N", "GND")                                  # 0.01: the switch failed short

    # ------------------------------------------------------------ plate
    if variant == "loop":
        a = pl.area
        g = TH.K_FR4_Z / pl.dz * a                                   # W/K between two FR-4 slices
        dv = "(V(VBUS)-V(/HTR_N))"
        B("B102", "heater power", f"i=1u*{dv}*{dv}/({r_htr})", "GND", "T_TOP")
        dd = "max(V(/T_TOP)-V(/T_AMB),1)"
        B("B103", "loss top", "i=" + G_TOP.replace("d", dd) + "*(V(/T_TOP)-V(/T_AMB))", "T_TOP", "T_AMB")
        B("B104", "loss underside", "i=" + G_BOT.replace("d", dd) + "*(V(/T_BOT)-V(/T_AMB))", "T_BOT", "T_AMB")
        R("R103", "1000G", "T_AMB", "T_TOP")                         # an object on the plate: 1 / (h A), 1M = 1 K/W
        V("V103", fmt(TH.T_AMB), "T_AMB")
        nodes = ["T_TOP"] + [f"TS{i}" for i in range(1, pl.n + 1)] + ["T_BOT"]
        caps = [pl.c_top * a] + [pl.c_slice * a] * pl.n + [pl.c_bot * a]
        for k, (node, cap) in enumerate(zip(nodes, caps)):
            C(f"C{110 + k}", fmt(cap) + "u", node, "GND")
        for k in range(pl.n + 1):
            R(f"R{111 + k}", fmt(1e3 / (2 * g) if k in (0, pl.n) else 1e3 / g) + "k", nodes[k], nodes[k + 1])
        B("B105", "sensor", f"v={pl.w_top}*V(/T_TOP)+{1 - pl.w_top:.1f}*V(/T_BOT)", "T_MIX", "GND")
        R("R104", "1M", "T_MIX", "T_NTC")
        C("C104", fmt(pl.tau_s) + "u", "T_NTC", "GND")
    else:
        up, top = RAMP
        V("V103", "ramp", "T_NTC", kind="PWL", params=f'pwl="0 0 {up:g} {top:g} {2 * up:g} 0"')
    return c, d, pl


def gnd(s, *pins):
    for p in pins:
        s.pwr("GND", p)


def draw(c, variant, d, pl, lib):
    s = SC.Sheet(c, lib, "A3")

    # ---------------------------------------------------------------- supply and charger
    s.box(12, 14, 114, 77, "Supply and charger (stand-ins)")
    for ref, x, net in (("V102", 24, "+3V3"), ("B101", 68, "VBUS")):
        s.sym(ref, x, 42)
        s.wire(f"{ref}.1", (None, 32))
        s.pwr(net, (x, 32))
        gnd(s, f"{ref}.2")
    s.sym("#FLG01", 30, 34)
    s.wire((24, 34), (30, None))
    s.sym("#FLG02", 74, 34)
    s.wire((68, 34), (74, None))
    s.sym("V101", 46, 42)
    s.wire("V101.1", (None, 34))
    s.label("VCHG", (46, 34))
    gnd(s, "V101.2")
    s.sym("#FLG03", 18, 46)
    s.wire("V102.2", (18, None))
    for ref, x in (("U3", 90), ("U4", 102)):
        s.sym(ref, x, 42, unit=3)
        s.pwr("+3V3", f"{ref}.8")
        gnd(s, f"{ref}.4")
    s.text("V102 stands for the 3.3 V regulator U2. B101 stands for the charger and the PD chip U1:\n"
           "VBUS is V101 (20, 15 or 12 V) while VSET is high, and 5 V while the limiter holds VSET low.\n"
           "It follows VSET about 0.1 s late (R106, C106); the real chip's delay is not specified.\n"
           "VBUS rises during the first millisecond of a run.", 14, 63)

    # ---------------------------------------------------------------- over-temperature limiter
    xs, xc, xb, xd, xu, xf, xp, xl, xr, xo = 24, 42, 58, 68, 76, 86, 94, 104, 110, 120
    y = 110
    s.box(12, 82, 150, y + 23, "Over-temperature limiter (second sensor)")
    s.sym("R5", xs, y - 16)
    s.sym("RT2", xs, y - 4)
    s.sym("C6", xc, y - 4)
    s.pwr("+3V3", "R5.1")
    gnd(s, "RT2.2", "C6.2")
    s.wire("R5.2", "RT2.1")
    s.sym("R11", xu, y - 10, rot=270)
    s.wire((xs, y - 10), "R11.2")
    s.wire((xc, y - 10), "C6.1")
    s.sym("U4", xu, y, unit=1)
    s.wire((xd, y - 10), (None, "U4.3"), "U4.3")
    s.sym("R8", xb, y - 2)
    s.sym("R9", xb, y + 6)
    s.pwr("+3V3", "R8.1")
    gnd(s, "R9.2")
    s.wire("R8.2", "R9.1")
    s.wire((xb, y + 2), "U4.2")
    s.sym("U4", xo, y + 2, unit=2, val=False)
    s.sym("U3", xo, y + 16, unit=2, val=False)
    # REF2 is also the threshold of the two limiter outputs
    s.wire((xb + 6, y + 2), (None, y + 10), (xr, None), (None, "U4.6"), "U4.6")
    s.wire("U3.6", (xr, None), (None, y + 10))
    s.wire("U4.1", "U4.5")
    s.wire("R11.1", (xf, None), (None, y))
    s.sym("R13", xp, y - 7)
    s.pwr("+3V3", "R13.1")
    s.wire("R13.2", (None, y))
    s.wire((xl, y), (None, "U3.5"), "U3.5")
    s.label("NTC2", (xs + 4, y - 10))
    s.label("REF2", (xb + 4, y + 2))
    s.label("LIM_N", (xp + 2, y))
    s.sym("R102", 130, y - 6)
    s.pwr("+3V3", "R102.1")
    s.wire("U4.7", (130, None), "R102.2")
    s.label("VSET", (126, y + 2))
    s.sym("R106", 136, y + 2, rot=90)                    # lag of the PD chip stand-in
    s.wire((130, y + 2), "R106.1")
    s.sym("C106", 139, y + 8)
    s.wire("R106.2", "C106.1")
    gnd(s, "C106.2")
    s.label("VSET_D", (139, y + 4))
    s.text(sheets.LIMITER_NOTE.format(**d), 14, y + 15.5)

    # ---------------------------------------------------------------- thermostat
    y = 158
    s.box(12, 141, xo + 12, y + 26, "Thermostat")
    s.sym("U3", xu, y, unit=1, mirror="x")
    s.sym("R6", xb, y - 6)
    s.sym("R7", xb, y + 2)
    s.sym("RV1", xb - 8, y - 11, rot=90, ref_at=(0, 2, "c"), val_at=(0, 4, "c"))
    s.pwr("+3V3", (xb - 14, y - 11))
    s.wire((xb - 14, y - 11), "RV1.1")
    s.wire("RV1.3", (xb, None), "R6.1")
    s.wire("RV1.2", (xb - 3, None), (None, y - 11))
    gnd(s, "R7.2")
    s.wire("R6.2", "R7.1")
    s.wire((xb, y - 2), "U3.2")
    s.sym("R3", xs, y + 6)
    s.sym("RT1", xs, y + 18)
    s.sym("C4", xc, y + 18)
    s.pwr("+3V3", "R3.1")
    gnd(s, "RT1.2", "C4.2")
    s.wire("R3.2", "RT1.1")
    s.sym("R10", xu, y + 12, rot=270)
    s.wire((xs, y + 12), "R10.2")
    s.wire((xc, y + 12), "C4.1")
    s.wire((xd, y + 12), (None, "U3.3"), "U3.3")
    s.wire("R10.1", (xf, None), (None, y))
    s.sym("R12", xp, y - 7)
    s.pwr("+3V3", "R12.1")
    s.wire("R12.2", (None, y))
    s.label("NTC1", (xs + 4, y + 12))
    s.label("REF1", (xb + 2, y - 2))
    s.label("GATE_OC", (xp + 2, y))
    s.text(sheets.THERMOSTAT_NOTE.format(**d) + "\nRV1's position (pos, 0 to 1) is the trimmer's travel: "
           f"{d['pot_x']:.3f} is {d['t_off']:.0f} °C.", xb - 2, y + 17.5)

    # ---------------------------------------------------------------- heater and switch
    x = xo + 32
    s.box(x, y - 37, x + 72, y + 26, "Heater and switch")
    s.sym("R2", x + 8, y, rot=90)
    s.wire("U3.1", "R2.1")
    s.wire("U3.7", (x - 6, None), (None, y))
    s.sym("Q1", x + 34, y)
    s.wire("R2.2", "Q1.G")
    s.label("GATE", (x + 13, y))
    s.sym("HTR1", x + 36, y - 18)
    s.wire("HTR1.2", "Q1.D")
    s.wire("HTR1.1", (None, y - 30))
    s.pwr("VBUS", (x + 36, y - 30))
    s.sym("D1", x + 52, y - 22, rot=90)
    s.sym("R4", x + 52, y - 12)
    s.wire((x + 36, y - 27), ("D1.A", None), "D1.A")
    s.wire("D1.K", "R4.1")
    s.wire("R4.2", (None, y - 7), (x + 36, None))
    s.sym("R105", x + 62, y - 1)
    s.wire((x + 52, y - 7), (x + 62, None), "R105.1")
    gnd(s, "R105.2")
    s.label("HTR_N", (x + 38, y - 7))
    s.wire("Q1.S", (None, y + 7))
    gnd(s, (x + 36, y + 7))
    s.text("HTR1 is the heater trace: 9.0 Ω at 20 °C, rising with the plate temperature.\n"
           "R2 and the gate charge of Q1 set the switching edges.\n"
           "R105 = 0.01 makes Q1 a failed, shorted switch (1G: no fault).", x + 2, y + 13.5)

    # ---------------------------------------------------------------- plate
    if variant == "loop":
        s.box(126, 14, 318, 77, "Plate (thermal model)")
        yl, yr, yg, x0 = 36, 22, 48, 164
        xn = [x0 + 12 * k for k in range(pl.n + 2)]
        for k, xk in enumerate(xn):
            s.sym(f"C{110 + k}", xk, yl + 6)
            s.wire((xk, yl), f"C{110 + k}.1")
            s.wire(f"C{110 + k}.2", (None, yg))
        for k in range(pl.n + 1):
            s.sym(f"R{111 + k}", xn[k] + 6, yl, rot=90)
            s.wire((xn[k], yl), f"R{111 + k}.1")
            s.wire(f"R{111 + k}.2", (xn[k + 1], yl))
        s.wire((xn[0], yg), (xn[-1], yg))
        gnd(s, (xn[4] + 6, yg))
        # top copper: power in, losses to the air, an object
        s.sym("R103", 134, 29)
        s.sym("B103", 144, 32, rot=180, ref_at=(3, -1, "l"), val_at=(3, 1, "l"))
        s.sym("B102", 154, 40, rot=180, ref_at=(-3, 1, "r"), val_at=(-3, 3, "r"))
        s.wire("R103.2", (None, yl), (xn[0], None))
        s.wire("R103.1", (None, yr))
        s.wire("B103.2", (None, yr))
        gnd(s, "B102.1")
        s.label("T_TOP", (157, yl))
        # underside copper
        xb4, xv = xn[-1] + 12, xn[-1] + 28
        s.sym("B104", xb4, 32, rot=180, ref_at=(3, -1, "l"), val_at=(3, 1, "l"))
        s.wire((xn[-1], yl), "B104.1")
        s.wire("B104.2", (None, yr))
        s.label("T_BOT", (xn[-1] + 2, yl))
        s.sym("V103", xv, 30)
        s.wire("V103.1", (None, yr), (134, None))
        gnd(s, "V103.2")
        s.label("T_AMB", (200, yr))
        # sensor
        s.sym("B105", 140, 64, ref_at=(3, -1, "l"), val_at=(3, 1, "l"))
        gnd(s, "B105.2")
        s.sym("R104", 156, 60, rot=90)
        s.wire("B105.1", "R104.1")
        s.label("T_MIX", (141, 60))
        s.sym("C104", 166, 66)
        s.wire("R104.2", (172, None))
        s.wire((166, 60), "C104.1")
        gnd(s, "C104.2")
        s.label("T_NTC", (172, 60))
        s.text("The plate through its thickness as an electrical network: 1 V = 1 °C, 1 µA = 1 W, 1 MΩ = 1 K/W, 1 µF = 1 J/K.\n"
               "C110 is the top copper, C111 to C118 are eight slices of FR-4, C119 the underside copper (calc/thermal.py).\n"
               "B102 feeds in the heater's electrical power. B103 and B104 are the losses to the air at V103, the room.\n"
               "R103 is an object on the plate: 6.8M takes 30 W/m²K more than free air (1000G: nothing).\n"
               "RT1 and RT2 read T_NTC: 70 % top copper, 30 % underside, 0.8 s behind.", 182, 54)
    else:
        s.box(126, 14, 222, 77, "Plate temperature (ramp)")
        s.sym("V103", 140, 42)
        s.wire("V103.1", (None, 34), (146, None))
        s.label("T_NTC", (146, 34))
        gnd(s, "V103.2")
        s.text("V103 is the plate temperature, 1 V = 1 °C:\n"
               f"0 to {RAMP[1]:.0f} °C in {RAMP[0]:.0f} s and back down.\n"
               "On the way up the temperature is 10 × the time,\n"
               f"on the way down 10 × ({2 * RAMP[0]:.0f} s − time).\n"
               "RT1, RT2 and the heater trace follow it.", 152, 38)

    # ---------------------------------------------------------------- simulation
    xt, yt = 230, 84
    s.box(xt - 2, yt - 2, 318, yt + 44, "Simulation")
    s.text(directive(variant), xt, yt + 5)
    if variant == "loop":
        # Gear integration, well damped for the thermal RC ladder; the test runs used it
        s.text(".options method=gear", xt + 30, yt + 5)
        how = ("Inspect > Simulator, then Run. Temperatures are plotted in volts: 100 V is 100 °C.\n"
               "The run starts with the plate at room temperature and the charger plugged in at time 0.\n"
               "With the Tune tool: RV1 turns the trimmer, V101 is the charger voltage, V103 the room\n"
               "temperature. R105 = 0.01 shorts the switch, R103 = 6.8M puts an object on the plate.\n"
               "The comparator model and its limits: sim/models/heater_sim.lib.")
    else:
        how = ("Inspect > Simulator, then Run. The plate temperature is 10 × the time on the way up.\n"
               "GATE high: heater on. LIM_N low: limiter tripped, VBUS falls to 5 V.\n"
               "With the Tune tool: RV1 turns the trimmer, V102 is the 3.3 V rail.\n"
               "The comparator model and its limits: sim/models/heater_sim.lib.")
    s.text(how, xt, yt + 12)
    return s


# ------------------------------------------------------------------------------------ sim/manual
def make_manual():
    """The control circuit alone, with stock models: the NTCs are trimmers turned by hand."""
    d = analog_design()
    h = H.design()
    f = P.fmt_r
    c = Circuit("manual", title="USB-C PCB heater, analog controller: simulation (manual)", rev=circuits.REV,
                paper="A3", company="pcb_heater / poc_fable")

    def R(ref, val, a, b):
        c.add(ref, "Device:R", val, "", {"1": a, "2": b})

    def C(ref, val, a, b, ic):
        c.add(ref, "Device:C", val, "", {"1": a, "2": b}, **{"Sim.Device": "C", "Sim.Params": f"c={val} ic={ic}"})

    def V(ref, val, p):
        c.add(ref, "Simulation_SPICE:VDC", str(val), "", {"1": p, "2": "GND"},
              **{"Sim.Device": "V", "Sim.Type": "DC", "Sim.Params": f"dc={val}", "Sim.Pins": "1=+ 2=-"})

    def pot(ref, ohm, pos, pins):
        c.add(ref, "Device:R_Potentiometer", f(ohm), "", pins,
              **{"Sim.Device": "R", "Sim.Type": "POT", "Sim.Pins": "1=r0 2=wiper 3=r1", "Sim.Params": f"r={ohm:.0f} pos={pos:.3f}"})

    V("V102", 3.3, "+3V3")
    V("V101", 20, "VBUS")
    for i, net in enumerate(("+3V3", "VBUS", "GND")):
        c.add(f"#FLG0{i + 1}", "power:PWR_FLAG", "PWR_FLAG", "", {"1": net}, in_bom=False)
    for ref, a, b in (("U3", ("NTC1", "REF1", "GATE_OC"), ("LIM_N", "REF2", "GATE_OC")),
                      ("U4", ("NTC2", "REF2", "LIM_N"), ("LIM_N", "REF2", "VSET"))):
        c.add(ref, "Comparator:LM393", "LM393", "",
              {"3": a[0], "2": a[1], "1": a[2], "5": b[0], "6": b[1], "7": b[2], "8": "+3V3", "4": "GND"},
              **{"Sim.Device": "SUBCKT", "Sim.Library": STOCK, "Sim.Name": "LM393_PACKAGE",
                 "Sim.Pins": "1=outa 2=inan 3=inap 4=vee 5=inbp 6=inbn 7=outb 8=vcc"})
    # the sensors: resistance = position x 100k, wiper tied to the grounded end
    R("R3", f(d["r_pu1"]), "+3V3", "NTC1")
    pot("RT1", NTC_POT, 0.2, {"1": "NTC1", "2": "GND", "3": "GND"})
    C("C4", "100n", "NTC1", "GND", ic=3.3)                           # starts charged: coming from cold
    pot("RV1", POT, pot_for(T_SET), {"1": "+3V3", "2": "TSET", "3": "TSET"})
    R("R6", f(d["r_top1"]), "TSET", "REF1")
    R("R7", f(d["r_set"]), "REF1", "GND")
    R("R10", f(d["r_h1"]), "GATE_OC", "NTC1")
    R("R12", f(d["r_pull"]), "+3V3", "GATE_OC")
    R("R5", f(d["r_pu2"]), "+3V3", "NTC2")
    pot("RT2", NTC_POT, 0.2, {"1": "NTC2", "2": "GND", "3": "GND"})
    C("C6", "100n", "NTC2", "GND", ic=3.3)
    R("R8", f(d["r_top2"]), "+3V3", "REF2")
    R("R9", f(d["r_lim"]), "REF2", "GND")
    R("R11", f(d["r_h2"]), "LIM_N", "NTC2")
    R("R13", f(d["r_pull"]), "+3V3", "LIM_N")
    R("R102", "100k", "+3V3", "VSET")                                # only so that U4B's open collector shows a level
    R("R2", "22k", "GATE_OC", "GATE")
    c.add("Q1", "Transistor_FET:AO3400A", "AO3400A", "", {"G": "GATE", "S": "GND", "D": "HTR_N"},
          **{"Sim.Device": "SUBCKT", "Sim.Library": STOCK, "Sim.Name": "AO3400A_L1", "Sim.Pins": "1=g 2=s 3=d"})
    c.add("HTR1", "Device:Heater", f"{h.r20:.1f}R", "", {"1": "VBUS", "2": "HTR_N"},
          **{"Sim.Device": "R", "Sim.Params": f"r={h.r20:.1f}"})
    return c, d


def ntc_table():
    """Nominal NTC resistance and the trimmer position that stands for it."""
    rows = [(t, P.ntc_r(t)) for t in (25, 43, 60, 80, 90, 100, 110, 121, 127, 138, 150)]
    cells = [f"{t} °C: {r / 1e3:.3g}k ({r / NTC_POT:.3f})" for t, r in rows]
    return ",  ".join(cells[:4]) + ",\n" + ",  ".join(cells[4:8]) + ",\n" + ",  ".join(cells[8:]) + "."


def draw_manual(c, d, lib):
    s = SC.Sheet(c, lib, "A3")
    r_off, r_on = (_trip_r(THERMOSTAT[0], THERMOSTAT[1] + d["pot_x"] * POT, THERMOSTAT[2], THERMOSTAT[3], hi) for hi in (True, False))
    r_trip, r_reset = (_trip_r(*LIMITER, hi) for hi in (True, False))

    # ---------------------------------------------------------------- supplies
    s.box(12, 14, 114, 77, "Supplies")
    for ref, x, net, flag in (("V102", 24, "+3V3", "#FLG01"), ("V101", 46, "VBUS", "#FLG02")):
        s.sym(ref, x, 42)
        s.wire(f"{ref}.1", (None, 32))
        s.pwr(net, (x, 32))
        gnd(s, f"{ref}.2")
        s.sym(flag, x + 6, 34)
        s.wire((x, 34), (x + 6, None))
    s.sym("#FLG03", 18, 46)
    s.wire("V102.2", (18, None))
    for ref, x in (("U3", 90), ("U4", 102)):
        s.sym(ref, x, 42, unit=3)
        s.pwr("+3V3", f"{ref}.8")
        gnd(s, f"{ref}.4")
    s.text("Two plain sources: V102 for the 3.3 V rail, V101 for VBUS.\n"
           "The regulator and the PD chip are not simulated.", 14, 63)

    # ---------------------------------------------------------------- sensors as trimmers
    s.box(126, 14, 318, 77, "The two NTCs as trimmers")
    s.text("RT1 and RT2 stand for the NTCs: resistance = position × 100 kΩ, so turning one down heats that sensor.\n"
           "The NTC's nominal resistance (100 kΩ at 25 °C, B = 3950 K, both ±1 %) and the position for it:\n"
           + ntc_table() + "\n\n"
           f"With RV1 at {d['pot_x']:.3f} the heater switches off below {r_off / 1e3:.2f}k and on again above {r_on / 1e3:.2f}k at RT1;\n"
           f"the limiter trips below {r_trip / 1e3:.2f}k and resets above {r_reset / 1e3:.2f}k at RT2 (from the resistor values alone).", 130, 22)

    # ---------------------------------------------------------------- over-temperature limiter
    xs, xc, xb, xd, xu, xf, xp, xl, xr, xo = 24, 42, 58, 68, 76, 86, 94, 104, 110, 120
    y = 110
    s.box(12, 82, 144, y + 23, "Over-temperature limiter (second sensor)")
    s.sym("R5", xs, y - 16)
    s.sym("RT2", xs, y - 4)
    s.sym("C6", xc, y - 4)
    s.pwr("+3V3", "R5.1")
    s.wire("R5.2", "RT2.1")
    s.wire("RT2.2", (xs + 5, None), (None, "RT2.3"), "RT2.3")
    gnd(s, "RT2.3", "C6.2")
    s.sym("R11", xu, y - 10, rot=270)
    s.wire((xs, y - 10), "R11.2")
    s.wire((xc, y - 10), "C6.1")
    s.sym("U4", xu, y, unit=1)
    s.wire((xd, y - 10), (None, "U4.3"), "U4.3")
    s.sym("R8", xb, y - 2)
    s.sym("R9", xb, y + 6)
    s.pwr("+3V3", "R8.1")
    gnd(s, "R9.2")
    s.wire("R8.2", "R9.1")
    s.wire((xb, y + 2), "U4.2")
    s.sym("U4", xo, y + 2, unit=2, val=False)
    s.sym("U3", xo, y + 16, unit=2, val=False)
    # REF2 is also the threshold of the two limiter outputs
    s.wire((xb + 6, y + 2), (None, y + 10), (xr, None), (None, "U4.6"), "U4.6")
    s.wire("U3.6", (xr, None), (None, y + 10))
    s.wire("U4.1", "U4.5")
    s.wire("R11.1", (xf, None), (None, y))
    s.sym("R13", xp, y - 7)
    s.pwr("+3V3", "R13.1")
    s.wire("R13.2", (None, y))
    s.wire((xl, y), (None, "U3.5"), "U3.5")
    s.label("NTC2", (xs + 4, y - 10))
    s.label("REF2", (xb + 4, y + 2))
    s.label("LIM_N", (xp + 2, y))
    s.sym("R102", 134, y - 6)
    s.pwr("+3V3", "R102.1")
    s.wire("U4.7", (134, None), "R102.2")
    s.label("VSET", (128, y + 2))
    s.text("RT2 too low (too hot): LIM_N goes low and stays low until RT2 is clearly higher again (R11).\n"
           "Then U3B holds the gate low and U4B pulls VSET low. On the board VSET goes to the PD chip;\n"
           "here R102 is only a pull-up so that the output shows a level.", 14, y + 15.5)

    # ---------------------------------------------------------------- thermostat
    y = 158
    s.box(12, 141, xo + 12, y + 26, "Thermostat")
    s.sym("U3", xu, y, unit=1, mirror="x")
    s.sym("R6", xb, y - 6)
    s.sym("R7", xb, y + 2)
    s.sym("RV1", xb - 8, y - 11, rot=90, ref_at=(0, 2, "c"), val_at=(0, 4, "c"))
    s.pwr("+3V3", (xb - 14, y - 11))
    s.wire((xb - 14, y - 11), "RV1.1")
    s.wire("RV1.3", (xb, None), "R6.1")
    s.wire("RV1.2", (xb - 3, None), (None, y - 11))
    gnd(s, "R7.2")
    s.wire("R6.2", "R7.1")
    s.wire((xb, y - 2), "U3.2")
    s.sym("R3", xs, y + 6)
    s.sym("RT1", xs, y + 18)
    s.sym("C4", xc, y + 18)
    s.pwr("+3V3", "R3.1")
    s.wire("R3.2", "RT1.1")
    s.wire("RT1.2", (xs + 5, None), (None, "RT1.3"), "RT1.3")
    gnd(s, "RT1.3", "C4.2")
    s.sym("R10", xu, y + 12, rot=270)
    s.wire((xs, y + 12), "R10.2")
    s.wire((xc, y + 12), "C4.1")
    s.wire((xd, y + 12), (None, "U3.3"), "U3.3")
    s.wire("R10.1", (xf, None), (None, y))
    s.sym("R12", xp, y - 7)
    s.pwr("+3V3", "R12.1")
    s.wire("R12.2", (None, y))
    s.label("NTC1", (xs + 4, y + 12))
    s.label("REF1", (xb + 2, y - 2))
    s.label("GATE_OC", (xp + 2, y))
    s.text("RV1 is the set-point trimmer: position 0 fully anticlockwise (coldest), 1 fully clockwise.\n"
           "Heater on while NTC1 is above REF1; R10 gives the small hysteresis.", xb - 2, y + 17.5)

    # ---------------------------------------------------------------- heater and switch
    x = xo + 26
    s.box(x, y - 37, x + 68, y + 26, "Heater and switch")
    s.sym("R2", x + 8, y, rot=90)
    s.wire("U3.1", "R2.1")
    s.wire("U3.7", (x - 6, None), (None, y))
    s.sym("Q1", x + 34, y)
    s.wire("R2.2", "Q1.G")
    s.label("GATE", (x + 13, y))
    s.sym("HTR1", x + 36, y - 18)
    s.wire("HTR1.2", "Q1.D")
    s.wire("HTR1.1", (None, y - 30))
    s.pwr("VBUS", (x + 36, y - 30))
    s.label("HTR_N", (x + 36, y - 9))
    s.wire("Q1.S", (None, y + 7))
    gnd(s, (x + 36, y + 7))
    s.text("HTR1 is the heater trace as a plain resistor, its value at 20 °C.\n"
           "HTR_N near 0 V: heater on. The heater current is −I(V101).", x + 2, y + 13.5)

    # ---------------------------------------------------------------- simulation
    xt, yt = 224, 84
    s.box(xt - 2, yt - 2, 318, yt + 52, "Simulation")
    s.text(directive("manual"), xt, yt + 5)
    # Gear integration: with the default method the macromodel's open-collector outputs ring
    # between about -0.4 V and 7 V on alternate time steps
    s.text(".options method=gear", xt + 30, yt + 5)
    s.text("Inspect > Simulator, then Run. With the Tune tool turn RT1, RT2 and RV1 (position 0 to 1).\n"
           "For finer steps, type the position (pos) into the part's simulation model.\n"
           "GATE high: heater on. LIM_N low: limiter tripped; GATE and VSET are then low as well.\n\n"
           "Every change runs 40 ms from a fresh start, as if the plate had just been colder: C4 and C6\n"
           "start charged (ic=3.3). The run therefore shows where things switch while warming up.\n"
           "With ic=0 on C4 and C6 it shows where they switch back while cooling down.\n\n"
           "Models (sim/models/stock.lib): an LM393 macromodel, unchanged, and a level-1 MOSFET\n"
           "with data-sheet values. Everything else is KiCad's own R, C, trimmer and source.", xt, yt + 12)
    return s


def manual_run(text, pos1, pos2, ic, folder):
    """Final GATE, LIM_N, VSET and HTR_N of the exported netlist with the sensor trimmers at pos1 / pos2."""
    t, n = re.subn(r"(\.model __RT1 potentiometer\( r=\S+ position=)\S+", rf"\g<1>{pos1:.6f}", text)
    t, k = re.subn(r"(\.model __RT2 potentiometer\( r=\S+ position=)\S+", rf"\g<1>{pos2:.6f}", t)
    assert n == 1 and k == 1, "trimmer models not found in the netlist"
    t = t.replace("ic=3.3", f"ic={ic}")
    ctl = (".control\nrun\nlet k = length(time) - 1\nlet g = v(/gate)[k]\nlet l = v(/lim_n)[k]\nlet s = v(/vset)[k]\nlet h = v(/htr_n)[k]\n"
           "let j = abs(v(/vset)[k] - v(/vset)[k-1]) + abs(v(/gate_oc)[k] - v(/gate_oc)[k-1])\necho RESULT $&g $&l $&s $&h $&j\n.endc\n")
    run = os.path.join(folder, "manual_run.cir")
    with open(run, "w") as fh:
        fh.write(re.sub(r"\n\.end\s*$", "\n", t) + ctl + ".end\n")
    r = subprocess.run(["ngspice", "-b", run], capture_output=True, text=True, cwd=folder)
    os.remove(run)
    out = r.stdout + r.stderr
    m = re.search(r"^RESULT (\S+) (\S+) (\S+) (\S+) (\S+)", out, flags=re.M)
    if "Timestep too small" in out or not m:
        raise RuntimeError("ngspice failed:\n" + out[-2000:])
    return [float(v) for v in m.groups()]


def check_manual(folder):
    """Where the outputs switch, found by bisection on the sensor resistance, against the formula."""
    text = open(netlist(folder, "manual")).read()
    d = analog_design()
    want = {("heater", 3.3): _trip_r(THERMOSTAT[0], THERMOSTAT[1] + d["pot_x"] * POT, THERMOSTAT[2], THERMOSTAT[3], True),
            ("heater", 0): _trip_r(THERMOSTAT[0], THERMOSTAT[1] + d["pot_x"] * POT, THERMOSTAT[2], THERMOSTAT[3], False),
            ("limiter", 3.3): _trip_r(*LIMITER, True), ("limiter", 0): _trip_r(*LIMITER, False)}
    cold = manual_run(text, 1.0, 1.0, 3.3, folder)
    hot = manual_run(text, 0.02, 0.02, 3.3, folder)
    print(f"   sensors at 100k: GATE {cold[0]:.2f} V, LIM_N {cold[1]:.2f} V, VSET {cold[2]:.2f} V, HTR_N {cold[3]:.2f} V; "
          f"at 2k: GATE {hot[0]:.2f} V, LIM_N {hot[1]:.2f} V, VSET {hot[2]:.2f} V, HTR_N {hot[3]:.2f} V")
    for (name, ic), r_want in want.items():
        lo, hi = 0.02, 0.5                               # output low at lo, high at hi
        for _ in range(16):
            mid = (lo + hi) / 2
            v = manual_run(text, mid, 0.2 if name == "heater" else mid, ic, folder)
            lo, hi = (lo, mid) if v[0 if name == "heater" else 1] > 1.65 else (mid, hi)
        r_got = (lo + hi) / 2 * NTC_POT
        word = {("heater", 3.3): "heater off below", ("heater", 0): "heater on above", ("limiter", 3.3): "limiter trips below",
                ("limiter", 0): "limiter resets above"}[(name, ic)]
        print(f"   {word} {r_got:.0f} Ω ({P.ntc_t(r_got):.1f} °C nominal); from the resistor values {r_want:.0f} Ω")
    os.remove(os.path.join(folder, "manual.cir"))


def directive(variant):
    return {"loop": ".tran 20m 150 0 20m", "thresholds": f".tran 2m {2 * RAMP[0]:g} 0 5m", "manual": ".tran 20u 40m uic"}[variant]


TRACES = {"loop": ("V(/T_TOP)", "V(/T_NTC)", "V(/T_BOT)"),
          "thresholds": ("V(/GATE)", "V(/LIM_N)", "V(/NTC1)", "V(/REF1)", "V(/NTC2)", "V(/REF2)"),
          "manual": ("V(/GATE)", "V(/LIM_N)", "V(/VSET)", "V(/NTC1)", "V(/REF1)", "V(/NTC2)", "V(/REF2)")}
COLORS = ("rgb(228, 26, 28)", "rgb(55, 126, 184)", "rgb(77, 175, 74)", "rgb(152, 78, 163)", "rgb(255, 127, 0)", "rgb(166, 86, 40)",
          "rgb(102, 102, 102)")


def project_files(folder, variant, root_uuid):
    """.kicad_pro and the simulator workbook (the format of KiCad's own demo projects)."""
    pro = {"meta": {"filename": f"{variant}.kicad_pro", "version": 3},
           "schematic": {"meta": {"version": 1},
                         "ngspice": {"fix_include_paths": True, "fix_passive_vals": False, "meta": {"version": 0},
                                     "model_mode": 1, "workbook_filename": f"{variant}.wbk"}},
           "sheets": [[root_uuid, "Root"]], "text_variables": {}}
    with open(os.path.join(folder, f"{variant}.kicad_pro"), "w") as fh:
        json.dump(pro, fh, indent=2)
        fh.write("\n")
    cmd = directive(variant)
    wbk = {"last_sch_text_sim_command": cmd,
           "tabs": [{"analysis": "TRAN", "commands": [cmd, ".kicad adjustpaths", ".save all", ".probe alli"],
                     "dottedSecondary": False, "margins": {"bottom": 45, "left": 70, "right": 70, "top": 30},
                     "measurements": [], "showGrid": True,
                     "traces": [{"color": col, "signal": sig, "trace_type": 257} for sig, col in zip(TRACES[variant], COLORS)]}],
           "user_defined_signals": [], "version": 6}
    with open(os.path.join(folder, f"{variant}.wbk"), "w") as fh:
        json.dump(wbk, fh, indent=2)
        fh.write("\n")


def netlist(folder, variant):
    """KiCad's SPICE netlist of the schematic, as its simulator builds it."""
    out = os.path.join(folder, f"{variant}.cir")
    r = subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "spice", "-o", out,
                        os.path.join(folder, f"{variant}.kicad_sch")], capture_output=True, text=True, cwd=folder)
    if not os.path.exists(out):
        raise RuntimeError("kicad-cli gave no netlist:\n" + r.stdout + r.stderr)
    return out


def ngspice(folder, variant):
    """Run the exported netlist in ngspice; returns {signal: [values]} with 'time'."""
    cir = netlist(folder, variant)
    txt = open(cir).read()
    sigs = ["V(/T_TOP)", "V(/T_NTC)", "V(/GATE)", "V(/LIM_N)", "V(VBUS)"] if variant == "loop" else \
           ["V(/T_NTC)", "V(/GATE)", "V(/LIM_N)", "V(VBUS)"]
    data = os.path.join(folder, f"{variant}.data")
    ctl = (".control\nset wr_singlescale\nset wr_vecnames\nrun\nlinearize " + " ".join(sigs) +
           f"\nwrdata {data} " + " ".join(sigs) + "\n.endc\n")
    run = os.path.join(folder, f"{variant}_run.cir")
    with open(run, "w") as fh:
        fh.write(re.sub(r"\n\.end\s*$", "\n", txt) + ctl + ".end\n")
    r = subprocess.run(["ngspice", "-b", run], capture_output=True, text=True, cwd=folder)
    if not os.path.exists(data):
        raise RuntimeError("ngspice failed:\n" + (r.stdout + r.stderr)[-3000:])
    rows = [ln.split() for ln in open(data)]
    cols = {name: [float(v[i]) for v in rows[1:]] for i, name in enumerate(rows[0])}
    for tmp in (data, run):
        os.remove(tmp)
    return cols, r.stdout + r.stderr


def report(variant, cols):
    t = cols["time"]
    key = {k.lower(): v for k, v in cols.items()}
    gate, lim, vbus = key["v(/gate)"], key["v(/lim_n)"], key["v(vbus)"]
    if variant == "loop":
        top = key["v(/t_top)"]
        t99 = next((a for a, v in zip(t, top) if v >= 99.0), None)
        seg = [i for i, a in enumerate(t) if 100.0 <= a <= 148.0]
        on = [gate[i] > 1.65 for i in seg]
        edges = sum(1 for a, b in zip(on, on[1:]) if a != b)
        print(f"   99 °C at {t99:.0f} s, peak {max(top):.1f} °C, settled {min(top[i] for i in seg):.1f} to "
              f"{max(top[i] for i in seg):.1f} °C, duty {100 * sum(on) / len(on):.0f} %, "
              f"period {2 * 48.0 / edges if edges else 0:.1f} s, VBUS {min(vbus[i] for i in seg):.1f} to {max(vbus[i] for i in seg):.1f} V")
    else:
        temp = key["v(/t_ntc)"]
        ev = []
        for name, sig, thr in (("heater", gate, 1.65), ("limiter", lim, 1.65)):
            for i in range(1, len(t)):
                if (sig[i - 1] > thr) != (sig[i] > thr) and t[i] > 0.05:
                    word = (("off", "on") if name == "heater" else ("trips", "resets"))[sig[i] > thr]
                    ev.append(f"{name} {word} at {temp[i]:.1f} °C "
                              f"({'rising' if t[i] < RAMP[0] else 'falling'})")
        print("   " + "; ".join(ev))


def main(argv):
    lib = SC.Lib()
    bad = 0
    names = ("manual", "loop", "thresholds")
    for variant in [a for a in argv if a in names] or names:
        folder = os.path.join(HERE, variant)
        path = os.path.join(folder, f"{variant}.kicad_sch")
        prl = os.path.join(folder, f"{variant}.kicad_prl")           # kicad-cli leaves one behind
        had_prl = os.path.exists(prl)
        if os.path.exists(path) and "--force" not in argv:
            print(f"[{variant}] {os.path.relpath(path, ROOT)} exists: not overwritten (use --force to redraw it)")
        else:
            if variant == "manual":
                c, d = make_manual()
                s = draw_manual(c, d, lib)
            else:
                c, d, pl = make(variant)
                s = draw(c, variant, d, pl, lib)
            named = s.write(path)
            root = re.search(r'\(uuid "([^"]+)"\)', open(path).read()).group(1)
            project_files(folder, variant, root)
            res = SC.verify(c, path, lib, named)
            msgs, crossings = s.lint()
            erc = {f"{k[0]}:{k[1]}": len(x) for k, x in res["violations"].items()}
            print(f"[{variant}] {len(c.parts)} symbols, {res['n_nets']} nets, netlist mismatches {res['mismatches']}, "
                  f"extra nets {res['extra_nets']}, ERC {erc}, {crossings} wire crossings")
            for m in msgs:
                print("   lint:", m)
            for k, x in res["violations"].items():
                for line in x:
                    print("   ERC", k, line)
            for ext in ("_erc.json", ".net"):
                os.remove(os.path.join(folder, variant + ext))
            bad += len(res["mismatches"]) + len(res["extra_nets"]) + len(erc)
        if "--check" in argv and variant == "manual":
            check_manual(folder)
        elif "--check" in argv:
            cols, _ = ngspice(folder, variant)
            report(variant, cols)
            os.remove(os.path.join(folder, f"{variant}.cir"))
        if not had_prl and os.path.exists(prl):
            os.remove(prl)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
