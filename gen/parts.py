"""Part table: what to buy, where, and roughly what it costs.

Every part has an LCSC / JLCPCB number. Prices, stock and the basic / extended class come from
JLCPCB's parts library (gen/jlc_parts.json, refreshed by `python3 gen/pcba.py --refresh`); the
figures in the tables below are only the fallback when that file is missing.
"""
import json
import math
import os

CHECKED = "2026-11-11"
_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jlc_parts.json")

# name -> (MPN, LCSC, price, price source, note)
ICS = {
    "usbc":   ("TYPE-C-31-M-17", "C283540", 0.20, "est", "HRO 6-pin power-only USB-C receptacle, 5 A"),
    "pd":     ("HUSB238_002DD", "C7471904", 0.59, "est", "Hynetek PD sink, DFN-10 3x3 mm"),
    "ldo":    ("HT7533-1", "C14289", 0.13, "est", "Holtek 3.3 V LDO, 30 V max input, SOT-89"),
    "fet":    ("AO3400A", "C20917", 0.08, "est", "30 V N-MOSFET, SOT-23"),
    "ntc":    ("KNTC0603/100KF3950", "C2892545", 0.03, "est", "100 k 1 % B3950 0603, -40..125 C"),
    "ntc_s":  ("SDNT1608X104F3950FTF", "C919169", 0.015, "est", "Sunlord 100 k 1 % B3950 0603, -55..125 C"),
    "cmp":    ("LM393DR2G", "C7955", 0.06, "est", "onsemi dual comparator, SOIC-8; JLCPCB basic part"),
    "mcu":    ("STM32C011F4P6", "C5452432", 1.47, "est", "TSSOP-20"),
    "amp":    ("INA180A2IDBVR", "C192764", 0.19, "est", "current-sense amplifier, gain 50, SOT-23-5"),
    "shunt":  ("FRM121WFR020TM", "C7420010", 0.04, "est", "20 mohm 1 % 1 W 50 ppm/K, 1206"),
    "led":    ("LTST-C230KRKT", "C125107", 0.05, "est", "red reverse-mount LED, 1206; shines through the board"),
    "led_y":  ("KT-0805Y", "C2296", 0.015, "est", "yellow 0805 LED; JLCPCB basic part"),
    "pot":    ("3362P-1-503", "C118910", 0.16, "est", "BOCHEN 50 k 10 % single-turn trimmer, 3362P style, through-hole"),
}

# (value, package) -> (MPN, LCSC, price, source); the 0603 resistors are 1 % parts
PASSIVES = {
    ("100n", "0603"): ("CC0603KRX7R9BB104", "C14663", 0.006, "est"),
    ("10n", "0603"): ("0603B103K500NT", "C57112", 0.010, "est"),
    ("1u 50V", "0603"): ("CL10A105KB8NNNC", "C15849", 0.011, "est"),
    ("4.7u", "0603"): ("CL10A475KO8NNNC", "C19666", 0.015, "est"),
    ("470", "0603"): ("0603WAF4700T5E", "C23179", 0.002, "est"),
    ("1k", "0603"): ("0603WAF1001T5E", "C21190", 0.002, "est"),
    ("3.3k", "0603"): ("0603WAF3301T5E", "C22978", 0.002, "est"),
    ("4.7k", "0603"): ("0603WAF4701T5E", "C23162", 0.003, "est"),
    ("6.2k", "0603"): ("0603WAF6201T5E", "C4260", 0.002, "est"),
    ("10k", "0603"): ("0603WAF1002T5E", "C25804", 0.002, "est"),
    ("16.5k", "0603"): ("0603WAF1652T5E", "C22812", 0.003, "est"),
    ("22k", "0603"): ("0603WAF2202T5E", "C31850", 0.004, "est"),
    ("68k", "0603"): ("0603WAF6802T5E", "C23231", 0.002, "est"),
    ("100k", "0603"): ("0603WAF1003T5E", "C25803", 0.003, "est"),
    ("1M", "0603"): ("0603WAF1004T5E", "C22935", 0.002, "est"),
    ("3M", "0603"): ("0603WAF3004T5E", "C23156", 0.003, "est"),      # extended, but "preferred": no fee
}

_jlc = None


def jlc(lcsc=None):
    """JLCPCB parts-library record of one part ({} if unknown), or the whole cache."""
    global _jlc
    if _jlc is None:
        try:
            with open(_CACHE) as f:
                _jlc = json.load(f)
        except (OSError, ValueError):
            _jlc = {"fetched": "", "parts": {}}
    return _jlc if lcsc is None else _jlc["parts"].get(lcsc, {})


def unit_price(lcsc, qty=1, fallback=0.0):
    """JLCPCB price for a quantity (their price breaks), or the fallback."""
    tiers = jlc(lcsc).get("prices") or []
    best = None
    for start, usd in tiers:
        if qty >= start:
            best = usd
    return (best if best is not None else (tiers[0][1] if tiers else fallback))


def _priced(mpn, lcsc, price, src):
    rec = jlc(lcsc)
    return (mpn, lcsc, unit_price(lcsc, 1, price), "jlc") if rec else (mpn, lcsc, price, src)


def ic(name):
    """(MPN, LCSC, price, price source, note) with the price from the JLCPCB cache if present."""
    mpn, lcsc, price, src, note = ICS[name]
    return (*_priced(mpn, lcsc, price, src), note)


NTC_R25 = 100e3
NTC_B = 3950.0

E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]


def ntc_r(t_c):
    """NTC resistance in ohm at t_c (B-parameter model)."""
    return NTC_R25 * math.exp(NTC_B * (1 / (t_c + 273.15) - 1 / 298.15))


def ntc_t(r):
    return 1 / (1 / 298.15 + math.log(r / NTC_R25) / NTC_B) - 273.15


def e96(x):
    """Nearest E96 value."""
    d = math.floor(math.log10(x))
    m = x / 10 ** d
    k = round(96 * math.log10(m))
    v = round(10 ** (k / 96), 2)
    return v * 10 ** d


def e24(x):
    d = math.floor(math.log10(x))
    m = x / 10 ** d
    v = min(E24 + [10.0], key=lambda e: abs(math.log(e / m)))
    return v * 10 ** d


def fmt_r(ohm):
    """4750 -> '4.75k', 1e6 -> '1M', 16500 -> '16.5k'."""
    for div, suf in ((1e6, "M"), (1e3, "k"), (1, "R")):
        if ohm >= div:
            s = f"{ohm / div:.3g}"
            return s + suf
    return f"{ohm:g}R"


def passive(value, package):
    """(MPN, LCSC, price, source) for a resistor/capacitor value."""
    return _priced(*PASSIVES[(value.replace(" 1%", ""), package)])
