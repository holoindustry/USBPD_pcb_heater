/*
 * Interface between the hardware-independent logic (src/) and whatever runs it:
 * the MCU layer (mcu/board.c) or the host simulation (test/sim.c).
 *
 * The platform calls app_step() once per PWM period with the samples of that period.
 */
#ifndef HAL_H
#define HAL_H

#include <stdint.h>
#include "../config.h"

/* One PWM period as seen by the hardware. The ADC values are sums of ADC_OVERSAMPLE
 * 12-bit conversions (0..ADC_FULL_SCALE), indexed by ADC_CH_x. Both windows are always
 * sampled; whether they are meaningful follows from `duty` (ON_VALID_MIN_DUTY,
 * OFF_VALID_MAX_DUTY). */
typedef struct {
    uint16_t duty;          /* duty that was really output in this period, 0..PWM_STEPS */
    uint16_t on[ADC_NCH];   /* window ON_SAMPLE_TICK .. +SAMPLE_TICKS after turn-on */
    uint16_t off[ADC_NCH];  /* window OFF_SAMPLE_TICK .. +SAMPLE_TICKS, end of the period */
} hal_period_t;

/* Duty for the following periods. Glitch-free; reaches the output two periods after the
 * app_step() call that set it (the platform latches it once per period). */
void hal_pwm_set(uint16_t duty);

/* Gate low immediately and whatever is still in the PWM pipeline discarded. The output
 * stays off until hal_pwm_set() is called with a non-zero duty again. */
void hal_heater_off(void);

void hal_led(int on);

/* 1: drive the HUSB238 VSET pin low (forces a 5 V request); 0: high-Z. */
void hal_vset_low(int low);

/* HUSB238 register access; return 0 on success, non-zero if the chip did not acknowledge. */
int hal_pd_read(uint8_t reg, uint8_t *val);
int hal_pd_write(uint8_t reg, uint8_t val);

/* Log output (UART), blocking. */
void hal_log(const char *s, unsigned len);

#endif /* HAL_H */
