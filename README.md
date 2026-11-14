# USB-C PD PCB heater

<p align="center">
  <img src="docs/heater_top.webp" width="49%" alt="Top of the heater board: the flat work surface, with the heater trace under solder mask and the six break-off legs at the sides">
  <img src="docs/heater_underside.webp" width="49%" alt="Underside of the heater board: the bare copper plane with the two temperature sensors, and the electronics, USB-C socket and trimmer on the tail">
</p>
<p align="center"><em>Top (the work surface) and underside, as the board comes from the fab with its six break-off legs still attached. 3D renders of the KiCad board.</em></p>

A 70 × 70 mm hot plate that is nothing but a circuit board. Plug in a USB-C PD charger, set the temperature with a trimmer, and the board heats itself with its own copper trace and holds between 43 and 121 °C. There is no firmware: two comparator chips do the work.

> [!WARNING]
> **No board has been built or tested yet.** Every temperature, time and power figure here comes from the project's own models. The surface gets hot enough to burn, there is no thermal fuse, and the design is for attended use only.

## At a glance

| | |
|---|---|
| **Heated area** | 70 × 70 mm, completely flat: every part is on the underside |
| **Board** | 94 × 100 mm, 2-layer FR-4 TG135, 1.6 mm, lead-free HASL; sized for JLCPCB's cheapest tier |
| **Power** | USB-C PD, up to 20 V and 2.2 A (44 W cold) |
| **Temperature** | 43 to 121 °C by trimmer; 98.5 to 104 °C at the 100 °C setting (model) |
| **Heat-up** | 25 to 99 °C in 34 s at 20 V with nothing on the plate (model) |
| **Control** | Comparator thermostat with two LM393, no firmware |
| **Safety net** | A second sensor and comparator chip: at 138 °C they switch the heater off and make the charger drop to 5 V |
| **Parts** | 32 fitted, 15 BOM lines, about $1.27 per board, each with an LCSC number |
| **Legs** | Six FR-4 legs snap off the same board and solder into slots, leaving 8 mm of air underneath |

## Which charger does what

The PD chip takes the highest voltage that the charger offers at 2.5 A or more.

| Charger | Board runs at | Heater power | Reaches (model) |
|---|---|---|---|
| 60 W and up | 20 V | 44 W | the whole range; 100 °C in 34 s |
| 45 W (15 V / 3 A) | 15 V | 25 W | the whole range; 100 °C in 75 s |
| 12 V at 2.5 A or more | 12 V | 16 W | about 111 °C; 100 °C in about 3 min |
| 25 to 30 W (9 V at 2.5 A or more) | 9 V | 9 W | about 83 °C |
| 18 to 20 W | 5 V | 2.8 W | about 49 °C |

The top of the board carries the short form: `45W 120C, 25W 80C, 18W 50C`.

## How it works

- **Heater.** 6.9 m of top-layer copper in 106 lanes under solder mask, 9 Ω. The trace is narrower towards the edges, where the plate loses more heat.
- **Underside.** A bare tinned copper plane spreads the heat and radiates less towards the table than a masked one.
- **Sensing.** Two NTCs sit underneath, each tied by vias to a copper bar that runs between the heater lanes on top.
- **Thermostat.** One comparator switches the heater through a MOSFET. A trimmer sets the temperature; clockwise is hotter.
- **Limiter.** The second sensor has its own comparator chip and reference. At 138 °C it holds the heater off and pulls the PD chip down to 5 V, which cuts the power 16-fold even if the switch has failed short.
- **Thermal break.** The electronics sit on a tail that is joined to the hot zone only by two narrow FR-4 links.

The full description, with the resistor values, the dial scale and the fault behaviour, is in [docs/design.md](docs/design.md).

## Making one

1. Open `hw/analog/analog.kicad_pro` in KiCad 10 and export the fabrication files with the Fabrication Toolkit plugin.
2. Correct three rows of the placement file (the PD chip's rotation and two part positions).
3. Order from JLCPCB: 2 layers, 1.6 mm, 1 oz copper, lead-free HASL, assembly on the bottom side.
4. Solder what was left off the order, then snap off the six legs and solder them into their slots.
5. Turn the trimmer fully anticlockwise, check for shorts, and plug in.

Each step is spelled out in [hw/README.md](hw/README.md).

## Limits to know

- **Hot surface.** Up to 121 °C in normal use. With a failed switch or sensor the limiter cycles the plate between 125 and 142 °C until the board is unplugged.
- **Live surface.** Solder mask is the only insulation over a trace that sits at up to 20 V. Put polyimide tape on top before placing metal objects.
- **Socket above its rating.** The USB-C socket is rated 5 V and 3 A by its maker and runs at up to 20 V here, a deliberate cost choice.
- **Untested.** The list of what was checked and what was not is in [docs/design.md](docs/design.md#what-is-not-verified).

## Repository

| Path | What |
|---|---|
| [`hw/`](hw/README.md) | The KiCad 10 project and footprints, and the guide to ordering, assembly and first power-up |
| [`docs/design.md`](docs/design.md) | The design in detail and its unverified points |
| [`calc/`](calc/README.md) | Thermal model and control model behind the figures |
| [`sim/`](sim/README.md) | Three KiCad / ngspice simulation projects of the controller |
| [`gen/`](gen/README.md) | The Python generator the board started from; kept as a record, not to be run on the project |
| [`DEVELOPMENT.md`](DEVELOPMENT.md) | How the design got here: decisions, dead ends, mistakes |
