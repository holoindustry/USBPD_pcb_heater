/* PI controller with conditional-integration anti-windup. */
#ifndef PI_H
#define PI_H

#include <stdint.h>

typedef struct {
    int32_t integ_nd;       /* integral term, 1e-9 of full duty */
} pi_t;

/* err_mk = set-point - control temperature. Returns the duty, 0..PWM_STEPS. */
uint16_t pi_step(pi_t *pi, int32_t err_mk);

#endif /* PI_H */
