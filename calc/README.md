# Models

Two Python models produce every temperature, time and power figure quoted in this repository. Neither has been compared with a real board.

> [!NOTE]
> The scripts do not run from a bare clone. `thermal.py` imports `thermal_budget.py` (convection and radiation coefficients) from the parent project this repository was split from, and both scripts use `gen/heater.py` and `gen/parts.py`.

## `thermal.py`: the plate

```
python3 calc/thermal.py
```

- A 2-D steady-state map of the top surface, for evenness. It draws `calc/out/evenness.png`.
- A lumped transient model of the plate (`Plant`): top copper, FR-4, underside plane and the sensor's lag. The control model and the simulations use it.
- Assumed emissivities: 0.9 for the solder-masked top, 0.15 for the bare tinned underside.

| Result | Value |
|---|---|
| Power to hold 100 °C in still air | 10.2 W |
| 25 to 99 °C, empty plate | 34 s at 20 V, 75 s at 15 V, 166 s at 12 V |
| Full power at 9 V | settles at about 83 °C |
| Evenness with the sensor at 100 °C | inner 50 × 50 mm 97 to 101 °C; inner 60 × 60 mm 93 to 101 °C; far corners about 89 °C |
| Heater stuck on, no limiter | about 187 °C at 20 V, 49 °C at 5 V |
| Heat capacity of the plate | 17.1 J/K |

Questions it was used to settle:

| Question | Answer |
|---|---|
| Ground plane underneath, or not? | Without it the inner 60 × 60 mm spreads 88 to 109 °C instead of 93 to 101 °C, and holding 100 °C takes 12.9 W instead of 10.2 W |
| Bare tin or solder mask underneath? | Bare tin loses 2.5 W downwards instead of 4.8 W |
| 2.0 mm board instead of 1.6 mm? | Slower: 40 s instead of 34 s to 99 °C at 20 V |
| 1.2 mm or 1.0 mm? | Faster (27 s and 23 s) but 42 % and 24 % as stiff; not adopted |

## `control_sim.py`: thermostat and limiter

```
python3 calc/control_sim.py
```

It computes the switching temperatures from the actual resistor values (`THERMOSTAT`, `LIMITER`, `POT` at the top of the file), prints the trimmer scale, and runs the on/off control on the plate model. It draws `calc/out/control.png`. `analog_design()` is also what the generator reads its resistor values from.

Runs as printed on 2026-11-14 (top copper):

| Run | 99 °C after | Peak | Settled | Duty | Period |
|---|---|---|---|---|---|
| 20 V, 100 °C setting | 34 s | 105.8 °C | 98.6 to 104.0 °C | 29 % | 1.8 s |
| 12 V, 100 °C setting | 166 s | 101.4 °C | 98.6 to 101.4 °C | 82 % | 4.8 s |
| 20 V, hottest setting (121 °C) | 34 s | 125.5 °C | 119.0 to 124.4 °C | 43 % | 1.6 s |
| 15 V, hottest setting | 75 s | 122.8 °C | 119.0 to 122.6 °C | 75 % | 3.1 s |
| 20 V, coldest setting (43 °C) | never | 51.0 °C | 42.1 to 47.9 °C | 5 % | 7.5 s |
| 20 V, switch shorted | 34 s | 142.1 °C | 125.5 to 142.0 °C | 100 % | |
| 20 V, RT1 open | 34 s | 141.8 °C | 125.3 to 141.8 °C | 51 % | 17.1 s |

The last two are the fault cases: the limiter alone holds the plate, by dropping the charger to 5 V and back.

Thresholds from the resistor values: thermostat off at 100.0 °C and on at 99.1 °C with the trimmer at 53.5 %; limiter trips at 137.5 °C and resets near 127 °C, 134 to 141 °C in the worst case of 1 % resistors and a 1 % NTC.
