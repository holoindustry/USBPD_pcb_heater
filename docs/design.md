# The design in detail

How the heater works, part by part, and what has not been verified. For ordering and building see [hw/README.md](../hw/README.md); for the reasons behind each choice see [DEVELOPMENT.md](../DEVELOPMENT.md).

Every temperature, time and power figure is from the models in [`calc/`](../calc/README.md), not from measurements.

## Heater

106 vertical lanes of top copper under solder mask, 6.86 m long, 0.21 to 0.44 mm wide with 0.22 mm gaps: 9.0 Ω at 20 °C. The trace is narrower towards the edges and at the lane ends, which puts more heat where the plate loses more.

| At | Cold current | Cold power | Power at 100 °C | 25 to 99 °C, empty plate |
|---|---|---|---|---|
| 20 V | 2.2 A | 44 W | 34 W | 34 s |
| 15 V | 1.7 A | 25 W | 19 W | 75 s |
| 12 V | 1.3 A | 16 W | 12 W | 166 s |
| 9 V | 1.0 A | 9 W | 7 W | settles at about 83 °C |

Holding 100 °C takes about 10 W in still air.

**Evenness.** With the sensor at 100 °C and nothing on the plate, the inner 50 × 50 mm is within 97 to 101 °C and the inner 60 × 60 mm within 93 to 101 °C. The far corners, where the leg slots are, drop to about 89 °C.

## Underside

A solid copper plane with the solder mask removed (bare HASL). It spreads heat and radiates about 2.4 W less towards the table than a masked surface would. 42 anchor vias sit along its top, left and right edges, tied together by a thin ground ring on the top layer so that each via holds copper on both faces. The bottom edge carries the sense lines instead.

## Temperature sensing

The two NTCs (100 kΩ, B 3950, 1 %) are on the underside, but they follow the top copper: a copper bar in a channel between the two centre lanes of the heater is joined by four vias to a small island under each NTC, and each island is separated from the plane by a 1 mm gap. In the model an underside-only sensor lets the top copper swing 96 to 119 °C under on/off control; with the bar it stays within 98.5 to 104 °C.

## Thermal break

The heater zone is joined to the electronics tail only by two Z-shaped FR-4 links, 5 mm wide with about 23 mm of path. The heater feed and return run on top of them, a sensor signal and a ground trace underneath.

## Power input

- **Socket.** J1 is a six-contact, power-only USB-C socket (SHOU HAN TYPE-C 6P(073), C668623).
- **PD chip.** U1 (Hynetek HUSB238) walks the charger's offers from the highest voltage down and takes the first that can supply the current set on its ISET pin, 2.5 A. So the board never overloads a charger, but it asks for 2.5 A at every voltage. The datasheet value for 2.5 A is 16.5 kΩ; the board makes it from 22 k in parallel with 68 k (16.6 k), two values it already uses.
- **3.3 V rail.** U2 (Holtek HT7533-1) supplies about 1.5 mA. Its input and output capacitors are 1 µF 50 V 0603, the same part as the PD chip's capacitor, which keeps the capacitance on VBUS at 2 µF, inside the 10 µF that USB allows a device at plug-in. Holtek's application circuit draws 10 µF on both sides and states no minimum, so the 1 µF output capacitor is a choice, not a datasheet value: if the rail turns out noisy, a 10 µF 10 V 0603 (C19702) fits C3's pads.

**The socket runs above its stated voltage.** Its datasheet says 3.0 A and 5.0 V; this board puts up to 20 V and 2.2 A on it. That was accepted to save cost, on the reasoning that 5 V and 20 V are both low DC voltages; the sheet's insulation tests (100 V AC for one minute, 100 MΩ) are the same as on the maker's 20 V sockets. Sockets that JLCPCB lists for 20 V and that fit the same pads, should the choice be revisited (catalogue ratings, datasheets not read; stock on 2026-11-14):

