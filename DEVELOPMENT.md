# Development history

`README.md` and the documents it links describe the heater as it is now. This file is the long version of how it got there: what was asked, what was tried, what was thrown away, which numbers moved and why, and what went wrong along the way. It covers 10 to 14 November 2026. Times are local (CET). Nothing described here has been built or powered: every temperature, time and power figure is from the project's own models.

The project was worked on in one long session between the owner and an AI assistant (Claude). "The assistant" below means that; "the owner" is the person who asked for the board, routed it by hand and made the decisions.

## Timeline

| When | What |
|---|---|
| 10 Nov, evening | Brief, questions, first plan rejected, revised plan approved |
| Night 10–11 Nov | Rev A generated: two boards, thermal and control models, STM32 firmware |
| 11 Nov, morning | Analog board chosen; BOM cut to standard values and basic parts (rev B); buck regulator tried and dropped; assembly cost estimated |
| 11 Nov, afternoon | Schematic redrawn in wired functional groups; regulator capacitors reduced to 1 µF |
| 11 Nov, evening | Owner starts routing the analog board by hand; outline converted to lines and arcs; thickness, ground plane and bare tin discussed; 10 k resistors become 22 k |
| Night 11–12 Nov | NTC alternatives compared; Sunlord part adopted |
| 12 Nov, evening | Trimmer added for an adjustable set point; limiter moved up to 138 °C; 3D models added |
| 13 Nov, after midnight | R6 changed from 6.2 k to 4.7 k |
| 13 Nov, night and morning | SPICE simulation projects built; their independence questioned; a third, stock-model project added |
| 14 Nov, night | Review of the routed board; REF1 safety gap found and closed; anchor vias restored; dial added and reverted |
| 14 Nov, morning | R6 moved ahead of the trimmer; pre-order check |
| 14 Nov, afternoon | USB-C socket replaced by a cheaper one; final export checked; pictures made for the repository |
| 14 Nov, evening | STM32 variant removed from the repository; documentation split into per-folder files |

## 1. The brief and the plan (10 November)

The request, in the owner's words: "a simple pcb heater thats pcb can be ordered for 2 bucks from jlcpcb, it gets usb-c power, heats and maintains 100C while plugged in, has a simple and inexpensive bom and can be hand soldered by a skilled person with good tools, has high power to heat up objects put on top of it, doesnt conduct much heat downwards (maybe some legs)".

The parent folder already held a complex modular preheater and a 4-layer proof of concept with 40 BOM lines. This project was to be the simple take: one 2-layer board from JLCPCB's cheapest tier.

Three questions were put to the owner before planning:

- **Controller:** "lets try analog and stm32 too, to see how big difference it makes in bom count and bom price". This is why there are two variants.
- **Heated area:** 70 × 70 mm.
- **Legs:** snap-off FR-4 pieces cut from the same board.

The first plan was rejected with four points, each of which shaped the design:

| Owner's point | What it became |
|---|---|
| "if you have a solid plane, use vias on the edge of the board to anchor the plane against delamination" | Anchor vias around the underside plane |
| "i like the ntc idea but cant we infer temperature from the heater copper trace resistance?" | Added to the STM32 variant only: a 20 mΩ shunt and a current-sense amplifier let the MCU compute R = V/I. Not practical on the analog board, which would need a division and a per-board trim. The NTC stays as the absolute reference because copper thickness varies about ±10 % |
| "its better for the components to be only on the underside, the legs anyway lift them" | Every part on the underside, including the USB-C socket; the top is flat |
| "can variant A work also with 12V? some PD chargers might only support that" | The PD chip changed from CH224A to HUSB238, whose datasheet documents walking the charger's offers from the highest voltage down with a current check. The heater went from 8 Ω to 9 Ω (44 W at 20 V instead of 50 W) so that lower voltages fit weaker chargers |

The revised plan was approved. Its method: generate everything from Python (`gen/`), so that ERC, a netlist cross-check, DRC, the thermal model and the control simulation can all be rerun, because nothing could be bench-tested before ordering.

## 2. First build, rev A (night of 10–11 November)

Both boards were generated, 97 × 98 mm, 2 layers, 1.6 mm, 1 oz, lead-free HASL.

