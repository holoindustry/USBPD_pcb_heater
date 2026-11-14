/* ADC samples of one PWM period -> physical quantities. */
#ifndef SENSE_H
#define SENSE_H

#include <stdint.h>
#include "hal.h"

typedef struct {
    /* refreshed every period */
    uint8_t  on_valid;      /* the ON window saw the heater on, settled */
    uint8_t  off_valid;     /* the OFF window saw the heater off, settled */
    uint8_t  r_valid;       /* r_x is a fresh heater resistance */
    uint8_t  ntc_state;     /* NTC_OK / NTC_OPEN / NTC_SHORT for NTC1 */
    uint8_t  ntc2_ok;       /* NTC2 fitted and agreeing with NTC1 */
    int32_t  vbus_mv;       /* VBUS, from the OFF window when there is one */
    int32_t  von_mv;        /* VBUS in the ON window (on_valid) */
    int32_t  ion_ma;        /* heater current in the ON window, zero corrected (on_valid) */
    int32_t  ioff_ma;       /* current reading in the OFF window, uncorrected (off_valid) */
    uint32_t r_x;           /* heater resistance V/I, 0.1 mΩ (r_valid) */
    int32_t  t_ntc_mc;      /* NTC1; keeps the last good value while ntc_state != NTC_OK */
    int32_t  t_ntc2_mc;
    /* state */
    uint16_t zero_x8;       /* filtered zero-current ISENSE reading, x8 */
    uint8_t  zero_init;
    uint8_t  ntc2_cnt;
} sense_t;

void sense_update(sense_t *s, const hal_period_t *p);

#endif /* SENSE_H */
