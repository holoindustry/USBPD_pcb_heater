#!/usr/bin/env python3
"""BOM comparison of the two controller variants.

    python3 gen/compare.py           table on the terminal
    python3 gen/compare.py --md      Markdown, as pasted into README.md

Counts every part that has to be bought and soldered (no test pads, no unpopulated options,
no PCB). Prices come from gen/parts.py: small-quantity LCSC prices, rough by nature.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import circuits  # noqa: E402
import parts as P  # noqa: E402
import pcbkit as K  # noqa: E402

KIND = (("ICs and transistor", ("U", "Q")), ("connector, LED, NTCs, trimmer", ("J", "D", "RT", "RV")),
        ("resistors", ("R",)), ("capacitors", ("C",)))


def summary(variant):
    rows = K.bom_rows(circuits.make(variant))
    refs = [r for row in rows for r in row[-1]]
    cost = sum(row[4] * len(row[-1]) for row in rows)
    est = sum(row[4] * len(row[-1]) for row in rows if row[5] == "est")
    by_kind = {}
    for name, prefixes in KIND:
        by_kind[name] = sum(1 for r in refs if r.rstrip("0123456789") in prefixes)
    return dict(rows=rows, parts=len(refs), lines=len(rows), cost=cost, est=est, by_kind=by_kind)


def main(argv):
    a, s = summary("analog"), summary("stm32")
    md = "--md" in argv
    line = (lambda *c: "| " + " | ".join(str(x) for x in c) + " |") if md else (lambda *c: f"{c[0]:34s}{str(c[1]):>12s}{str(c[2]):>12s}")
    out = [line("", "Analog", "STM32")]
    if md:
        out.append("|---|---|---|")
    out.append(line("Parts to solder", a["parts"], s["parts"]))
    for name, _ in KIND:
        out.append(line(("  " if not md else "- ") + name, a["by_kind"][name], s["by_kind"][name]))
    out.append(line("BOM lines (different parts)", a["lines"], s["lines"]))
    out.append(line("Parts cost per board", f"${a['cost']:.2f}", f"${s['cost']:.2f}"))
    print("\n".join(out))
    if md:
        return
    print(f"\nprices checked {P.CHECKED}; estimated (not looked up) share: analog ${a['est']:.2f}, stm32 ${s['est']:.2f}")
    for name, x in (("analog", a), ("stm32", s)):
        print(f"\n{name}:")
        for val, fp, mpn, lcsc, price, src, refs in x["rows"]:
            print(f"  {len(refs):2d} x {val:14s} {mpn or '(by value)':22s} {lcsc:10s} ${price:6.3f} {src:4s}  {','.join(refs)}")
    only_a = {(r[0], r[2]) for r in a["rows"]} - {(r[0], r[2]) for r in s["rows"]}
    only_s = {(r[0], r[2]) for r in s["rows"]} - {(r[0], r[2]) for r in a["rows"]}
    print("\nonly in analog:", ", ".join(sorted(f"{v} {m}".strip() for v, m in only_a)))
    print("only in stm32: ", ", ".join(sorted(f"{v} {m}".strip() for v, m in only_s)))


if __name__ == "__main__":
    main(sys.argv[1:])
