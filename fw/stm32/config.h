/*
 * Board and tuning constants for the USB-C PCB hot plate (STM32C011F4P6).
 *
 * Units used throughout the firmware (all integers):
 *   temperature   m°C (int32)        voltage   mV        current  mA
 *   resistance    0.1 mΩ ("x")       duty      0..PWM_STEPS
 *   time          PWM periods (40 ms) unless the name says _MS
 */
#ifndef CONFIG_H
#define CONFIG_H

/* ------------------------------------------------------------------ control */
#define SETPOINT_MC             100000  /* plate set-point */
#define PI_KP_PERMILLE_PER_K    250     /* Kp = 0.25 duty/K */
#define PI_KI_PERMILLE_PER_KS   12      /* Ki = 0.012 duty/(K s) */
#define EST_TAU_MS              20000   /* T_R is pulled towards the NTC with this time constant */
#define AT_TEMP_ENTER_MK        2000    /* "at temperature" once within this of the set-point ... */
#define AT_TEMP_LEAVE_MK        5000    /* ... until it falls this far below it */

/* ------------------------------------------------- PWM and sampling schedule */
#define PWM_HZ                  25
#define PWM_STEPS               1000    /* duty resolution, 1 step = 40 us */
#define PWM_PERIOD_MS           40
#define TICK_US                 40      /* PWM_PERIOD_MS * 1000 / PWM_STEPS */

#define ADC_OVERSAMPLE          8       /* scans of the 4 channels summed per sample window */
#define ON_SAMPLE_TICK          50      /* ON window starts 2.0 ms after turn-on */
#define OFF_SAMPLE_TICK         955     /* OFF window starts 1.8 ms before the period ends */
#define SAMPLE_TICKS            25      /* a window lasts < 1.0 ms (8 x 4 x 28.8 us + overhead) */
/* the ON window is valid if the heater stays on until it has ended (+0.2 ms) */
#define ON_VALID_MIN_DUTY       (ON_SAMPLE_TICK + SAMPLE_TICKS + 5)
/* the OFF window is valid if the heater went off at least 0.6 ms before it */
#define OFF_VALID_MAX_DUTY      (OFF_SAMPLE_TICK - 15)
#define PWM_MIN_PULSE           5       /* no on or off time shorter than 0.2 ms (edges take 15 us) */
#define MEAS_PULSE_DUTY         (ON_VALID_MIN_DUTY + 5)  /* 3.4 ms measurement pulse */
#define MEAS_INTERVAL           25      /* insert a pulse this often when the duty is too small */
#define OFF_INTERVAL            25      /* insert an OFF window this often at (near) full duty */
#define TR_STALE_PERIODS        50      /* T_R older than this is not used */

/* ------------------------------------------------------------ analog front end */
#define ADC_NCH                 4
#define ADC_CH_NTC1             0       /* PA0 */
#define ADC_CH_ISENSE           1       /* PA1 */
#define ADC_CH_VSENSE           2       /* PA2 */
#define ADC_CH_NTC2             3       /* PA3 */
#define ADC_VREF_MV             3300    /* VDDA */
#define ADC_FULL_SCALE          (4095 * ADC_OVERSAMPLE)

#define VSENSE_DIV_NUM          11      /* (100k + 10k) / 10k */
#define VSENSE_DIV_DEN          1
#define ISENSE_MV_PER_A         1000    /* 20 mΩ shunt x gain 50 */
#define ISENSE_ZERO_MAX_MA      100     /* largest zero-current reading accepted as amplifier offset */
#define ISENSE_MIN_MA           150     /* below this no resistance is computed / heater counts as open */

/* NTC 100 k, B25/50 3950, to GND; 22 k to 3V3. The table itself is in src/ntc_table.h
 * (tools/gen_ntc_table.py); these two limits are on the divider ratio, 0..65535. */
