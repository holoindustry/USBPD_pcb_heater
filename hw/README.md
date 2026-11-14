# Hardware: KiCad project, ordering, building

## What is here

| Path | What |
|---|---|
| `analog/analog.kicad_pro` | The KiCad 10 project. The schematic is one A3 sheet drawn in functional groups; the board is routed by hand |
| `analog/analog_erc.json`, `analog_drc.json`, `analog.net` | ERC and DRC reports and the netlist of the files as they are (written 2026-11-14) |
| `lib/fable.pretty/` | Project footprints: the heater trace, leg, leg slot, mouse bite, tooling hole, trimmer |

Not kept in git, because they are outputs or downloads:

- `analog/production/`: the order files that the export below writes.
- `lib/fable.3dshapes/`: STEP models of the USB-C socket and the trimmer. Without them KiCad's 3D view shows the board without those two parts. They are EasyEDA's models of LCSC parts C283540 and C118910.
- Renders, Gerber folders, the schematic PDF and KiCad's backups.

The schematic and the board are edited by hand. Do not run the generator in [`gen/`](../gen/README.md) on them.

## Exporting the order files

In KiCad's board editor run the Fabrication Toolkit plugin (JLC-Plugin-for-KiCad). It writes `analog/production/`:

- `analog.zip`: Gerbers and drill files
- `bom.csv`: 15 lines, 32 parts
- `positions.csv`: the placement file, which needs the three corrections [below](#placement-file-corrections)

The export of 2026-11-14 15:05 was compared with a fresh plot of the board, layer by layer and hole by hole, and is identical. Export again after any change to the board.

## Ordering the PCB

| Setting | Value |
|---|---|
| Layers / size | 2 / 94 × 100 mm |
| Material | FR-4 TG135 |
| Thickness | 1.6 mm |
| Copper | 1 oz (this sets the heater resistance) |
| Surface finish | HASL, lead-free |
| Remove order number | Yes. The board carries no `JLCJLCJLCJLC` text; add one on the underside to use "Specify a location" instead |

Add a remark to the order: the bare copper underside of the heater zone is intentional, and the six pieces beside it are legs of the same board. The fab note that says so is on the User.Comments layer, which is not in the zip.

Two things decide the price and are not settled by this design:

- Recent reports say the $2 price is tied to JLCPCB's desktop app, with about $4 on the web.
- The six legs hang on mouse-bite tabs. JLCPCB may treat that as a panel and add a fee.

The quote page shows both once the Gerbers are uploaded.

## Assembly at JLCPCB

The board fits JLCPCB's Economic assembly: 2 layers, 1.6 mm, lead-free HASL, parts on one side, 0.5 mm smallest pin pitch.

| Order setting | Value |
|---|---|
| PCBA type | Economic |
| Assembly side | Bottom |
| PCBA quantity | 2 or 5 |
| Tooling holes | Added by Customer (four 1.152 mm holes: two in the bottom corners of the tail and one in the first leg on each side) |
| BOM file | `analog/production/bom.csv` |
| CPL file | `analog/production/positions.csv` with the three corrections below |
| Confirm Parts Placement | Yes ($0.45) |

### Placement file corrections

The plugin's `positions.csv` has three wrong rows:

| Part | Column | In the file | Correct | What happens otherwise |
|---|---|---|---|---|
| U1 (PD chip) | Rotation | 90 | 0 | The chip sits a quarter turn off, its pins not on their pads |
| J1 (USB-C socket) | Mid Y | -147.5 | -146.18 | The socket is placed 1.3 mm too far towards the board edge |
| U2 (regulator) | Mid X | 65.25 | 65.92 | Pins 1 and 3 overlap their pads by only about 0.3 mm |

- **How they were found:** LCSC's own footprint of each polarised part was placed at the file's position and rotation, and its pins compared with the board's pads. Q1, U3, U4, D1 and RV1 land within 0.25 mm.
- **U1:** the plugin turns underside parts by 180° minus the KiCad angle, plus a correction from a table of footprint names. The table has `DFN-` and `UDFN-10` but nothing for this footprint, `WDFN-10-…`, so the 270° correction was not applied. In the preview, pin 1 belongs at the corner nearest C1.
- **J1:** KiCad's footprint anchor is 1.3 mm nearer the socket's mouth than the origin of LCSC's footprint for this socket.
- **U2:** the origin of LCSC's footprint is 0.67 mm from the body centre towards the three pins.
- **How sure:** the U1 rotation follows from the plugin's own rule as well as from the comparison. The J1 and U2 offsets assume that the origin of LCSC's footprint is JLCPCB's placement point; the placement preview shows whether that holds.
- **Every new export brings all three back.** To make the corrections stick, add these fields to the footprints: U1 `FT Rotation Offset` = `270`, J1 `FT Origin` = `Center` (this leaves J1 0.16 mm off, which the stakes take up), U2 `FT Position Offset` = `-0.67,0`. They are worked out from the plugin's code and have not been tried.

Check the placement preview before paying, U1, J1 and U2 in particular.

### Which parts to leave to hand soldering

`bom.csv` and `positions.csv` list all 32 fitted parts. Untick the ones you solder yourself in JLCPCB's parts step.

- **Extended parts** cost a $3.07 fee per type: the PD chip (U1), the USB-C socket (J1), the NTCs (RT1, RT2) and the trimmer (RV1). JLCPCB has no NTC and no six-contact USB-C socket among its basic or preferred parts.
- **The trimmer** is through-hole, which JLCPCB solders by hand at an extra charge.
- **R10** (3 MΩ, C23156) is extended. On 2026-11-11 JLCPCB marked it as preferred, which has no fee; the lookup of 2026-11-14 shows only "extended", so look for the fee in the quote.
- Everything else is a basic part. All 15 LCSC numbers were looked up on 2026-11-14: each is the intended part and in stock, the smallest stock being the PD chip with 17,680 pieces.
- Pads of unticked parts may still get solder paste and arrive with solder bumps. If J1's do, wick them flat before seating the socket.

### Cost

Estimate from JLCPCB's published fees (page updated 2026-10-22) and their parts library on 2026-11-11. `python3 gen/pcba.py` computes it from the generator's part list, which has one 100 nF capacitor less than the board and a socket that costs $0.16 more:

| | By hand: J1, RT1, RT2, RV1, 2 boards | By hand: J1, RT1, RT2, RV1, 5 boards | By hand: RV1 only, 2 boards | By hand: RV1 only, 5 boards |
|---|---|---|---|---|
| Setup | $8.18 | $8.18 | $8.18 | $8.18 |
| Stencil | $1.53 | $1.53 | $1.53 | $1.53 |
| Extended parts, $3.07 each | $3.07 | $3.07 | $9.21 | $9.21 |
| Soldering | $0.25 | $0.62 | $0.29 | $0.73 |
| Components | $2.06 | $5.15 | $2.52 | $6.30 |
| **Assembly total** | **$15.09** | **$18.55** | **$21.73** | **$25.94** |
| per assembled board | $7.54 | $3.71 | $10.86 | $5.19 |

Not in the table: the PCB itself (about $2 to $4 for five, more if the legs count as a panel), shipping and tax. A real quote for this board on 2026-11-11 had no X-ray charge for the DFN-10, so none is counted.

## Building

1. **Solder what the assembly left off**, all on the underside; `bom.csv` is the shopping list. R15 stays empty.
   - RV1 is through-hole: its pins come out on the work surface about 4 mm long, so cut them flush after soldering. Its three pads and the four grounded pads of the socket's stakes are the only bare metal on the work surface.
   - U1 is a 3 × 3 mm DFN whose only ground is the centre pad, so it needs hot air or a hot plate.
2. **Legs.** Snap off the six legs; each breaks at the heater edge. Nip or file the tab stub off. Push each tongue into a slot from the underside until the shoulders sit on the board, and solder both faces of the leg to the bare land. The tongue stops 0.1 mm below the top surface. Four slots are near the heater corners, two on the tail.
3. **Metal objects.** Put polyimide tape on the heater surface first: solder mask is the only insulation over a trace that sits at up to 20 V.

The legs, for reference: three on each side of the heater zone, each on one tab about 4 mm wide where it breaks, with a row of three 0.5 mm holes on the edge of the heater zone. A leg is 10 mm wide and holds the board 8.25 mm above the table; its 6.0 × 1.5 mm tongue goes into a plated slot of 7.4 × 1.9 mm. The tallest things underneath are the trimmer (4.9 mm) and a USB-C plug (about 4.9 mm below the board for a plug 6.5 mm thick).

## First power-up

1. Turn RV1 fully anticlockwise, the coldest setting (43 °C). Raise it afterwards.
2. Before plugging in, measure the heater between the VBUS pad and the drain of Q1, the pin that stands alone on one side of the transistor: 9 Ω ± 12 % is expected, since copper thickness varies.
3. Check that VBUS to GND and +3V3 to GND are not shorted. There are three test pads for this, labelled VBUS, GND and +3V3.
4. Plug in a PD charger. +3V3 should read 3.3 V and VBUS the voltage from the [charger table](../README.md#which-charger-does-what).
5. Watch the first warm-up with a thermocouple or a thermal camera. The LED is on while heating and starts to flicker once the plate is at temperature.
6. Test the limiter: warm RT2 with a soldering iron. VBUS must fall to 5 V and the LED go out, and both must come back as it cools.

## What was checked

On the board as saved on 2026-11-14 at 15:04 and the export of 15:05:

- **Rules:** ERC clean. DRC with no errors, nothing unconnected and schematic parity clean; the zone fills are current. The 17 warnings left are cosmetic: silkscreen over pads and at the socket's edge, one unused 3.3 V via under TP3, five VBUS track ends not centred on their vias.
- **Order files:** all nine Gerber layers and both drill files in the zip are identical to a fresh plot of the board made with the plugin's settings. The drill files hold 100 vias of 0.3 mm, three 0.8 mm trimmer holes, four 0.5 mm stake slots, six leg slots, 18 mouse-bite holes and four tooling holes.
- **BOM:** each of the 32 parts has the value and LCSC number that the board has; R15 is left out as not fitted.
- **Placement file:** 32 rows, all on the underside; three rows are wrong, as described above.
- **Heater current path:** no track narrower than 0.9 mm on the way in or 1.0 mm on the way out, and eight vias at each layer change.

On the board as saved at 11:04 the same day, not repeated after the small changes that followed (two tooling holes, a few tracks moved, the socket's part number):

- **Pinouts:** every pin of U1 to U4, Q1, D1 and J1 is on the net its datasheet calls for. The PD chip's tables give 2.5 A for the 16.6 kΩ on ISET and 20 V for an open VSET pin; its exposed pad (1.7 × 2.4 mm) fits the 1.8 × 2.5 mm land.
- **Ground pads:** three 0.5 mm spokes on each pad that carries the heater's return current.
- **Heater:** the footprint is unchanged from the library (9.0 Ω).
- **Mechanics:** the socket's mouth stands about 1 mm proud of the board edge, so a plug's body clears the board.
- **Sensors:** the NTC pads are surrounded by solder mask inside the bare underside.
- **Cosmetic, left as they are:** part designators are 0.8 mm tall with 0.12 mm strokes and may print faint; R9 and R13 overlap; the warning line on the top runs over the eight VBUS vias; the logo is clipped at two stake pads of the socket.

What could not be checked without a board is listed in [docs/design.md](../docs/design.md#what-is-not-verified).
