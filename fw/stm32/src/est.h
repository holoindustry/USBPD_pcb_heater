/* Trace temperature from the heater resistance, and the control temperature. */
#ifndef EST_H
#define EST_H

#include <stdint.h>

typedef struct {
    uint32_t r0_x;      /* reference resistance, 0.1 mΩ; 0 = none */
    int32_t  t0_mc;     /* NTC temperature when r0_x was captured */
    uint8_t  trusted;   /* reference captured cold (isothermal): T_R may drive the control */
    uint8_t  tr_valid;  /* T_R has a reference and is fresh (enough for the protections) */
    uint8_t  uses_r;    /* control temperature is T_R based right now */
    uint8_t  age;       /* periods since the last resistance sample, saturating */
    uint32_t r_x;       /* filtered heater resistance */
    int32_t  tr_mc;     /* trace temperature T_R */
    int32_t  corr_uk;   /* slow correction of T_R towards the NTC, µK */
    int32_t  tctl_mc;   /* control temperature */
} est_t;

/* Capture R0/T0. The reference is always kept for the protections; it is used for
 * control only if t0_mc < CAL_MAX_T_MC. */
void est_set_reference(est_t *e, uint32_t r0_x, int32_t t0_mc);

/* Once per period. r_valid/r_x: fresh resistance sample; t_ntc_mc: NTC1. */
void est_update(est_t *e, int r_valid, uint32_t r_x, int32_t t_ntc_mc);

/* Resistance at 20 C from a resistance measured at t_mc. */
uint32_t est_r20(uint32_t r_x, int32_t t_mc);

#endif /* EST_H */
