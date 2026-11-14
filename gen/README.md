# The generator

The Python scripts that produced the first versions of the board: the circuit as code, the schematic drawn from it, the board placed and routed from it, and the checks. The project in [`hw/analog/`](../hw/README.md) began as their output on 2026-11-11 and has been edited by hand since.

> [!CAUTION]
> Do not run `gen/build.py --overwrite` or `gen/sheets.py --overwrite` on this project. They replace the hand-routed board and the hand-edited schematic with a generated version that is older and does not pass DRC. Without the flag both scripts print a warning and do nothing. Work on a copy.

They are kept as the record of how the board was made, and because other parts of the repository use pieces of them: the heater geometry, the part table, the cost estimate and the schematic drawing engine.

## What it needs

- KiCad 10 with its `pcbnew` Python module and `kicad-cli`.
- The circuit, placement and routing toolkit of the parent project (`../gen/eda/` beside this repository's folder). It is not part of this repository, so the scripts do not run from a bare clone.

## Files

| File | What |
|---|---|
| `build.py` | Entry point: regenerates the project library and `hw/analog/`, then checks ERC, netlist, DRC, heater resistance and outline |
| `circuits.py` | The circuit as code: every part with its nets, part number and position |
| `sheets.py`, `schematic.py` | How the schematic is drawn (groups, symbol positions, wires, notes), and the engine that refuses a drawing whose wires do not give exactly the circuit's nets |
| `board.py`, `pcbkit.py` | The board builder (library footprints, outline, heater zone, placement, power copper, routing, pours, silkscreen) and its pcbnew helpers |
| `geom.py`, `heater.py` | Board dimensions; the heater trace generator (lanes, width grading, resistance) |
| `parts.py`, `jlc_parts.json` | Part numbers and prices; JLCPCB's price, stock and class for each, read on 2026-11-11 |
| `pcba.py` | JLCPCB assembly estimate from the part list and the board's pad count; `--refresh` re-reads the parts data |

## Where the generator's board differs from the real one

The generator still describes the circuit of the morning of 2026-11-14. The hand-edited project has moved on:

| | Generator | `hw/analog/` |
|---|---|---|
| Set-point divider | trimmer on the 3.3 V rail, then R6 | R6 on the rail, then the trimmer |
| Heater-return net | `HTR_N` | `HEAT` |
| Test pads | five (VBUS, GND, +3V3, GATE, HTR-) | three (VBUS, GND, +3V3) |
| Decoupling | C5 only | C5 and C7 |
| USB-C socket | HRO TYPE-C-31-M-17 | SHOU HAN TYPE-C 6P(073) |
| Legs and outline | eight legs, 97 × 98 mm | six legs, 94 × 100 mm |
| Tooling holes | two | four |
| Layout | generated; the trimmer has no legal place, 7 DRC errors | routed by hand, DRC clean |

## Schematic conventions

The schematic is one A3 sheet, drawn in functional groups with wires between the pins. Power nets use power symbols; a local label only names a wire. The board's net names follow the schematic: a labelled net is `/NAME` on the PCB, and an unlabelled one has the name KiCad derives from a pin, such as `Net-(U1-ISET)`.

## Cost estimate

```
python3 gen/pcba.py            # table for 2 and 5 boards
python3 gen/pcba.py --refresh  # first re-read prices, stock and class from JLCPCB
```

It only reads the project. Its part list is the generator's, so it has one 100 nF capacitor less than the real board and the older, dearer socket. The table is in [hw/README.md](../hw/README.md#cost).
