"""Circuits of the two controller variants, as code (one netlist drives schematic and PCB).

make("analog") / make("stm32") return a Circuit. Every part carries its placement
pcb=(x, y, rotation, "B"): board frame of gen/geom.py, all on the underside.
How the circuit is drawn (symbol positions, wires, notes) is in gen/sheets.py.
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
R1206 = "Resistor_SMD:R_1206_3216Metric_Pad1.30x1.75mm_HandSolder"
TP = "TestPoint:TestPoint_Pad_D1.5mm"
REV = "B"

# Parts left off the JLCPCB assembly order and soldered by hand: all are extended parts there
# (a fee per part type) and easy to do with an iron. RV1 is through-hole as well.
HAND_SOLDERED = {"analog": ("J1", "RT1", "RT2", "RV1")}

# where the links land on the tail (x of the power trace; sense and ground traces beside it)
X_LAND = 10.6          # |x| of the power trace where a link meets the tail (gen/board.py X_PWR)
Y_T = G.Y_TAIL

# STM32 pin use (also the firmware's pin map)
MCU_PINS = {
    "PA0": "NTC1",       # ADC_IN0  plate NTC
    "PA1": "ISENSE",     # ADC_IN1  heater current, 20 mohm x 50 = 1 V/A
    "PA2": "VSENSE",     # ADC_IN2  VBUS / 11
    "PA3": "NTC2",       # ADC_IN3  optional second NTC
    "PA5": "LED",        # status LED, active high
    "PA8": "GATE_DRV",   # TIM1_CH1 PWM -> 10 k -> gate
    "PA9/PA11": "SCL",   # PA11, bit-banged I2C to the HUSB238
    "PA10/PA12": "SDA",  # PA12
    "PA13": "SWDIO",
    "PA14": "SWCLK",
    "PB6": "TX",         # USART1_TX log
    "PB7": "VSET",       # open drain: low forces the PD chip to 5 V
    "PF2": "NRST",
}


def _ic(c, ref, lib, key, fp, pins, pcb, value=None, **kw):
    mpn, lcsc, price, src, note = P.ic(key)
    c.add(ref, lib, value or mpn, fp, pins, pcb=pcb, MPN=mpn, LCSC=lcsc, Price=price, PriceSrc=src, Note=note, **kw)


def make(variant):
    assert variant in ("analog", "stm32")
    c = Circuit(variant, title=f"USB-C PCB heater 100 °C, {variant} controller", rev=REV, paper="A3",
                company="pcb_heater / poc_fable")

    def R(ref, val, a, b, pcb, fp=R0603, **kw):
        mpn, lcsc, price, src = P.passive(val, "0603")
        c.add(ref, "Device:R", val, fp, {"1": a, "2": b}, pcb=pcb, MPN=mpn, LCSC=lcsc, Price=price, PriceSrc=src, **kw)

    def C(ref, val, a, b, pcb, fp=C0603, **kw):
        mpn, lcsc, price, src = P.passive(val, "0603")
        c.add(ref, "Device:C", val, fp, {"1": a, "2": b}, pcb=pcb, MPN=mpn, LCSC=lcsc, Price=price, PriceSrc=src, **kw)

    def ntc(ref, net, pcb, **kw):
        # analog board: the Sunlord part, set by hand in the KiCad files on 2026-11-12
        _ic(c, ref, "Device:Thermistor_NTC", "ntc_s" if variant == "analog" else "ntc", R0603, {"1": net, "2": "GND"},
            pcb, value="100k NTC B3950", **kw)

    src = "GND" if variant == "analog" else "SH_P"
    drv = "GATE_OC" if variant == "analog" else "GATE_DRV"

    # ------------------------------------------------------------ USB-C input and PD sink
    _ic(c, "J1", "Connector:USB_C_Receptacle_PowerOnly_6P", "usbc", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-17",
        {"A5": "CC1", "B5": "CC2", "A9": "VBUS", "B9": "VBUS", "A12": "GND", "B12": "GND", "SH": "GND"},
        (0.0, G.Y_BOT + 3.2, 180, "B"))
    i2c = {"SDA": "I2C_IDLE", "SCL": "I2C_IDLE"} if variant == "analog" else {"SDA": "SDA", "SCL": "SCL"}
    _ic(c, "U1", "Interface_USB:HUSB238_xxxDD", "pd", "Package_DFN_QFN:WDFN-10-1EP_3x3mm_P0.5mm_EP1.8x2.5mm",
        {"VIN": "VBUS", "D+": "NC", "D-": "NC", "CC1": "CC1", "CC2": "CC2", "VSET": "VSET", "ISET": "ISET",
         "GATE": "NC", "GND": "GND", **i2c}, (-0.75, -52.0, 90, "B"))
    C("C1", "1u 50V", "VBUS", "GND", (4.5, -53.9, 0, "B"))
    if variant == "analog":
        # 22k || 68k = 16.6k: the 2.5 A step of the ISET table (16.5k) from two values the board already uses
        R("R1", "22k", "ISET", "GND", (3.7, -48.4, 0, "B"), Note="ISET: with R16, PD offer must supply 2.5 A")
        R("R16", "68k", "ISET", "GND", (4.15, -46.7, 0, "B"), Note="ISET: 22k || 68k = 16.6k")
    else:
        R("R1", "16.5k 1%", "ISET", "GND", (3.0, -47.2, 0, "B"), Note="ISET: PD offer must supply 2.5 A")

    # ------------------------------------------------------------ 3.3 V rail
    # analog: C3 stands beside the regulator's pins, its pads level with VOUT and GND
    left = dict(analog=dict(U2=(-21.6, -46.8), C2=(-15.2, -46.4), C3=(-26.9, -46.8, 270)),
                stm32=dict(U2=(-19.4, -46.4), C2=(-13.0, -48.6), C3=(-24.6, -45.2, 0)))[variant]
    # 1 uF in and out on the analog board, the same part as C1: the rail carries about 1.5 mA.
    # Holtek's application circuit draws 10 uF on both sides and states no minimum; if the rail
    # turns out noisy, a 10 uF 10 V 0603 (C19702) fits the pads of C3.
    C("C2", "1u 50V", "VBUS", "GND", (*left["C2"], 90, "B"))
    _ic(c, "U2", "Regulator_Linear:HT75xx-1-SOT89", "ldo", "Package_TO_SOT_SMD:SOT-89-3_Handsoldering",
        {"GND": "GND", "VIN": "VBUS", "VOUT": "+3V3"}, (*left["U2"], 0, "B"))
    # STM32 board: 4.7 uF, which is also the bulk capacitor of the MCU supply
    C("C3", "1u 50V" if variant == "analog" else "4.7u", "+3V3", "GND", (*left["C3"], "B"))

    # ------------------------------------------------------------ heater and its switch
    c.add("HTR1", "Device:Heater", "heater 9R", "fable:Heater_70x70", {"1": "VBUS", "2": "HTR_N"},
          pcb=(0.0, 0.0, 0, "F"), in_bom=False, Note="PCB trace, R20 = 9.0 ohm; top layer")
    _ic(c, "Q1", "Transistor_FET:AO3400A", "fet", "Package_TO_SOT_SMD:SOT-23", {"G": "GATE", "S": src, "D": "HTR_N"},
        (X_LAND, -47.0, 90, "B"))
    # analog board: 22k here and at the comparator pull-ups, so the board needs no 10k part
    R("R2", "22k" if variant == "analog" else "10k", drv, "GATE", (14.8, -47.4, 90, "B"),
      Note="slow gate edges (~30 us)" if variant == "analog" else "slow gate edges (~15 us)")

    # ------------------------------------------------------------ plate sensor
    ntc("RT1", "NTC1", (G.SENSORS[0][2] * G.NTC_DX, G.SENSORS[0][1], 180 if G.SENSORS[0][2] > 0 else 0, "B"))

    def tp(ref, net, pos):
        c.add(ref, "Connector:TestPoint", net, TP, {"1": net}, pcb=(*pos, 0, "B"), in_bom=False)

    led_fp = "fable:LED_1206_ReverseMount"
    led = P.ic("led")

    if variant == "analog":
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
    else:
        # measuring points; TP7..TP11 are the SWD pads, 2.54 mm apart, in ST-Link order
        tp("TP1", "VBUS", (-13.2, -61.0))
        tp("TP4", "GATE", (18.0, -47.4))
        tp("TP5", "HTR_N", (6.4, -44.4))
        tp("TP6", "TX", (-15.9, -61.0))
        for i, net in enumerate(("+3V3", "SWDIO", "SWCLK", "NRST", "GND")):
            tp(f"TP{7 + i}", net, (-28.6 + 2.54 * i, -61.0))
        R("R3", "22k 1%", "+3V3", "NTC1", (-26.6, -50.9, 0, "B"))
        C("C4", "10n", "NTC1", "GND", (-26.6, -52.8, 0, "B"))
        pins = {k: "NC" for k in ("PC14", "PC15", "PA4", "PA6", "PA7")}
        pins.update(MCU_PINS)
        pins.update({"VDD": "+3V3", "VSS": "GND"})
        _ic(c, "U3", "MCU_ST_STM32C0:STM32C011F4Px", "mcu", "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm", pins,
            (-20.5, -54.0, 180, "B"))
        C("C5", "100n", "+3V3", "GND", (-26.4, -55.4, 90, "B"))
        C("C6", "100n", "NRST", "GND", (-26.6, -58.6, 0, "B"))
        R("R5", "100k", "VBUS", "VSENSE", (-24.6, -47.6, 0, "B"), Note="VBUS / 11")
        R("R6", "10k", "VSENSE", "GND", (-28.0, -47.6, 0, "B"))
        R("R7", "100k", "GATE", "GND", (14.8, -45.0, 0, "B"), Note="switch off while the MCU is in reset")
        mpn, lcsc, price, s, note = P.ic("shunt")
        c.add("R8", "Device:R", "20m 1%", R1206, {"1": "SH_P", "2": "GND"}, pcb=(11.6, -51.6, 90, "B"),
              MPN=mpn, LCSC=lcsc, Price=price, PriceSrc=s, Note=note)
        _ic(c, "U4", "Amplifier_Current:INA180A2", "amp", "Package_TO_SOT_SMD:SOT-23-5_HandSoldering",
            {"+": "SH_P", "-": "GND", "1": "ISENSE", "V+": "+3V3", "GND": "GND"}, (6.6, -50.6, 0, "B"), value="INA180A2")
        C("C7", "100n", "+3V3", "GND", (7.2, -46.6, 0, "B"))
        R("R9", "10k", "+3V3", "SCL", (-2.8, -49.4, 0, "B"))
        R("R10", "10k", "+3V3", "SDA", (-2.8, -47.4, 0, "B"))
        c.add("D1", "Device:LED", "red", led_fp, {"A": "LED_A", "K": "GND"}, pcb=(0.0, -44.6, 0, "B"),
              MPN=led[0], LCSC=led[1], Price=led[2], PriceSrc=led[3],
              Note="status; " + led[4])
        R("R4", "470", "LED", "LED_A", (-4.8, -44.6, 0, "B"))
        ntc("RT2", "NTC2", (G.SENSORS[1][2] * G.NTC_DX, G.SENSORS[1][1], 180 if G.SENSORS[1][2] > 0 else 0, "B"),
            dnp=True)
        R("R11", "22k 1%", "+3V3", "NTC2", (-24.6, -49.4, 0, "B"), dnp=True, Note="fit with RT2")
        C("C8", "10n", "NTC2", "GND", (-28.0, -45.6, 0, "B"), dnp=True, Note="fit with RT2")

    for i, net in enumerate(("VBUS", "GND")):
        c.add(f"#FLG0{i + 1}", "power:PWR_FLAG", "PWR_FLAG", "", {"1": net}, in_bom=False)
    return c


if __name__ == "__main__":
    for v in ("analog", "stm32"):
        c = make(v)
        real = [p for p in c.parts if not p.ref.startswith("#") and p.in_bom and not p.dnp]
        print(v, "parts to buy:", len(real), " nets:", len(c.nets()))
