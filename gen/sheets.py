#!/usr/bin/env python3
"""How the circuit is drawn: symbol positions, wires, labels and notes.

    python3 gen/sheets.py --overwrite      write and check hw/analog/analog.kicad_sch

The schematic in hw/analog/ is edited by hand since 2026-11-11 and this script would replace
it, so it does nothing without --overwrite.

analog() draws the circuit of gen/circuits.py, one functional group after the other.
Coordinates are grid steps of 1.27 mm on an A3 sheet, x to the right, y down; a point is
'REF.PIN' or (x, y) (see Sheet.pt in gen/schematic.py). gen/schematic.py refuses to write a
drawing whose wires do not give exactly the nets of the circuit.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import circuits  # noqa: E402  (also puts calc/ and the sibling toolkit on the path)
import parts as P  # noqa: E402
import schematic as SC  # noqa: E402


def tp(s, ref, x, y):
    """Test pad standing on a wire; its net is named by the wire, so only the reference shows."""
    s.sym(ref, x, y, val=False, ref_at=(0, -4.2, "c"))


def gnd(s, *pins):
    for p in pins:
        s.pwr("GND", p)


def input_and_pd(s, variant):
    """USB-C socket and PD sink controller (sheet x 12..114, y 14..77)."""
    s.box(12, 14, 114, 77, "USB-C input and PD sink")
    s.sym("J1", 28, 42)
    s.sym("U1", 72, 48)
    s.wire("J1.A9", (44, None), (None, 26))
    s.pwr("VBUS", (44, 26))
    s.wire((44, 30), ("U1.VIN", None), "U1.VIN")
    s.sym("C1", 52, 33)
    tp(s, "TP1", 59, 30)
    s.sym("#FLG01", 65, 30)
    s.wire("J1.CC1", "U1.CC1")
    s.wire("J1.CC2", "U1.CC2")
    s.wire("J1.SH", (None, 60), (42, None))
    s.wire("J1.A12", (None, 60))
    s.sym("#FLG02", 42, 60)
    gnd(s, (28, 60), "C1.2", "U1.GND")


def rail(s, x, y, tp_out):
    """3.3 V regulator in a box whose top left corner is (x, y)."""
    s.box(x, y, x + 66, y + 36, "3.3 V rail")
    s.sym("U2", x + 32, y + 20, ref_at=(0, -6.5, "c"))
    s.sym("C2", x + 16, y + 21)
    s.sym("C3", x + 48, y + 21)
    s.pwr("VBUS", (x + 10, y + 18))
    s.wire((x + 10, y + 18), "U2.VIN")
    s.wire("U2.VOUT", (x + 60, None))
    s.pwr("+3V3", (x + 60, y + 18))
    tp(s, tp_out, x + 54, y + 18)
    gnd(s, "C2.2", "U2.GND", "C3.2")


# the two notes are also what gets written into the hand-edited hw/analog schematic
THERMOSTAT_NOTE = ("RV1 sets the temperature: {t_min:.0f} °C fully anticlockwise, {t_max:.0f} °C fully clockwise.\n"
                   "Heater off above the set point, on again 0.9 K below it (R10).")
LIMITER_NOTE = ("RT2 above {t_trip:.0f} °C: LIM_N goes low and stays low until {t_reset:.0f} °C (hysteresis by R11).\n"
                "Then U3B holds the gate low and U4B shorts VSET, so the charger falls back to 5 V:\n"
                "1/16 of the heater power, even with Q1 failed short.")


def analog(s):
    from control_sim import analog_design
    d = analog_design()

    # ---------------------------------------------------------------- USB-C input and PD sink
    input_and_pd(s, "analog")
    tp(s, "TP2", 35, 60)
    s.sym("R14", 88, 39)
    s.pwr("+3V3", "R14.1")
    s.wire("U1.SCL", (88, None))
    s.wire("U1.SDA", (88, None), "R14.2")
    s.sym("R1", 90, 60)
    s.sym("R16", 98, 60)
    s.sym("R15", 108, 60)
    s.wire("U1.ISET", ("R16.1", None), "R16.1")
    s.wire(("R1.1", "U1.ISET"), "R1.1")
    s.wire("U1.VSET", ("R15.1", None), "R15.1")
    gnd(s, "R1.2", "R16.2", "R15.2")
    s.label("VSET", (100, 52))
    s.text("U1 asks the charger for the highest voltage, 20 V at most, that it offers with 2.5 A\n"
           "(ISET: R1 || R16 = 16.6k). VSET pulled to GND limits it to 5 V: the limiter's fallback.\n"
           "12 V option for small chargers: fit R15, 4.7k at R1 and no R16 (see README).", 14, 70.5)

    # ---------------------------------------------------------------- 3.3 V rail, comparator supply
    rail(s, 142, 14, "TP3")
    s.box(214, 14, 262, 50, "Comparator supply")
    s.sym("U3", 228, 34, unit=3)
    s.sym("U4", 240, 34, unit=3)
    s.sym("C5", 252, 34)
    s.wire((220, 26), ("C5.1", None), "C5.1")
    s.wire("U3.8", (None, 26))
    s.wire("U4.8", (None, 26))
    s.pwr("+3V3", (220, 26))
    s.wire((220, 42), ("C5.2", None), "C5.2")
    s.wire("U3.4", (None, 42))
    s.wire("U4.4", (None, 42))
    gnd(s, (220, 42))

    # ---------------------------------------------------------------- over-temperature limiter
    # columns shared by the two comparator stages: sensor, its capacitor, reference divider,
    # comparator, feedback corner, pull-up; then the two limiter outputs
    xs, xc, xb, xd, xu, xf, xp, xl, xr, xo = 24, 42, 58, 68, 76, 86, 94, 104, 110, 120
    y = 110
    s.box(12, 82, xo + 12, y + 23, "Over-temperature limiter (second sensor)")
    s.sym("R5", xs, y - 16)
    s.sym("RT2", xs, y - 4)
    s.sym("C6", xc, y - 4)
    s.pwr("+3V3", "R5.1")
    gnd(s, "RT2.2", "C6.2")
    s.wire("R5.2", "RT2.1")
    s.sym("R11", xu, y - 10, rot=270)                    # hysteresis: output back to the + input
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
    s.sym("U4", xo, y + 2, unit=2, val=False)            # limiter tripped -> PD chip to 5 V
    s.sym("U3", xo, y + 16, unit=2, val=False)           # limiter tripped -> gate held low
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
    s.wire(("R15.1", "U1.VSET"), (xo + 16, None), (None, "U4.7"), "U4.7")
    s.text(LIMITER_NOTE.format(**d), 14, y + 15.5)

    # ---------------------------------------------------------------- thermostat
    y = 158
    s.box(12, 141, xo + 12, y + 26, "Thermostat")
    s.sym("U3", xu, y, unit=1, mirror="x")               # - input on top: REF1 comes from above
    s.sym("R6", xb, y - 6)
    s.sym("R7", xb, y + 2)
    s.sym("RV1", xb - 8, y - 11, rot=90, ref_at=(0, 2, "c"), val_at=(0, 4, "c"))   # set point: +3V3 - RV1 - R6
    s.pwr("+3V3", (xb - 14, y - 11))
    s.wire((xb - 14, y - 11), "RV1.1")
    s.wire("RV1.3", (xb, None), "R6.1")
    s.wire("RV1.2", (xb - 3, None), (None, y - 11))      # wiper tied to the clockwise end
    gnd(s, "R7.2")
    s.wire("R6.2", "R7.1")
    s.wire((xb, y - 2), "U3.2")
    s.sym("R3", xs, y + 6)
    s.sym("RT1", xs, y + 18)
    s.sym("C4", xc, y + 18)
    s.pwr("+3V3", "R3.1")
    gnd(s, "RT1.2", "C4.2")
    s.wire("R3.2", "RT1.1")
    s.sym("R10", xu, y + 12, rot=270)                    # hysteresis
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
    # REF1 also goes up to the two limiter outputs
    s.text(THERMOSTAT_NOTE.format(**d), xb - 2, y + 17.5)

    # ---------------------------------------------------------------- heater and switch
    x = xo + 26                                          # left edge of the group
    s.box(x, y - 37, x + 68, y + 26, "Heater and switch")
    s.sym("R2", x + 8, y, rot=90)
    s.wire("U3.1", "R2.1")
    s.wire("U3.7", (x - 6, None), (None, y))             # limiter output on the same open-collector node
    s.sym("Q1", x + 34, y)
    s.wire("R2.2", "Q1.G")
    s.label("GATE", (x + 13, y))
    tp(s, "TP4", x + 23, y)
    s.sym("HTR1", x + 36, y - 18)
    s.wire("HTR1.2", "Q1.D")
    s.wire("HTR1.1", (None, y - 30))
    s.pwr("VBUS", (x + 36, y - 30))
    s.sym("D1", x + 52, y - 22, rot=90)
    s.sym("R4", x + 52, y - 12)
    s.wire((x + 36, y - 27), ("D1.A", None), "D1.A")
    s.wire("D1.K", "R4.1")
    s.wire("R4.2", (None, y - 7), (x + 36, None))
    s.wire((x + 52, y - 7), (x + 62, None))
    tp(s, "TP5", x + 62, y - 7)
    s.label("HTR_N", (x + 38, y - 7))
    s.wire("Q1.S", (None, y + 7))
    gnd(s, (x + 36, y + 7))
    s.text("HTR1 is the trace on the top side: 9.0 Ω at 20 °C, 44 W at 20 V.\n"
           "R2 slows the gate edges to about 30 µs: no flyback diode needed.\n"
           "D1 is lit while the heater is on.", x + 2, y + 13.5)


LAYOUT = {"analog": analog}


def draw(circuit, variant, lib):
    s = SC.Sheet(circuit, lib, "A3")
    LAYOUT[variant](s)
    return s


def main(argv):
    if "--overwrite" not in argv:
        print("gen/sheets.py redraws hw/analog/analog.kicad_sch from gen/circuits.py. That schematic is edited\n"
              "by hand and would be replaced. Nothing done; pass --overwrite if that is what you want.")
        return 2
    lib = SC.Lib()
    bad = 0
    for v in [a for a in argv if a in LAYOUT] or list(LAYOUT):
        c = circuits.make(v)
        s = draw(c, v, lib)
        path = os.path.join(ROOT, "hw", v, f"{v}.kicad_sch")
        named = s.write(path)
        res = SC.verify(c, path, lib, named)
        msgs, crossings = s.lint()
        erc = {f"{k[0]}:{k[1]}": len(x) for k, x in res["violations"].items()}
        print(f"[{v}] {res['n_nets']} nets, netlist mismatches {res['mismatches']}, extra nets {res['extra_nets']}, "
              f"ERC {erc}, {crossings} wire crossings")
        for m in msgs:
            print("   lint:", m)
        if "-v" in argv:
            for k, x in res["violations"].items():
                for line in x:
                    print("   ERC", k, line)
        bad += len(res["mismatches"]) + len(res["extra_nets"]) + len(erc)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
