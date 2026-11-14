# Simulating the controller

Three KiCad projects for KiCad's built-in SPICE simulator (ngspice). Open one, then Inspect → Simulator → Run. All use the board's references and values; parts that are not on the board are numbered from 101.

| Project | What it shows | What it assumes |
|---|---|---|
| `manual/manual.kicad_pro` | The control circuit alone. The two NTCs are trimmers (RT1, RT2: resistance = position × 100 kΩ) that you turn in the simulator like the set-point trimmer RV1; each change runs 40 ms and shows whether the heater is on and the limiter tripped. | Stock models only (below). No plate, no PD chip, no regulator. |
| `loop/loop.kicad_pro` | Closed loop, 150 s: the control circuit heats a thermal model of the plate from room temperature. Temperatures are plotted in volts (100 V is 100 °C). | The plate model of `calc/thermal.py`, the NTC's B-parameter law, a stand-in for the PD chip, a comparator model written for this project. |
| `thresholds/thresholds.kicad_pro` | Open loop, 30 s: the plate temperature is a ramp, 10 °C per second up to 150 °C and back, so the switching points can be read off the time axis. | As `loop`, without the plate. |

> [!IMPORTANT]
> `loop` and `thresholds` are not an independent check. They are built from the same plate numbers, NTC law and assumed PD-chip behaviour as the Python model in [`calc/`](../calc/README.md), so agreement shows only that the numbers were carried over correctly. Only `manual` stands on stock models, and it checks the arithmetic of the switching points, nothing more.

The wiring of all three matches the board schematic except in two places: the simulations still have the trimmer on the 3.3 V rail with R6 after it, and the heater-return net under its old name HTR_N. Two resistors in series give the same REF1 in either order, so the results stand.

## The manual project

- **Models:** KiCad's own resistor, capacitor, trimmer and DC source. The comparator is the long-circulated LM393 macromodel (header "created using PARTS version 4.03 on 03/07/90"), used unchanged in `models/LM393.sub`; its origin could not be confirmed, the copy is from a public GitHub repository. The switch is a SPICE level-1 MOSFET with six numbers from the typical values of the AO3400A data sheet. `models/stock.lib` holds only that and the wiring of two comparators into one package.
- **Temperature:** the simulation knows resistances, not temperatures. The sheet lists the NTC's nominal resistance for a few temperatures (100 kΩ at 25 °C, B = 3950 K) as an aid.
- **History:** KiCad reruns the simulation from scratch at every change, so a run cannot remember the previous setting. Each run starts as if the plate had just been colder (C4 and C6 start charged), which shows where things switch while warming up. Set `ic=0` in the simulation model of C4 and C6 to see where they switch back while cooling down.
- **Not simulated:** what the PD chip does when VSET is pulled low (R102 is only a pull-up so that the output shows a level), the 3.3 V regulator, the plate, the LED.
- **Result (ngspice 45 on the netlist KiCad exports):** the heater switches off below 6977 Ω and on again above 7140 Ω at RT1, the limiter trips below 2654 Ω and resets above 3413 Ω at RT2. From the resistor values alone the figures are 6975, 7144, 2652 and 3428 Ω.

Why these models:

- **TI's current LM393 model does not fit this circuit.** It runs in ngspice, but drives the output to half the supply whenever either input is above VCC − 2 V. That is this circuit's normal state, and the onsemi data sheet says the output stays correct there.
- **Gear integration is needed with the macromodel.** With ngspice's default method its open-collector outputs alternate between about −0.4 V and 7 V from one time step to the next. The schematic carries `.options method=gear`.
- **ngspice's power-MOSFET model (VDMOS) is not used here.** With the AO3400A's values it stopped with "timestep too small" at the heater's turn-off edge in roughly one run in 200; the level-1 model did not in over 1600.

## The loop and thresholds projects

- **Things to change with the Tune tool:** RV1 (the trimmer's travel, 0 to 1), V101 (charger voltage), V102 (the 3.3 V rail), V103 (room temperature). R105 = 0.01 shorts the switch; R103 = 6.8M puts an object on the plate.
- **Stand-ins:** a 3.3 V source for the regulator, and a source for the charger and PD chip that gives 5 V while the limiter holds VSET low, about 0.1 s late (the real chip's delay is not specified).
- **Plate:** the numbers of `calc/thermal.py` as an RC ladder, with 1 V = 1 °C, 1 µA = 1 W, 1 MΩ = 1 K/W and 1 µF = 1 J/K.
- **Models:** `models/heater_sim.lib`, written for this project. The LM393 is a behavioural comparator with offset, bias current and input range as parameters; the AO3400A is ngspice's power-MOSFET model fitted to the data sheet's typical values.
- **Input range at the coldest setting:** set `vhead=2.0` on U3 (its simulation model parameters) to see the comparator at the cold end of its temperature range. With the trimmer at 0 the heater then switches off at 45 °C instead of 43 °C, or does not heat at all with `oor=0`; at 100 °C nothing changes. What the real part does with both inputs above its range is not specified, so this shows the two possibilities that were programmed in, not a prediction.
- **Result (ngspice 45, 2026-11-13):** 14 cases of the closed loop (trimmer at five positions, 12, 15 and 20 V, shorted switch, object on the plate, 10 and 35 °C room), each with and without recording all currents, all ran to the end in 1 to 3 s. They agree with `calc/control_sim.py`: 99 °C after 34 s and 98.5 to 103.9 °C at the 100 °C setting, 125 to 142 °C with the switch shorted, thresholds at 100.0 / 99.1 °C and 137.5 / 126.4 °C.

## Redrawing the projects

`make_sim.py` draws the three schematics, and `--check` reruns the checks above. It refuses to overwrite an existing schematic unless called with `--force`, so changes made in KiCad are safe. It needs the parent project's schematic toolkit, which is not in this repository; opening and running the projects in KiCad needs nothing but KiCad.

Not checked for any of the three: they have not been opened in KiCad's simulator window itself, only run through `kicad-cli` and ngspice.