| LCSC | Part | Price | Listed rating | Stock | Fit |
|---|---|---|---|---|---|
| C52711237 | HH 6P TYPE-C (Y026X) | $0.037 | 20 V, 3 A | 15,507 | Same pads and slots in LCSC's footprint; JLCPCB has no datasheet for it |
| C2798175 | USAKRO TYPE-C-6M-001 | $0.068 | 20 V, 3 A | 2,749 | Pads within 0.05 mm; its layout draws 0.6 mm wide slots |
| C22464426 | HRO TYPE-C-31-M-17A | $0.113 | 20 V, 5 A | 2,605 | Pads exact; its layout draws longer slots, 0.6 × 1.4 mm |
| C283540 | HRO TYPE-C-31-M-17 | $0.199 | 20 V, 5 A | 9,752 | Pads exact; the part the footprint and 3D model are named after |

## Controller

Two LM393 dual comparators (onsemi LM393DR2G) on the 3.3 V rail:

| Comparator | Job |
|---|---|
| U3 A | Thermostat on RT1. The trimmer RV1 sets the switch-off temperature between 43 and 121 °C; the heater comes back on 0.9 K below it. |
| U4 A | Limiter on RT2, an independent sensor: trips at 138 °C, resets at 127 °C. |
| U3 B | Limiter tripped: heater switch off. |
| U4 B | Limiter tripped: shorts the PD chip's VSET pin, which requests 5 V. Heater power drops 16-fold, even if the switch has failed short. |

- The thermostat and the limiter sit in different chips, so one failed comparator IC cannot take out both.
- RT1 and RT2 have separate reference dividers and leave the heater zone through different links, so no single open joint or trace in the sensor paths blinds both.
- The two limiter outputs take REF2, the limiter's own reference, as their threshold, not the set-point reference REF1. A fault that pulls REF1 to 0 V (an open joint at R6 or at RV1 pin 1, or the set-point net shorted to ground) therefore cannot stop them from acting.
- The switch is an AO3400A with a 22 k gate resistor. The gate edges take about 30 µs (an estimate from typical figures), slow enough to need no flyback diode.
- A yellow LED (D1) on the underside at the front of the tail is lit while the heater is energised. It shines down; from above its glow on the table shows through the gap between the tail and the heater zone.

**What a fault looks like.** With the switch shorted or RT1 open, or with REF1 pulled low, the thermostat asks for heat all the time. The limiter then cycles the top copper between 125 and 142 °C until the board is unplugged, at any trimmer setting. That is above the glass transition of TG135 FR-4 and above the 125 °C rating of the NTCs. It was accepted for the fault case, because the limiter has to sit above the 120 °C setting.

**Resistors.** The 15 fitted resistors are five values, all JLCPCB basic parts except the 3 M:

| Value | Where |
|---|---|
| 22 k | limiter NTC pull-up R5; limiter reference top R8; ISET R1; gate R2; pull-ups R12, R13, R14 |
| 68 k | thermostat NTC pull-up R3; limiter hysteresis R11; ISET R16 |
| 3.3 k | thermostat reference bottom R7; limiter reference bottom R9 |
| 4.7 k | thermostat reference top R6, in series with the trimmer RV1; LED R4 |
| 3 M | thermostat hysteresis R10 (C23156) |

R15 is not fitted. It is the 12 V option for small chargers: fit 10 k at R15 (the PD chip reads 10 kΩ on VSET as a 12 V limit), fit 4.7 k at R1 and leave R16 empty (asks for 1.5 A). The board is then a fixed 12 V / 16 W heater on any charger.

## Set point

RV1 is a 50 kΩ ± 10 % single-turn trimmer (BOCHEN 3362P-1-503, C118910, through-hole). It is wired as a variable resistor between R6 and the reference REF1, with the wiper tied to the clockwise end; R6 comes first, on the 3.3 V rail. Turning clockwise lowers REF1 and raises the temperature. If the wiper loses contact the full 50 kΩ stays in circuit, which is the hottest setting, not an open reference.

| Rotation | 0 % | 12.5 % | 25 % | 37.5 % | 50 % | 62.5 % | 75 % | 87.5 % | 100 % |
|---|---|---|---|---|---|---|---|---|---|
| Heater off above | 43 °C | 66 °C | 80 °C | 90 °C | 98 °C | 105 °C | 111 °C | 116 °C | 121 °C |
| REF1 (across R7) | 1.361 V | 0.764 V | 0.531 V | 0.407 V | 0.330 V | 0.277 V | 0.239 V | 0.210 V | 0.188 V |

