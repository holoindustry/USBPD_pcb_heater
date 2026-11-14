/* Protections. fault_step() is evaluated every period; it reports conditions as a bit
 * mask, the application decides what latches. */
#ifndef FAULT_H
#define FAULT_H

#include <stdint.h>
#include "sense.h"
#include "est.h"

/* Fault codes = number of LED flashes. */
enum {
    FAULT_NONE = 0,
    FAULT_NTC = 1,              /* NTC1 open or shorted */
    FAULT_OVERTEMP = 2,         /* NTC > 125 C or T_R > 135 C */
    FAULT_SWITCH_SHORT = 3,     /* current flows with the switch off */
    FAULT_SENSOR = 4,           /* T_R / NTC cross-check, or no temperature rise */
    FAULT_OVERCURRENT = 5,      /* over-current, repeated after stepping the voltage down */
    FAULT_HEATER_OPEN = 6       /* switch on but no current, or resistance not that of the heater */
};

#define FLT_BIT(code)       (1u << (code))
#define FLT_VBUS            (1u << 7)   /* VBUS out of range (not latched) */

typedef struct {
    uint8_t  ntc_cnt;
    uint8_t  ot_cnt;
    uint8_t  short_cnt;
    uint8_t  oc_cnt;
    uint8_t  open_cnt;
    uint8_t  vbus_cnt;
    uint16_t xc_cnt;            /* cross-check: periods out of agreement */
    uint16_t nr_cnt;            /* no-rise check: periods at high duty */
    int32_t  nr_t0_mc;          /* NTC at the start of the no-rise window */
} fault_t;

/* duty: duty output in the sampled period. sel_mv: selected supply voltage, 0 while none
 * is selected (no VBUS range check). limit_ma: contract current, 0 = unknown.
 * Returns FLT_BIT(code) for each condition that tripped in this period, and FLT_VBUS.
 * FLT_BIT(FAULT_OVERCURRENT) is one over-current event. */
unsigned fault_step(fault_t *f, const sense_t *s, const est_t *e, uint16_t duty,
                    uint16_t sel_mv, uint16_t limit_ma);

/* An OFF window showed current: the application should keep OFF windows coming. */
static inline int fault_short_suspected(const fault_t *f)
{
    return f->short_cnt != 0;
}

#endif /* FAULT_H */