- **Heater:** a serpentine of 106 lanes on the top copper under solder mask, 6.86 m long, 0.21 to 0.44 mm wide, graded narrower towards the edges and lane ends; 9.00 Ω at 20 °C, re-computed independently from the saved boards.
- **Sensing:** NTCs on the underside, coupled to the top copper by a pickup bar in a channel between the two centre lanes and four vias per sensor to a small island.
- **Underside:** a ground plane with the mask removed (bare HASL) and 54 anchor vias on its perimeter.
- **Thermal break:** two Z-shaped links between heater zone and tail.
- **Legs:** eight snap-off pieces (six used, two spare) on mouse-bite tabs, six plated slots.
- **Analog variant:** one LM339 quad comparator (thermostat, limiter, limiter-to-gate, limiter-to-VSET), E96 resistor values. 28 parts, 20 BOM lines, about $1.34.
- **STM32 variant:** STM32C011F4P6, shunt and INA180, PI control at 25 Hz, fault codes, UART log. 25 parts, 19 BOM lines, about $2.09. The firmware (`fw/stm32/`) was written by a delegated agent and checked afterwards: 7.5 KB of flash, 30 host tests passing against a plant and charger model.

Model results that have stayed valid since: 10.2 W to hold 100 °C, 25 to 99 °C in 34 s at 20 V, 75 s at 15 V, 166 s at 12 V, about 83 °C at 9 V, a stuck-on heater settling near 187 °C at 20 V and 49 °C at 5 V.

Problems met while building the generator:

