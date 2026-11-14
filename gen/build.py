#!/usr/bin/env python3
"""Regenerate the heater board from gen/circuits.py.

    python3 gen/build.py --overwrite

Writes hw/lib (project library) and hw/analog/: KiCad project, ERC/DRC reports, Gerber
zip, BOM, position file, schematic PDF, renders, layout.png. Exits non-zero if a check fails.

DO NOT RUN THIS ON THE REAL PROJECT. hw/analog/ is edited by hand since 2026-11-11: the board
there is routed by hand and its schematic has parts and changes the generator does not know.
The generator's own layout of the present circuit has never been made to pass DRC (the
trimmer has no legal place in it). The script therefore does nothing without --overwrite; it
is kept as the record of how the board was first made, and for work on a copy.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import board  # noqa: E402

ERC_OK = ()                                         # ERC must be completely clean
DRC_OK = ("warning:silk_overlap", "warning:silk_over_copper", "warning:silk_edge_clearance",
          "warning:lib_footprint_mismatch", "warning:lib_footprint_issues", "warning:text_height",
          "warning:text_thickness")


def check(res):
    problems = []
    if abs(res["r20"] - 9.0) > 0.05:
        problems.append(f"R20 {res['r20']:.2f} ohm")
    if res["min_gap"] < 0.19:
        problems.append(f"heater gap {res['min_gap']:.3f} mm")
    if res["net_mismatch"] or res["extra_nets"]:
        problems.append("schematic netlist differs from the circuit")
    problems += [f"ERC {k} x{n}" for k, n in res["erc"].items() if k not in ERC_OK]
    problems += [f"DRC {k} x{n}" for k, n in res["drc"].items() if k not in DRC_OK]
    if res["unconnected"]:
        problems.append(f"{res['unconnected']} unconnected")
    if res["parity"]:
        problems.append(f"{res['parity']} schematic parity issues")
    if res["unrouted"]:
        problems.append(f"unrouted {res['unrouted']}")
    if max(res["bbox"]) > 100.0:
        problems.append(f"outline {res['bbox']} exceeds 100 x 100 mm")
    if res["anchor_vias"] < 40:
        problems.append(f"only {res['anchor_vias']} anchor vias around the underside plane")
    if res["top_side_parts"]:
        problems.append(f"parts on the top side: {res['top_side_parts']}")
    if any(res["cam_rc"]):
        problems.append("Gerber/drill export failed")
    return problems


def main(argv):
    if "--overwrite" not in argv:
        print(__doc__)
        return 2
    bad = 0
    for v in ("analog",):
        res = board.build(v, cam="--no-cam" not in argv)
        problems = check(res)
        n_parts = sum(len(r[-1]) for r in res["bom"])
        cost = sum(r[4] * len(r[-1]) for r in res["bom"])
        print(f"[{v}] {n_parts} parts, {len(res['bom'])} BOM lines, about ${cost:.2f} per board; "
              f"heater {res['lanes']} lanes, R20 {res['r20']:.2f} ohm, min gap {res['min_gap']:.3f} mm")
        print(f"[{v}] " + ("ALL CHECKS PASSED" if not problems else "PROBLEMS: " + "; ".join(problems)))
        bad += len(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