#define NTC_OPEN_Q16            65000   /* above: open (R > 2.6 MΩ, colder than -35 C) */
#define NTC_SHORT_Q16           1300    /* below: shorted (R < 450 Ω, hotter than 230 C) */
#define NTC2_AGREE_MK           10000   /* second NTC is used only while within this of NTC1 ... */
#define NTC2_AGREE_PERIODS      50      /* ... for this long */

/* ----------------------------------------------------------------- heater */
#define HEATER_R20_NOM_MOHM     9000    /* nominal; +-12 % board to board */
#define HEATER_R20_ACCEPT_PCT   20      /* a probe result further off is a sensing or heater fault */
#define CU_ALPHA_PPM            3930    /* copper TCR at 20 C, ppm/K */
#define CU_INV_ALPHA_MK         254453  /* 1 / alpha, mK */
#define CAL_MAX_T_MC            45000   /* R0/T0 is trusted for control only if captured below this */
#define CAL_PULSES              4       /* measurement pulses averaged for R0 */
#define CAL_SPACING             5       /* periods between them */
#define CAL_TIMEOUT             75      /* give up after 3 s and run without T_R */

/* ----------------------------------------------------------- charger (HUSB238) */
#define PD_I2C_ADDR             0x08
#define PD_BOOT_WAIT            38      /* 1.5 s for the PD chip to negotiate by itself */
#define PD_RETRY_WAIT           13      /* 0.5 s between attempts to read the offers */
#define PD_READ_TRIES           4
#define PD_QUIET_PERIODS        3       /* heater off this long before a voltage request */
#define PD_CONFIRM_TIMEOUT      38      /* 1.5 s for the new voltage and the PD response */
#define PD_STABLE_PERIODS       5       /* VSENSE in tolerance this long counts as settled */
#define PD_CURRENT_MARGIN_PCT   108     /* offer must cover 1.08 x V / R20 */
#define PD_VSENSE_TOL_PCT       6       /* requested voltage confirmed within this */
#define PROBE_SPACING           8       /* periods between R probe pulses */
#define PROBE_TIMEOUT           75      /* 3 s */
#define VBUS_MIN_NO_PD_MV       8500    /* without PD data: heat only above this */
#define WEAK_BELOW_MV           11000   /* selected voltage below this: "weak charger" */

/* -------------------------------------------------------------- protections */
#define NTC_FAULT_PERIODS       5       /* NTC1 open/short for 0.2 s */
#define OT_NTC_MC               125000  /* over-temperature on the NTC */
#define OT_TR_MC                135000  /* over-temperature on the trace */
#define OT_PERIODS              3
#define SHORT_MA                300     /* current with the switch off */
#define SHORT_SAMPLES           5       /* consecutive OFF windows */
#define XCHECK_MK               25000   /* |T_R - T_NTC| */
#define XCHECK_PERIODS          250     /* 10 s */
#define NORISE_DUTY             900     /* no-rise check (only without T_R): >= 90 % duty ... */
#define NORISE_PERIODS          2250    /* ... for 90 s ... */
#define NORISE_MK               2000    /* ... with less than 2 K rise ... */
#define NORISE_VBUS_MV          11000   /* ... while VBUS is at least this */
#define OC_ABS_MA               3200    /* absolute over-current limit */
#define OC_CONTRACT_PCT         105     /* limit relative to the contract current */
#define OC_SAMPLES              2
#define OC_MAX_EVENTS           2       /* second over-current event latches the fault */
#define OPEN_SAMPLES            3       /* ON windows without current: heater open */
#define OPEN_MIN_VBUS_MV        4000
#define VBUS_LOW_PCT            88      /* VBUS allowed range relative to the selected voltage */
#define VBUS_HIGH_PCT           108
#define VBUS_FAULT_PERIODS      5
#define EMERGENCY_5V_MV         6000    /* after a 5 V request VBUS should fall below this */

#define LOG_PERIODS             25      /* one UART line per second */

#define MS_TO_PERIODS(ms)       (((ms) + PWM_PERIOD_MS - 1) / PWM_PERIOD_MS)

#endif /* CONFIG_H */
