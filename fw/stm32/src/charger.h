/* USB-PD charger selection through the HUSB238 sink controller. */
#ifndef CHARGER_H
#define CHARGER_H

#include <stdint.h>
#include "sense.h"

#define CH_NV   4               /* candidate voltages: 20, 15, 12, 9 V */

typedef enum {
    CH_WAIT,                    /* let the PD chip negotiate by itself */
    CH_READ,                    /* read the source's offers */
    CH_PROBE,                   /* measure the heater with a short pulse */
    CH_PICK,                    /* choose the highest voltage the charger can feed */
    CH_QUIET,                   /* heater off before the request */
    CH_CONFIRM,                 /* wait for the new voltage and the PD response */
    CH_DONE,                    /* sel_mv / limit_ma are valid */
    CH_NO_POWER,                /* nothing usable above 5 V */
    CH_PROBE_FAILED             /* no or implausible resistance reading: cannot select */
} ch_state_t;

typedef struct {
    uint8_t  st;                /* ch_state_t */
    uint8_t  pd_ok;             /* the PD chip answered and listed offers */
    uint8_t  tries;
    uint8_t  idx;               /* candidate being requested */
    uint8_t  stable;            /* periods VBUS has been at the requested voltage */
    uint16_t timer;             /* periods in the current state */
    uint16_t max_mv;            /* candidates above this are skipped (over-current step-down) */
    uint16_t offer_ma[CH_NV];   /* offered current per candidate; 0 = not offered or failed */
    uint16_t sel_mv;            /* selected voltage; 0 = none */
    uint16_t limit_ma;          /* contract current of the selection; 0 = unknown (no PD data) */
    uint32_t r20_x;             /* heater resistance at 20 C, 0.1 mΩ; 0 = not measured */
} charger_t;

/* Power-up: wait, read the offers, probe the heater, select. */
void charger_init(charger_t *c);

/* VBUS left the expected range: start over (keeps the R20 estimate and max_mv). */
void charger_restart(charger_t *c);

/* Over-current: select again among the offers below the present voltage, with r_x as an
 * upper bound for the heater resistance. Returns 0 if there is nothing to step down to. */
int charger_step_down(charger_t *c, uint32_t r_x);

/* Once per period while selecting. Returns the duty to output in the next period
 * (0, or one measurement pulse); the result is c->st. */
uint16_t charger_step(charger_t *c, const sense_t *s);

/* Emergency: ask for 5 V over I2C and through the VSET pin. */
void charger_force_5v(void);

/* Highest candidate (index into the 20/15/12/9 V list, starting at `from`) not above
 * max_mv whose offer covers PD_CURRENT_MARGIN_PCT x V / R20; -1 if none. */
int charger_pick(const uint16_t offer_ma[CH_NV], uint32_t r20_x, uint16_t max_mv, int from);

uint16_t charger_candidate_mv(int idx);

#endif /* CHARGER_H */