- **Why R6 comes before the trimmer.** The trimmer's three pins come through to the work surface. With R6 first none of them is on the 3.3 V rail, so a metal object that bridges a pin to ground draws at most 0.7 mA through R6 instead of shorting the regulator, for which Holtek states no short-circuit protection. Such a bridge still pulls REF1 to 0 V, which ends in the fault behaviour above.
- **Dial.** Five labels around the trimmer on the underside (40, 80, 100, 110 and 120 °C) were placed by hand. Measured at their centres they sit within about 2 K of the nominal scale for the 240° adjustment angle of a 3362: the 80 label at 80 °C, 100 at 98 °C, 110 at 111 °C, and 40 and 120 at the two end stops (43 and 121 °C). For an exact setting use a multimeter on REF1 (the pads of R7) with the table, or a thermocouple on the plate.
- **Tolerances.** The coldest setting does not depend on the trimmer's tolerance. The hottest does: 117 °C with a trimmer 10 % low, 124 °C with one 10 % high, and up to 127 °C if the 1 % parts and the NTC are also at their limits. The top copper peaks about 5 K above the switch-off temperature. 100 °C is at 53.5 % of the travel.
- **Limiter margin.** The limiter's lowest worst-case trip is 134 °C, so it stays out of the way in normal use.
- **Charger.** The top of the range needs a 15 V or 20 V charger. At 12 V the heater's full power only brings the plate to about 111 °C.
- **Cold end.** R3 is 68 k to keep the reference low enough for the LM393 on a 3.3 V supply. Its input range is 1.8 V at 25 °C and 1.3 V guaranteed over its whole temperature range. REF1 is below 1.3 V for every setting above about 45 °C. In the last 1 % of the travel (43 to 45 °C) it reaches 1.36 V, which is inside the room-temperature range only: with the board in a cold room that setting may switch a few kelvin late or not heat. Turn the trimmer up slightly if that happens.
- **Other trimmer values** work with the same ratios, R6 = 0.094 × and R7 = 0.066 × the trimmer, between 10 k and 100 k. 50 k was kept because its R7 is the 3.3 k the limiter needs anyway, and R6 is 4.7 k because that is also the LED resistor's value.

## What is not verified

In rough order of risk:

- **Nothing has run on hardware.** The thermal and control numbers are from models.
- **HUSB238.** Its behaviour is taken from the datasheet. The limiter depends on the documented "request follows the VSET resistance while running".
- **Placement file for JLCPCB assembly.** The three corrections in [hw/README.md](../hw/README.md#placement-file-corrections) rest on LCSC's footprints, not on anything JLCPCB has confirmed; their placement preview is the first real check.
- **USB-C socket above its rating**, as described under "Power input".
- **USB-C socket stake slots.** They are 0.5 × 1.2 mm plated slots in 1.0 × 1.7 mm pads, which is what the socket's datasheet and LCSC footprint ask for. 0.5 mm is believed to be JLCPCB's minimum for a plated slot; that limit was not confirmed.
- **Trimmer footprint and range.** The footprint `fable:Potentiometer_3362P` is drawn from the Bourns 3362 datasheet (style P); the BOCHEN part is sold as the same package, but its own drawing was not available to check. Its pin positions agree exactly with LCSC's footprint for the BOCHEN part; the holes are 0.8 mm where LCSC's footprint has 0.9 mm. The temperature scale comes from nominal part values and the B-parameter NTC model.
- **3.3 V regulator with 1 µF on its output.** Smaller than the 10 µF of the datasheet's circuit; look at the rail with a scope on the first board.
- **Assembly price.** Computed from published fees, not quoted.
- **Mechanical fit taken from the footprint, not the datasheet:** the length of the USB-C shell stakes against the flat top.
- **LED visibility.** How well the downward glow shows from above has not been tried.
- **Attended use only.** There is no thermal fuse. A heater stuck on at 20 V with no limiter settles near 187 °C in the model; that is why the finish and solder should be lead-free.
