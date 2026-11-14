#!/usr/bin/env python3
"""JLCPCB assembly (PCBA) cost estimate for the analog board.

    python3 gen/pcba.py                 estimate for 2 and 5 assembled boards
    python3 gen/pcba.py --refresh       first re-read prices, stock and basic/extended class
                                        from JLCPCB's parts library into gen/jlc_parts.json
    python3 gen/pcba.py --md            the table in Markdown

The fees are JLCPCB's published Economic PCBA prices (help page "PCB Assembly Cost", last
updated 2026-10-22). The real quote appears after uploading the Gerber zip, the BOM and the
placement file; shipping, tax and the PCB itself are not in this estimate.
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import circuits  # noqa: E402
import parts as P  # noqa: E402
import pcbkit as K  # noqa: E402

API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"

# Economic PCBA, USD
SETUP = 8.18
STENCIL = 1.53
FEEDER = 3.07            # per extended part type
JOINT = 0.0016
CONFIRM = 0.45           # optional "Confirm Parts Placement"
# JLCPCB's fee page also lists X-ray inspection for leadless packages ($1.64 per part); a real
# quote for this board on 2026-11-11 did not charge it for the DFN-10, so it is not counted.


def fetch(code):
    body = json.dumps({"currentPage": 1, "pageSize": 25, "keyword": code, "searchSource": "search",
                       "componentAttributes": []}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json",
                                                          "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    for it in ((d.get("data") or {}).get("componentPageInfo") or {}).get("list") or []:
        if it.get("componentCode") == code:
            return dict(mpn=it.get("componentModelEn", ""), brand=it.get("componentBrandEn", ""),
                        package=it.get("componentSpecificationEn", ""),
                        type="basic" if it.get("componentLibraryType") == "base" else "extended",
                        preferred=bool(it.get("preferredComponentFlag")), stock=it.get("stockCount", 0),
                        prices=[[p["startNumber"], p["productPrice"]] for p in it.get("componentPrices") or []])
    return None


def refresh():
    codes = sorted({v[1] for v in P.ICS.values()} | {v[1] for v in P.PASSIVES.values()})
    out = {"fetched": time.strftime("%Y-%m-%d"), "parts": {}}
    for code in codes:
        rec = fetch(code)
        if rec is None:
            print(f"  {code}: not in JLCPCB's parts library")
            continue
        out["parts"][code] = rec
        time.sleep(0.3)
    with open(os.path.join(HERE, "jlc_parts.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"{len(out['parts'])} of {len(codes)} parts read from JLCPCB, {out['fetched']}")
    P._jlc = None


def joints(variant):
    """Solder pads per reference, counted on the built board."""
    import pcbnew
    bd = pcbnew.LoadBoard(os.path.join(ROOT, "hw", variant, f"{variant}.kicad_pcb"))
    return {fp.GetReference(): sum(1 for pad in fp.Pads() if pad.GetNumber() and pad.IsOnCopperLayer())
            for fp in bd.GetFootprints()}


def estimate(variant, boards, by_hand=()):
    """Fee items for `boards` assembled boards; the references in by_hand are left unpopulated."""
    rows = K.bom_rows(circuits.make(variant))
    pads = joints(variant)
    n_ext = n_parts = n_joints = 0
    cost = 0.0
    missing = []
    for val, fp, mpn, lcsc, price, src, refs in rows:
        refs = [r for r in refs if r not in by_hand]
        if not refs:
            continue
        rec = P.jlc(lcsc)
        qty = len(refs) * boards
        if not rec or rec["stock"] < qty:
            missing.append(f"{mpn or val} ({lcsc})")
        if rec.get("type", "extended") == "extended" and not rec.get("preferred"):
            n_ext += 1
        n_parts += len(refs)
        n_joints += sum(pads.get(r, 2) for r in refs)
        cost += P.unit_price(lcsc, qty, price) * qty
    items = [("Setup", SETUP), ("Stencil", STENCIL), (f"Extended parts, {n_ext} x ${FEEDER}", n_ext * FEEDER),
             (f"Soldering, {n_joints} joints per board", n_joints * boards * JOINT),
             (f"Components, {n_parts} per board", cost)]
    return dict(items=items, total=sum(v for _, v in items), n_ext=n_ext, n_parts=n_parts, n_joints=n_joints,
                missing=missing, per_board_parts=cost / boards)


def main(argv):
    if "--refresh" in argv:
        refresh()
    if not P.jlc()["parts"]:
        sys.exit("no gen/jlc_parts.json yet: run  python3 gen/pcba.py --refresh")
    variant = "analog"
    hand = circuits.HAND_SOLDERED.get(variant, ())
    tht = tuple(r for r in hand if r.startswith("RV"))       # through-hole: not part of the SMT estimate
    cases = [(f"{', '.join(hand)} soldered by hand (the JLCPCB files in hw/{variant}/ are made for this)", hand),
             (f"every surface-mount part placed by JLCPCB ({', '.join(tht)} by hand)", tht)]
    cols = [(name, n, estimate(variant, n, skip)) for name, skip in cases for n in (2, 5)]
    md = "--md" in argv
    if md:
        print("| | " + " | ".join(f"{'By hand: ' + ', '.join(skip)}, {n} boards"
                                  for (_, skip), n in ((c, n) for c in cases for n in (2, 5))) + " |")
        print("|---|" + "---|" * len(cols))
        for k, lab in enumerate(("Setup", "Stencil", f"Extended parts, ${FEEDER} each", "Soldering", "Components")):
            print(f"| {lab} | " + " | ".join(f"${e['items'][k][1]:.2f}" for _, _, e in cols) + " |")
        print("| **Assembly total** | " + " | ".join(f"**${e['total']:.2f}**" for _, _, e in cols) + " |")
        print("| per assembled board | " + " | ".join(f"${e['total'] / n:.2f}" for _, n, e in cols) + " |")
        return
    print(f"JLCPCB Economic PCBA estimate, {variant} board (parts library read {P.jlc()['fetched']})\n")
    for name, skip in cases:
        sub = [(n, e) for nm, n, e in cols if nm == name]
        print(name + ":")
        print(f"  {'':40s}" + "".join(f"{f'{n} boards':>12s}" for n, _ in sub))
        for k in range(len(sub[-1][1]["items"])):
            print(f"  {sub[-1][1]['items'][k][0]:40s}" + "".join(f"{e['items'][k][1]:12.2f}" for _, e in sub))
        print(f"  {'assembly total, USD':40s}" + "".join(f"{e['total']:12.2f}" for _, e in sub))
        print(f"  {'per assembled board':40s}" + "".join(f"{e['total'] / n:12.2f}" for n, e in sub))
        e = sub[-1][1]
        print(f"  {e['n_parts']} parts per board, {e['n_ext']} extended part types, {e['n_joints']} joints; "
              + ("all in stock" if not e["missing"] else "NOT ENOUGH STOCK: " + ", ".join(e["missing"])) + "\n")
    print(f"Not included: the PCB (5 pieces, from about $2-4), optional 'Confirm Parts Placement' ${CONFIRM}, shipping, tax.")
    print("Extended part types:")
    for val, fp, mpn, lcsc, price, src, refs in K.bom_rows(circuits.make(variant)):
        rec = P.jlc(lcsc)
        if rec.get("type") == "extended":
            print(f"  {','.join(refs):8s} {mpn:22s} {lcsc:10s} stock {rec['stock']:>8d}  ${P.unit_price(lcsc, 1):.3f}")


if __name__ == "__main__":
    main(sys.argv[1:])