- **Anchor vias vanished.** The router's clean-up removed them as dangling vias. A thin ground ring on the top layer through the via centres fixed it, and the build now checks that at least 40 exist.
- **Multi-unit symbols.** The toolkit could not place a four-unit LM339, so a flat symbol was drawn for it (replaced later by KiCad's stock symbols).
- **J1 came out rotated wrong**, leg pads overlapped, and the reverse-mount LED's pads were too close to its hole. All three were fixed in the generator.
- **ERC complaints** about the undriven VSET pin and the I2C pins led to R15 (not fitted, the 12 V option) and R14 (idle pull-up).
- **STM32 routing failed** until the MCU and debug pads moved left and the VBUS feed went to the top layer.

Deviations from the plan, reported at the time: anchor vias only on the plane's outer perimeter (the heater trace runs above the internal cut-outs); one more part than estimated on the analog board and two more on the STM32 board.

## 3. Choosing the analog board and cutting the BOM (11 November, morning)

The owner picked the analog version and sent a list: standard resistor values, 100 nF instead of 10 nF, an LCSC number on every part, a JLCPCB assembly cost, a cheaper LM339 (C71036), one row of mouse bites, and for the 3.3 V rail a buck regulator and inductor they had in stock (C780769, C5832358).

- **Buck regulator, tried and dropped.** It was implemented (AP63203 plus a 2.2 µH inductor): 33 parts, 16 lines, $2.94 a board, and an assembly estimate of about $55 for five. An hour later: "actually you were right, lets go back to the 3v3 HT7533, its cheap and basic". The buck code and parts were removed.
- **Comparator.** The owner asked whether a basic part would suit. The only basic comparator at JLCPCB was the LM393 (onsemi LM393DR2G, C7955), a dual. The assistant replaced the LM339 with two LM393 without waiting to be asked; the owner did not object. A side effect worth keeping: thermostat and limiter sit in different chips.
- **LED.** A basic yellow 0805 (C2296) on the underside replaced the reverse-mount LED, which removed the last hole in the top of the analog board.
- **Standard values.** The E96 values went. The ISET resistor (datasheet 16.5 k for 2.5 A) became 22 k in parallel with 68 k. Thermostat 100.0 / 99.1 °C, limiter 124.1 / 112.2 °C.
- **Mouse bites.** One row of three 0.5 mm holes per tab on the heater edge, so the stub stays on the leg: 48 holes instead of 96.
- **Tooling holes.** Two 1.152 mm holes in the tail for JLCPCB's assembly line.
- **Prices.** From here on prices are JLCPCB's parts-library prices for one piece, not the older LCSC snapshots of rev A. That alone moved the STM32C011 from $0.73 to $1.47.

The owner asked whether there was an alternative PD chip. None is a basic part. CH221K (C5125736, $0.30), CH224A (C42459160, $0.43) and HUSB237 (C22373734, $0.24) all lack the HUSB238's ISET current check. Decision: "lets keep the husb238, its a good chip".

The owner also tried a real quote: "luckily no xray fee, i tried; and to be efficient i will probably solder the ntcs and the usbc port by hand". So X-ray was taken out of the estimate, and J1, RT1 and RT2 were left out of the generated JLCPCB files. Assembly estimate then: $15.54 for two boards, $19.68 for five.

A question in passing, "why is there 8 legs for 6 legholes?": two were spares.

This state is rev B: 30 parts, 15 BOM lines, $1.52.

## 4. Schematic redrawn (11 November, afternoon)

"oragnize the schematic better, put components of one logical group into proximity with each other and draw wires between connection points instead of labels".

Two new generator files did this: `gen/schematic.py` (a drawing engine that checks the drawn wires against the circuit by connectivity, then runs KiCad's ERC and compares the exported netlist) and `gen/sheets.py` (the layouts). Each sheet became one A3 page in functional groups, with power symbols and a handful of local labels. The LM393 became KiCad's stock multi-unit symbol. The board's net names now follow the schematic (`/NTC1`, `/REF1`, `Net-(U1-ISET)`).

## 5. Regulator capacitors (11 November, afternoon)

"with our LDO supplying so low current, do we need such big in out caps?" The rail carries about 1.5 mA. The 10 µF 50 V 1206 parts cost $0.127 each and put 11 µF on VBUS, above the 10 µF USB allows at plug-in. Holtek's datasheet draws 10 µF on both sides and states no minimum. The assistant recommended 10 µF 10 V 0603 on the output; the owner chose "lets use 1 uf for in an out too", the same part as C1. C3 was moved right next to the regulator's pins. 14 BOM lines, $1.28. The 1 µF output capacitor has been on the "not verified" list ever since.

## 6. Hand routing begins (11 November, evening)

"i started hand routing the layout". The owner asked for one thing only: replace the polygon board outline with lines and arcs so it can be edited by hand. Ten polygons became 148 lines and 90 arcs, with an identical render and DRC result.

From this point the analog schematic and board are the owner's files. Consequences that still hold:

- `gen/build.py analog` and `gen/sheets.py analog` must never be run; they would overwrite the hand work.
- When the assistant changed those files it did so by narrow text edits on a copy, checked ERC, DRC and the netlist, confirmed KiCad had the file closed, and only then installed the result.
- The generator's analog outputs in `hw/analog/` (Gerbers, position files, renders) stopped describing the board.

What the owner changed by hand over the following days, as found in the files: all generated tracks removed and every part moved; the two spare legs deleted; a 100 nF capacitor C7 added; later the legs redrawn (six, one tab each, the outline now 94 × 100 mm), the trimmer moved to the underside, three test pads kept and two dropped, the net HTR_N renamed HEAT, a title, a warning line and a logo on the top, dial labels and `v1` underneath, and two more tooling holes.

## 7. Questions that changed nothing (11 November, evening)

Model runs made to answer questions, with no change to the design:

| Question | Answer from the model |
|---|---|
| 2.0 mm instead of 1.6 mm? | Slower: 40 s instead of 34 s to 99 °C at 20 V, and JLCPCB's Economic assembly only takes up to 1.6 mm. Stay at 1.6 mm |
| 1.2 or 1.0 mm for faster heat-up? | 27 s and 23 s at 20 V; stiffness falls to 42 % and 24 %. The assistant recommended 1.2 mm (which would need narrower slots and tongues); the owner never took it up |
| Why a ground plane underneath? | Without it the inner 60 × 60 mm spreads 88 to 109 °C instead of 93 to 101 °C, and holding 100 °C takes 12.9 W instead of 10.2 W |
| Why bare tin instead of mask? | Assumed emissivity 0.15 against 0.9: 2.5 W lost downwards instead of 4.8 W |

## 8. 10 k becomes 22 k (11 November, late)

"i think we can replace 10k resistors with 22k or 4.7k". The gate resistor and three pull-ups became 22 k, which removed the 10 k part from the order (13 lines, $1.29). Gate edges went from about 15 µs to about 30 µs, an estimate from typical AO3400A figures. The limiter moved 1 K down to 123 °C. R15 stayed 10 k because the PD chip reads 10 kΩ on VSET as a 12 V limit. This was the first change made by text edit to the hand-routed files.

## 9. NTC choice (night of 11–12 November)

- C338607 (Fenghua, ±5 %): rejected; the thermostat's worst case would widen to 95 to 106 °C.
- C919169 (Sunlord SDNT1608X104F3950FTF, ±1 %, B ±1 %, rated to 125 °C, $0.015): a like-for-like replacement at half the price of the KUU part. The owner put it into the fields by hand.

## 10. Adjustable set point (12 November, evening)

"can we easily modify the design with a potmeter to adjust temperature between 50 and 120 degrees?"

The first answer was a 48 to 109 °C range that left the limiter at 123 °C. Reaching 120 °C needs the limiter above it. The owner decided: "we are going to use FR4 TG135, so we have some headroom for swings, a 138 limiter is fine, a normally working device will not reach that anyway". What that accepts: in a simulated fault the top copper peaks at 142 °C and cycles between 125 and 142 °C, above the glass transition of the board and above the 125 °C rating of the NTCs.

The values that came out of it:

- R3 (NTC pull-up) 22 k to 68 k, to keep the reference inside the LM393's input range on a 3.3 V supply.
- R6 6.2 k in series with a 50 k trimmer in the top leg of the reference divider, R7 3.3 k.
- R9 3.3 k: limiter trips at 137.5 °C and resets near 127 °C.
- R10 (hysteresis) 3 M. The assistant had proposed 3.3 M, which is an extended part; the owner pointed out that the 3 M part C23156 is "promotional extended", which carries no fee.

Other trimmer values would work with the same ratios (10 k, 20 k, 100 k). 50 k was kept because its R7 is the 3.3 k the limiter needs anyway. The owner chose C118910, a BOCHEN 3362P-1-503. Its footprint was drawn from the Bourns 3362 datasheet because the BOCHEN drawing could not be downloaded.

"why is the trim pot wired in parallel with itself": the wiper is tied to one end so that a wiper losing contact leaves the full 50 k in circuit (the hottest setting, still regulated) and not an open reference.

Result: 50 to 122 °C, 31 parts, 16 BOM lines, $1.42. The trimmer joined the hand-soldered parts.

## 11. 3D models (12 November, late)

KiCad shipped no model for the USB-C socket or the trimmer, and the PD chip's footprint named a file that did not exist. EasyEDA's STEP models for LCSC parts C283540 and C118910 were fetched by part number and placed by matching pin positions to pads; the PD chip got KiCad's own 3 × 3 mm DFN-10 model. They live in `hw/lib/fable.3dshapes/`.

## 12. R6 = 4.7 k (13 November, after midnight)

"how would the temp characteristic change with R6=4.7k": the range becomes 43 to 121 °C and the scale shifts by about 3 % of the travel. 4.7 k is already the LED resistor's value, so the 6.2 k line disappears: 15 BOM lines. "lets make the switch". The NTC fields that still named the old KUU part were cleaned up at the same time. A follow-up about 3.3 k was curiosity only.

## 13. Simulation (13 November)

"i would like to run some spice simulations of the circuit ... preferably with a gui". KiCad's built-in simulator (ngspice) was chosen because the schematic already lives in KiCad. `sim/make_sim.py` draws the projects.

First came two projects: `loop` (the controller heating a thermal model of the plate) and `thresholds` (a temperature ramp). They agreed with the Python model: 99 °C after 34 s, 98.5 to 103.9 °C at the 100 °C setting, thresholds at 100.0 / 99.1 °C and 137.5 / 126.4 °C.

Then the owner asked: "is there a risk that you built and customized heavily the simulation around assumptions that they are not independent verifications?" Yes. Both projects use the same plate numbers, the same NTC law, the same assumed PD-chip behaviour and a comparator model written for the purpose. Agreement shows that numbers were copied correctly, nothing more.

So a third project, `manual`, was built on the owner's specification: stock models only, with the two NTCs as trimmers that are turned by hand like the set-point trimmer. It knows resistances, not temperatures. Finding stock models took three attempts:

- **TI's current LM393 model** runs in ngspice but drives the output to half the supply whenever either input is above VCC − 2 V. That is this circuit's normal state, and onsemi's datasheet says the output stays correct there. Unusable here.
- **onsemi's own model** was downloaded with the owner's approval and turned out to be encrypted for Cadence tools.
- **The long-circulated LM393 macromodel** (header dated 1990) is what the project uses, unchanged. Its origin could not be confirmed.

What `manual` independently confirms is the arithmetic of the switching points: 6977 / 7140 Ω at RT1 and 2654 / 3413 Ω at RT2, against 6975 / 7144 and 2652 / 3428 Ω from the resistor values alone. It says nothing about the plate or the PD chip.

ngspice lessons that cost time, kept here so they are not learned twice:

- The macromodel needs Gear integration; with the default method its outputs alternate between about −0.4 V and 7 V from step to step.
- ngspice's power-MOSFET model (VDMOS) failed with "timestep too small" at the turn-off edge in about one run in 200; a level-1 MOSFET did not in over 1600.
- A behavioural comparator converged only as a tanh gain stage feeding a switch with hysteresis; an ideal voltage source into a small resistor, or an `? :` expression, did not.
- Starting from an operating point with a supply ramp worked where `uic` hung.
- KiCad reruns from scratch at every tuner change, so a run cannot remember the previous setting.

One slip: while adding `manual`, the assistant regenerated the other two projects with `--force`. It said so, and the script now takes a project name.

## 14. Board review and the REF1 gap (14 November, night)

"check the current state of the pcb, not just drc and automatic things, but give me real feedback or opportunities for improvement". The routed board was reviewed by reading it, not only by running checks.

The serious finding was in the circuit, and it was the assistant's own design error from rev B. The two limiter outputs (U3B to the gate, U4B to VSET) used REF1, the thermostat's set-point reference, as their threshold. A fault that pulled REF1 to 0 V turned the heater on and at the same moment stopped both limiter outputs from acting. Earlier the assistant had told the owner that an open reference "would be caught by the limiter". That was wrong; it found the error itself during this review, confirmed it in simulation and said so plainly.

The owner's answers to the review, point by point:

| Point | Decision |
|---|---|
| Limiter outputs on REF1 | Move them to REF2, the limiter's own reference. The owner routed it by hand the same night |
| Both sensor grounds share the pickup bar | Not a concern: a fault there would likely take the heater trace with it. The stub was widened to 0.8 mm |
| Anchor vias gone after hand routing | "add back the 42 anchor vias". Done by script: 42 vias on the top, left and right edges plus the top-layer ring. The first attempt broke edge clearance at the rounded corners and was chamfered |
| VBUS copper under the USB shell, insulated by mask only | "its fine, modern soldermask is reliable" |
| Trimmer on the underside | Fine |
| Board 100 mm tall | Fine |
| Test points | Undecided then; three were added later |
| Top silkscreen | Title changed to 40C–120C; fab note corrected |

A dial with tick marks was also proposed and added, then removed within the hour: "revert just the silkscreen dial, it looks uneven and confusing". In the same exchange the assistant claimed the owner's five hand-placed labels were 4 to 9 K off. That was a measuring mistake (text anchors instead of the centres of the text); the real error is about 1 to 2 K.

What the REF2 change leaves: a fault on REF1 still makes the thermostat ask for heat all the time, and the limiter then cycles the plate around 125 to 142 °C until the board is unplugged.

## 15. R6 ahead of the trimmer (14 November, morning)

The owner's idea: "what if we bring forward R6 in front of the trim pot, this way the tht hole of the trim pot wouldnt be on 3v3", and the reason: "so that there is no possibility of accidentally shorting 3v3 to gnd by putting someting larger and metallic on the heated topside". The trimmer is through-hole, so its three pins are bare metal on the work surface.

Asked which failure is more benign: R6 first. A bridge from a pin to ground then draws at most 0.7 mA and cannot short a regulator that states no short-circuit protection. The same bridge still pulls REF1 low, which ends in the limiter cycling described above. The owner made the change. The switching points did not move, since two resistors in series give the same divider in either order.

The owner then put the charger table on the board as `45W 120C, 25W 80C, 18W 50C`.

## 16. Pre-order check (14 November, 11:00)

"do a final check, before ordering it, leave no stone unturned". Done on a read-only copy of the board as saved at 11:04.

Found in order:

- ERC, DRC and schematic parity clean; the production Gerbers identical to a fresh plot.
- Every chip pin on the net its datasheet calls for; all 15 LCSC numbers the intended parts and in stock.
- Heater current path, sensor pads, connector overhang, leg clearance: fine (figures in `hw/README.md`).
- **The placement file was wrong in three rows.** The method: take LCSC's own footprint of each polarised part, place it at the file's position and rotation, and compare its pins with the board's pads.
  - U1, the PD chip, would be placed a quarter turn off. The export plugin corrects rotations from a table keyed on footprint names; it has `DFN-` and `UDFN-10` but nothing for `WDFN-10-…`.
  - J1 and U2 would be placed 1.3 mm and 0.67 mm off, because KiCad's footprint anchors differ from the origins of LCSC's footprints.
- The README still told the reader to upload the generator's old Gerber zip.
- The `JLCJLCJLCJLC` text for the order number was no longer on the board.
- The production files listed the four parts the plan had soldered by hand.

Two statements from that report were later weakened: that pads of unticked parts "still get paste" (the assistant is not certain JLCPCB does that), and a doubt about the 0.5 mm stake slots, which turned out to be exactly what the replacement socket's datasheet asks for.

The owner asked for the README to be brought up to date, and only the README. The generator and the simulations were left as they were.

## 17. The USB-C socket (14 November, afternoon)

"the usb-c connector looks needlessly expensive, C668623 for example is a replacement candidate". The HRO TYPE-C-31-M-17 cost $0.199.

- **C668623** (SHOU HAN TYPE-C 6P(073), $0.039): the same pad pattern, and its datasheet layout has exactly the board's 0.5 × 1.2 mm stake slots. But its datasheet, read with the owner's approval, rates it at 3.0 A and 5.0 V.
- **C30167326** (SHOU HAN, $0.059, 20 V): its stake rows are 3.64 mm apart instead of 3.80 mm. Not a fit without changing the footprint.

The assistant recommended keeping the HRO part. The owner decided otherwise: "lets go with C668623, 5v and 20v are both low dc, should have similar characteristics", and asked for a look at other alternatives too. JLCPCB lists 227 six-contact USB-C sockets; none is a basic or preferred part. Three are listed for 20 V and fit the pads (in `docs/design.md`), the closest being C52711237 at the same price but with no datasheet. None was clearly better, so C668623 went in: five fields of J1 in the schematic and the board. The footprint and the 3D model keep the HRO name.

Two things to be honest about here. The socket runs above its stated voltage, by the owner's choice. And the assistant downloaded the second candidate's datasheet without having asked for that file specifically; it said so afterwards.

## 18. Final export (14 November, 15:05)

Between the pre-order check and the last export the board was saved three more times: by the owner at 14:13 (two more tooling holes, one in the first leg on each side; the `v1` mark and some tracks moved), by the assistant at 14:34 (the socket's fields) and by the owner at 15:04 (R1 and R16 nudged by 0.25 mm, with their tracks).

The export of 15:05 was checked against the board saved at 15:04:

- All nine Gerber layers and both drill files are identical to a fresh plot made with the plugin's own settings.
- ERC clean; DRC with no errors, nothing unconnected, parity clean, zone fills current.
- BOM: 15 lines, 32 parts, matching the board, J1 now C668623, R15 left out as not fitted.
- Placement file: 32 rows, all on the underside, and the same three rows wrong as before, because the footprint fields that would correct them were not added. A corrected copy, `positions_corrected.csv`, was written next to the original with only those three cells changed.

## 19. Pictures for the repository (14 November, 16:20)

The owner put the project under git and asked for two pictures in the README that show well on a GitHub page. The README's old pictures were the generator's renders of 11 November, which no longer showed the board, and the repository's `.gitignore` leaves out every PNG, so they would not have appeared on GitHub at all.

Two new renders were made from the hand-routed board as saved at 15:04, top and underside, each tilted 35° with the tail towards the viewer:

```
kicad-cli pcb render --side top    --perspective --rotate -35,0,-18 --zoom 0.74 --quality high --background transparent --width 1800 --height 1600 -o top.png    analog.kicad_pcb
kicad-cli pcb render --side bottom --perspective --rotate -35,0,18  --zoom 0.74 --quality high --background transparent --width 1800 --height 1600 -o bottom.png analog.kicad_pcb
```

They were cropped to the board, centred on equal square canvases and saved as `docs/heater_top.webp` and `docs/heater_underside.webp` (1000 × 1000 px, transparent background, 178 and 132 KB). WebP was chosen over PNG for two reasons: the same pictures as PNG were 860 and 715 KB because of the fine heater pattern, and WebP files are not caught by the ignore rule. They sit at the top of the README, side by side.

## 20. The STM32 variant leaves the repository (14 November, 17:00)

After the first commit the owner asked for the STM32 version to be cleaned out: "it will stay in the history and can be mentioned in the dev md, but the readme and repo structure should concentrate on the analog version". It was never built and had not been touched since 11 November.

What it was:

- **Controller.** STM32C011F4P6 (C5452432), bare-metal C firmware of 7.5 KB, flashed over SWD with an ST-Link.
- **Charger choice.** It read every offer from the HUSB238 over I2C, measured the heater, and picked the highest voltage whose current covered it with 8 % margin. So it worked on anything offering 16 W at 12 V or more, where the analog board needs 2.5 A at whatever voltage it takes.
- **Sensing.** A 20 mΩ shunt and an INA180 (1 V/A) plus a VBUS divider gave the heater's resistance, and with it the average trace temperature with no lag (copper, +0.393 %/K). The NTC calibrated that at each cold start and corrected it slowly.
- **Control.** PI with 25 Hz PWM: 101 °C steady in the model, against the analog board's 98.5 to 104 °C.
- **Faults.** Six codes blinked on the LED: NTC open or short, over-temperature, current with the switch off, trace and NTC disagreeing or no temperature rise, over-current, heater open or of the wrong resistance. Two of them also requested 5 V. An independent watchdog and a pull-down on the gate covered a hung or resetting MCU.
- **Log.** One UART line per second with state, voltage, current, heater resistance, temperatures and duty.
- **Board.** Generated, never hand-routed: 97 × 98 mm, eight legs, a reverse-mount LED shining up through a hole. 25 parts, 18 BOM lines, $2.85.
- **Tests.** 30 host tests ran the firmware logic against a thermal and charger model (charger selection on five chargers, tolerances, every fault path, a load step, a warm start). The register-level layer compiled but never met the chip.

The comparison it was built for, as it last stood:

| | Analog | STM32 |
|---|---|---|
| Parts to solder | 31 | 25 |
| BOM lines | 15 | 18 |
| Parts cost per board | $1.42 | $2.85 |
| Firmware and programmer | none | yes, ST-Link |
| Set point | 43 to 121 °C, trimmer | 100 °C, in the firmware |
| At the 100 °C setting (model) | 98.5 to 104 °C, switching every 2 s | 101 °C steady |
| Chargers | 45 W and up for full function | anything offering 16 W at 12 V or more |

What was removed:

- `hw/stm32/` (the KiCad project and its reports) and `fw/stm32/` (the firmware, its tests and the CMSIS headers).
- The STM32 branches of `gen/circuits.py`, `gen/sheets.py` and `gen/board.py`, its parts in `gen/parts.py` and `gen/jlc_parts.json`, the PI controller in `calc/control_sim.py`, the comparison script `gen/compare.py`, and the reverse-mount LED footprint in `hw/lib/`.
- With the folders went their untracked outputs, which the ignore rules had kept out of git anyway: the firmware build, the STM32 Gerbers and zip, renders, the schematic PDF and one KiCad backup.

All tracked files are in commit `79c551a` ("initial commit of the release candidate"); `git checkout 79c551a -- fw hw/stm32 gen calc` brings the variant back as it was.

Two things were done so that the removal could not hurt the analog board:

- **The generator was compared before and after.** It was run for the analog board on a scratch copy with the old code and with the stripped code: the schematic, the BOM and the library footprints came out byte for byte the same, and the board the same part for part and track for track.
- **The generator can no longer run by accident.** With the STM32 variant gone, the only thing `gen/build.py` and `gen/sheets.py` can do is replace the hand-edited analog files, and that same test run showed that the generator's own layout fails DRC with seven errors, because the trimmer has no legal place in it. Both scripts now print a warning and stop unless called with `--overwrite`.

The three report files in `hw/analog/` (`analog_erc.json`, `analog_drc.json`, `analog.net`) were still the generator's from days earlier; they were replaced by reports of the current files, and the netlist no longer carries a local path.

## 21. Documentation split (14 November, 17:30)

In the same request: "make the readme concise and nice looking, if more md style docs are needed, split them to the specific parts of the repo into a separate md". The README had grown to 370 lines. It is now a one-screen overview with the pictures, a table of key figures, the charger table, six bullets on how it works and five steps to make one. The detail moved next to what it describes:

| File | Holds |
|---|---|
| `docs/design.md` | The design part by part, the dial scale, the fault behaviour, the socket's rating, and the list of what is not verified |
| `hw/README.md` | Exporting, ordering, assembly at JLCPCB with the placement corrections and the cost table, building, first power-up, and what was checked |
| `calc/README.md` | The two models and their results |
| `sim/README.md` | The three simulation projects |
| `gen/README.md` | The generator, the warning not to run it, and where its board differs from the real one |

Writing them for a reader on GitHub brought out two things that the single README had glossed over. The generator, the thermal model and the simulation drawing script import a toolkit from the parent project, so they do not run from a bare clone. And the order files, the 3D models and the plots are outputs that the ignore rules keep out of git, so the documents now say how to produce them instead of pointing at files that are not there.

## How the numbers moved

| State | Parts | BOM lines | Parts cost | Thermostat off / on | Limiter trip / reset |
|---|---|---|---|---|---|
| Rev A, LM339, E96 values (LCSC prices) | 28 | 20 | $1.34 | 100.7 / 99.8 °C | 124.7 / 112.7 °C |
| With the buck regulator | 33 | 16 | $2.94 | | |
| Rev B, two LM393, standard values (JLCPCB prices from here) | 30 | 15 | $1.52 | 100.0 / 99.1 °C | 124.1 / 112.2 °C |
| 1 µF regulator capacitors | 30 | 14 | $1.28 | | |
| 22 k pull-ups | 30 | 13 | $1.29 | 100.0 / 99.1 °C | 123.0 / 112.2 °C |
| Trimmer, R6 = 6.2 k | 31 | 16 | $1.42 | 50 to 122 °C | 137.5 / 126.8 °C |
| R6 = 4.7 k | 31 | 15 | $1.42 | 43 to 121 °C | 137.5 / 126.8 °C |
| Hand-routed board with C7 and the SHOU HAN socket | 32 | 15 | about $1.27 | 43 to 121 °C | 137.5 / 126.8 °C |

The STM32 variant went from 25 parts, 19 lines and $2.09 (LCSC prices) to 25 parts, 18 lines and $2.85 (JLCPCB prices, 1 µF input capacitor) and has not been touched since 11 November.

## Mistakes and corrections

Collected in one place, because they are the most useful part of a history:

- **Limiter outputs referenced to the set point** (rev B to 14 November): a single fault could turn the heater on and disable the limiter. The assistant's design error, and its wrong assurance about it. Closed by moving pin 6 of U3 and U4 to REF2.
- **Simulations presented as checks** before their dependence on the same assumptions was spelled out. Corrected after the owner's question; the README says which project is independent of what.
- **Dial label error overstated** by measuring text anchors.
- **Two simulation projects regenerated** when only one was meant to be added.
- **Placement rotations.** The generator's own rule for underside parts and the plugin's table both looked plausible; neither was compared with the assembler's footprints until the pre-order check.
- **A comparator swap made without being asked** (LM339 to two LM393). It turned out well.
- **Buck regulator.** Built at the owner's request against the assistant's earlier advice, then dropped.
- **Anchor vias lost twice:** once to the generator's clean-up, once to hand routing.

## Left open

- Board thickness of 1.2 mm for faster heat-up: recommended by the model, never decided.
- `gen/circuits.py`, `gen/sheets.py` and the three simulation projects still describe the analog circuit as of the REF2 change. They lack R6 ahead of the trimmer, the net name HEAT, the reduced test pads and the new socket. The simulations' results are unaffected.
- The generator's analog layout with the trimmer has never been built.
- The STM32 variant was never built; it left the repository on 14 November (section 20).
- Everything on the "not verified" list in `docs/design.md`, first of all that no board exists yet.
