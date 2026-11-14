#include "est.h"
#include "../config.h"

/* µK added to the correction per mK of (T_NTC - T_ctl) and period: 1000 * dt / tau */
#define CORR_UK_PER_MK  (1000 * PWM_PERIOD_MS / EST_TAU_MS)
#define CORR_MAX_UK     40000000        /* the cross-check trips long before 40 K */
_Static_assert(CORR_UK_PER_MK >= 1, "EST_TAU_MS too long for the correction resolution");

void est_set_reference(est_t *e, uint32_t r0_x, int32_t t0_mc)
{
    e->r0_x = r0_x;
    e->t0_mc = t0_mc;
    e->trusted = t0_mc < CAL_MAX_T_MC;
    e->corr_uk = 0;
}

void est_update(est_t *e, int r_valid, uint32_t r_x, int32_t t_ntc_mc)
{
    if (r_valid) {
        if (e->age > 2 || e->r_x == 0) {
            e->r_x = r_x;                   /* isolated sample: no history to filter with */
        } else {
            e->r_x = (uint32_t)((int32_t)e->r_x + ((int32_t)r_x - (int32_t)e->r_x) / 4);
        }
        e->age = 0;
        if (e->r0_x != 0) {
            /* R/R0 = (1 + a (T - 20)) / (1 + a (T0 - 20))
             *   =>  T = T0 + (R/R0 - 1) (1/a + T0 - 20) */
            int64_t num = (int64_t)((int32_t)e->r_x - (int32_t)e->r0_x)
                          * (CU_INV_ALPHA_MK + e->t0_mc - 20000);

            e->tr_mc = e->t0_mc + (int32_t)(num / (int32_t)e->r0_x);
        }
    } else if (e->age < 255) {
        e->age++;
    }
    e->tr_valid = e->r0_x != 0 && e->age <= TR_STALE_PERIODS;

    e->uses_r = e->tr_valid && e->trusted;
    if (e->uses_r) {
        e->tctl_mc = e->tr_mc + e->corr_uk / 1000;
        e->corr_uk += (t_ntc_mc - e->tctl_mc) * CORR_UK_PER_MK;
        if (e->corr_uk > CORR_MAX_UK) {
            e->corr_uk = CORR_MAX_UK;
        } else if (e->corr_uk < -CORR_MAX_UK) {
            e->corr_uk = -CORR_MAX_UK;
        }
    } else {
        e->tctl_mc = t_ntc_mc;
    }
}

uint32_t est_r20(uint32_t r_x, int32_t t_mc)
{
    /* 1 + alpha (T - 20), in 1e-4; valid for -200..+500 C without overflow */
    int32_t k = 10000 + (t_mc - 20000) * (CU_ALPHA_PPM / 10) / 10000;

    if (r_x > 400000u) {
        r_x = 400000u;                      /* 40 Ω: keeps the product inside 32 bits */
    }
    return r_x * 10000u / (uint32_t)k;
}
