"""The heater's circuit as code (one netlist drives schematic and PCB).

make() returns a Circuit. Every part carries its placement pcb=(x, y, rotation, "B"):
board frame of gen/geom.py, all on the underside.
How the circuit is drawn (symbol positions, wires, notes) is in gen/sheets.py.

This is the circuit the board in hw/analog/ was first generated from. That board and its
schematic are edited by hand since; see README.md for what differs.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "calc"))
sys.path.append(os.path.join(os.path.dirname(ROOT), "gen"))

import geom as G  # noqa: E402
import parts as P  # noqa: E402
from eda.circuit import Circuit  # noqa: E402  (sibling project toolkit)

R0603 = "Resistor_SMD:R_0603_1608Metric_Pad0.98x0.95mm_HandSolder"
C0603 = "Capacitor_SMD:C_0603_1608Metric_Pad1.08x0.95mm_HandSolder"
TP = "TestPoint:TestPoint_Pad_D1.5mm"
REV = "B"
VARIANT = "analog"     # names the project folder hw/analog and its files

# Parts left off the JLCPCB assembly order and soldered by hand: all are extended parts there
# (a fee per part type) and easy to do with an iron. RV1 is through-hole as well.
HAND_SOLDERED = {"analog": ("J1", "RT1", "RT2", "RV1")}

# where the links land on the tail (x of the power trace; sense and ground traces beside it)
X_LAND = 10.6          # |x| of the power trace where a link meets the tail (gen/board.py X_PWR)
Y_T = G.Y_TAIL


def _ic(c, ref, lib, key, fp, pins, pcb, value=None, **kw):
    mpn, lcsc, price, src, note = P.ic(key)
    c.add(ref, lib, value or mpn, fp, pins, pcb=pcb, MPN=mpn, LCSC=lcsc, Price=price, PriceSrc=src, Note=note, **kw)


def make(variant=VARIANT):
    assert variant == VARIANT
    c = Circuit(variant, title=f"USB-C PCB heater 100 °C, {variant} controller", rev=REV, paper="A3",
                company="pcb_heater / poc_fable")

    def R(ref, val, a, b, pcb, fp=R0603, **kw):
        mpn, lcsc, price, src = P.passive(val, "0603")
        c.add(ref, "Device:R", val, fp, {"1": a, "2": b}, pcb=pcb, MPN=mpn, LCSC=lcsc, Price=price, PriceSrc=src, **kw)

    def C(ref, val, a, b, pcb, fp=C0603, **kw):
        mpn, lcsc, price, src = P.passive(val, "0603")
        c.add(ref, "Device:C", val, fp, {"1": a, "2": b}, pcb=pcb, MPN=mpn, LCSC=lcsc, Price=price, PriceSrc=src, **kw)

    def ntc(ref, net, pcb, **kw):
        _ic(c, ref, "Device:Thermistor_NTC", "ntc", R0603, {"1": net, "2": "GND"}, pcb, value="100k NTC B3950", **kw)

    # ------------------------------------------------------------ USB-C input and PD sink
    _ic(c, "J1", "Connector:USB_C_Receptacle_PowerOnly_6P", "usbc", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-17",
        {"A5": "CC1", "B5": "CC2", "A9": "VBUS", "B9": "VBUS", "A12": "GND", "B12": "GND", "SH": "GND"},
        (0.0, G.Y_BOT + 3.2, 180, "B"))
    _ic(c, "U1", "Interface_USB:HUSB238_xxxDD", "pd", "Package_DFN_QFN:WDFN-10-1EP_3x3mm_P0.5mm_EP1.8x2.5mm",
        {"VIN": "VBUS", "D+": "NC", "D-": "NC", "CC1": "CC1", "CC2": "CC2", "VSET": "VSET", "ISET": "ISET",
         "GATE": "NC", "GND": "GND", "SDA": "I2C_IDLE", "SCL": "I2C_IDLE"}, (-0.75, -52.0, 90, "B"))
    C("C1", "1u 50V", "VBUS", "GND", (4.5, -53.9, 0, "B"))
    # 22k || 68k = 16.6k: the 2.5 A step of the ISET table (16.5k) from two values the board already uses
    R("R1", "22k", "ISET", "GND", (3.7, -48.4, 0, "B"), Note="ISET: with R16, PD offer must supply 2.5 A")
    R("R16", "68k", "ISET", "GND", (4.15, -46.7, 0, "B"), Note="ISET: 22k || 68k = 16.6k")

    # ------------------------------------------------------------ 3.3 V rail
    # C3 stands beside the regulator's pins, its pads level with VOUT and GND.
    # 1 uF in and out, the same part as C1: the rail carries about 1.5 mA.
    # Holtek's application circuit draws 10 uF on both sides and states no minimum; if the rail
    # turns out noisy, a 10 uF 10 V 0603 (C19702) fits the pads of C3.
    C("C2", "1u 50V", "VBUS", "GND", (-15.2, -46.4, 90, "B"))
    _ic(c, "U2", "Regulator_Linear:HT75xx-1-SOT89", "ldo", "Package_TO_SOT_SMD:SOT-89-3_Handsoldering",
        {"GND": "GND", "VIN": "VBUS", "VOUT": "+3V3"}, (-21.6, -46.8, 0, "B"))
    C("C3", "1u 50V", "+3V3", "GND", (-26.9, -46.8, 270, "B"))

    # ------------------------------------------------------------ heater and its switch
    c.add("HTR1", "Device:Heater", "heater 9R", "fable:Heater_70x70", {"1": "VBUS", "2": "HTR_N"},
          pcb=(0.0, 0.0, 0, "F"), in_bom=False, Note="PCB trace, R20 = 9.0 ohm; top layer")
    _ic(c, "Q1", "Transistor_FET:AO3400A", "fet", "Package_TO_SOT_SMD:SOT-23", {"G": "GATE", "S": "GND", "D": "HTR_N"},
        (X_LAND, -47.0, 90, "B"))
    # 22k here and at the comparator pull-ups, so the board needs no 10k part
    R("R2", "22k", "GATE_OC", "GATE", (14.8, -47.4, 90, "B"), Note="slow gate edges (~30 us)")

    # ------------------------------------------------------------ plate sensor
    ntc("RT1", "NTC1", (G.SENSORS[0][2] * G.NTC_DX, G.SENSORS[0][1], 180 if G.SENSORS[0][2] > 0 else 0, "B"))

    def tp(ref, net, pos):
        c.add(ref, "Connector:TestPoint", net, TP, {"1": net}, pcb=(*pos, 0, "B"), in_bom=False)

    # ------------------------------------------------------------ thermostat and limiter
    from control_sim import analog_design
    d = analog_design()
    for i, (net, x) in enumerate((("VBUS", -27.5), ("GND", -24.3), ("+3V3", -21.1), ("GATE", -17.9), ("HTR_N", -14.7))):
        tp(f"TP{i + 1}", net, (x, -60.6))
    f = P.fmt_r
    cmp_ = P.ic("cmp")
    R("R3", f(d["r_pu1"]), "+3V3", "NTC1", (-17.0, -51.0, 0, "B"))
    C("C4", "100n", "NTC1", "GND", (-17.0, -53.0, 0, "B"))
    # two dual comparators: U3 holds the thermostat, U4 the limiter, so that one dead chip cannot
    # take out both the control and the over-temperature fallback.
    # LM393 pins: unit A = 3 (+), 2 (-), 1 (out); unit B = 5 (+), 6 (-), 7 (out); 8 = V+, 4 = GND
    # The two limiter outputs (unit B of each chip) compare LIM_N with REF2, the limiter's own
    # reference. With REF1 there (until 2026-11-14) a fault that pulled the set-point reference to
    # 0 V turned the heater on and stopped both outputs from acting.
    for ref, a, b, at in (("U3", ("NTC1", "REF1", "GATE_OC"), ("LIM_N", "REF2", "GATE_OC"), (19.0, -53.6)),
                          ("U4", ("NTC2", "REF2", "LIM_N"), ("LIM_N", "REF2", "VSET"), (25.0, -53.6))):
        c.add(ref, "Comparator:LM393", "LM393", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
              {"3": a[0], "2": a[1], "1": a[2], "5": b[0], "6": b[1], "7": b[2], "8": "+3V3", "4": "GND"},
              pcb=(*at, 90, "B"), MPN=cmp_[0], LCSC=cmp_[1], Price=cmp_[2], PriceSrc=cmp_[3], Note=cmp_[4])
    C("C5", "100n", "+3V3", "GND", (21.8, -58.9, 0, "B"), Note="decoupling for U3 and U4")
    ntc("RT2", "NTC2", (G.SENSORS[1][2] * G.NTC_DX, G.SENSORS[1][1], 180 if G.SENSORS[1][2] > 0 else 0, "B"))
    R("R5", f(d["r_pu2"]), "+3V3", "NTC2", (17.6, -45.2, 0, "B"))
    C("C6", "100n", "NTC2", "GND", (17.6, -47.3, 0, "B"))
    # set point: RV1 as a variable resistor (wiper tied to the clockwise end) in series with R6.
    # Clockwise raises the resistance between pins 1 and 2, which lowers REF1: hotter. A wiper
    # that loses contact leaves the full 50k in circuit, the hottest setting, not an open reference.
    pot = P.ic("pot")
    c.add("RV1", "Device:R_Potentiometer", f(d["r_pot"]), "fable:Potentiometer_3362P",
          {"1": "+3V3", "2": "TSET", "3": "TSET"}, pcb=(8.0, -57.0, 0, "B"),
          MPN=pot[0], LCSC=pot[1], Price=pot[2], PriceSrc=pot[3],
          Note=f"set point {d['t_min']:.0f} to {d['t_max']:.0f} C, clockwise = hotter")
    R("R6", f(d["r_top1"]), "TSET", "REF1", (14.2, -54.8, 0, "B"))
    R("R7", f(d["r_set"]), "REF1", "GND", (14.2, -56.8, 0, "B"),
      Note=f"with R6 and RV1: {d['t_min']:.0f} to {d['t_max']:.0f} C")
    R("R8", f(d["r_top2"]), "+3V3", "REF2", (27.6, -45.2, 0, "B"))
    R("R9", f(d["r_lim"]), "REF2", "GND", (27.6, -47.3, 0, "B"),
      Note=f"limiter: trips {d['t_trip']:.0f} C, resets {d['t_reset']:.0f} C")
    R("R10", f(d["r_h1"]), "GATE_OC", "NTC1", (14.2, -52.8, 0, "B"), Note="thermostat hysteresis")
    R("R11", f(d["r_h2"]), "LIM_N", "NTC2", (24.2, -47.3, 0, "B"), Note="limiter hysteresis")
    R("R12", f(d["r_pull"]), "+3V3", "GATE_OC", (14.2, -50.8, 0, "B"))
    R("R13", f(d["r_pull"]), "+3V3", "LIM_N", (21.0, -45.2, 0, "B"))
    R("R14", "22k", "+3V3", "I2C_IDLE", (-2.8, -49.4, 0, "B"), Note="keeps the unused I2C pins of U1 idle")
    # R15 stays 10k: the PD chip's VSET table reads 10k as 12 V. Not fitted, so not a BOM line.
    R("R15", "10k", "VSET", "GND", (0.75, -47.9, 90, "B"), dnp=True,
      Note="option for small 12 V chargers: fit 10k here (12 V limit), fit 4.7k at R1 and leave R16 empty (1.5 A)")
    led_y = P.ic("led_y")
    c.add("D1", "Device:LED", "yellow", "LED_SMD:LED_0805_2012Metric_Pad1.15x1.40mm_HandSolder",
          {"A": "VBUS", "K": "LED_K"}, pcb=(0.0, -44.3, 0, "B"),
          MPN=led_y[0], LCSC=led_y[1], Price=led_y[2], PriceSrc=led_y[3],
          Note="lit while the heater is energised; shines down, seen through the gap in front of the tail")
    R("R4", "4.7k", "LED_K", "HTR_N", (-4.8, -44.6, 0, "B"))

    for i, net in enumerate(("VBUS", "GND")):
        c.add(f"#FLG0{i + 1}", "power:PWR_FLAG", "PWR_FLAG", "", {"1": net}, in_bom=False)
    return c


if __name__ == "__main__":
    c = make()
    real = [p for p in c.parts if not p.ref.startswith("#") and p.in_bom and not p.dnp]
    print(VARIANT, "parts to buy:", len(real), " nets:", len(c.nets()))
