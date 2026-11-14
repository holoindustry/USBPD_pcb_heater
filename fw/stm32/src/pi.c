#include "pi.h"
#include "../config.h"

/* proportional gain in 1e-6 duty per mK:  permille/K * 1000 / 1000 */
#define KP_UD_PER_MK    PI_KP_PERMILLE_PER_K
/* integral gain in 1e-9 duty per mK and period:  permille/(K s) * 1e6 / 1000 * dt */
#define KI_ND_PER_MK    (PI_KI_PERMILLE_PER_KS * PWM_PERIOD_MS)
#define ERR_MAX_MK      200000
#define FULL_UD         1000000
#define FULL_ND         1000000000

uint16_t pi_step(pi_t *pi, int32_t err_mk)
{
    int32_t u;

    if (err_mk > ERR_MAX_MK) {
        err_mk = ERR_MAX_MK;
    } else if (err_mk < -ERR_MAX_MK) {
        err_mk = -ERR_MAX_MK;
    }
    u = KP_UD_PER_MK * err_mk + pi->integ_nd / 1000;       /* 1e-6 duty */

    /* integrate only while the output is not saturated, or while that helps to leave
     * saturation */
    if ((u > 0 && u < FULL_UD) || (u >= FULL_UD && err_mk < 0) || (u <= 0 && err_mk > 0)) {
        pi->integ_nd += KI_ND_PER_MK * err_mk;
        if (pi->integ_nd > FULL_ND) {
            pi->integ_nd = FULL_ND;
        } else if (pi->integ_nd < -FULL_ND) {
            pi->integ_nd = -FULL_ND;
        }
    }
    if (u <= 0) {
        return 0;
    }
    if (u >= FULL_UD) {
        return PWM_STEPS;
    }
    return (uint16_t)((uint32_t)u / (FULL_UD / PWM_STEPS));
}
