#include "fault.h"
#include "ntc.h"

/* debounce: count consecutive hits, report once when the limit is reached */
static int hit8(uint8_t *cnt, int cond, uint8_t limit)
{
    if (!cond) {
        *cnt = 0;
        return 0;
    }
    if (*cnt < limit) {
        (*cnt)++;
    }
    return *cnt >= limit;
}

unsigned fault_step(fault_t *f, const sense_t *s, const est_t *e, uint16_t duty,
                    uint16_t sel_mv, uint16_t limit_ma)
{
    unsigned flags = 0;
    int ntc_ok = s->ntc_state == NTC_OK;
    int32_t d;

    /* NTC1 open or shorted */
    if (hit8(&f->ntc_cnt, !ntc_ok, NTC_FAULT_PERIODS)) {
        flags |= FLT_BIT(FAULT_NTC);
    }

    /* over-temperature */
    if (hit8(&f->ot_cnt,
             (ntc_ok && s->t_ntc_mc > OT_NTC_MC)
             || (s->ntc2_ok && s->t_ntc2_mc > OT_NTC_MC)
             || (e->tr_valid && e->tr_mc > OT_TR_MC),
             OT_PERIODS)) {
        flags |= FLT_BIT(FAULT_OVERTEMP);
    }

    /* current although the switch is off */
    if (s->off_valid && hit8(&f->short_cnt, s->ioff_ma > SHORT_MA, SHORT_SAMPLES)) {
        flags |= FLT_BIT(FAULT_SWITCH_SHORT);
    }

    /* the two temperature readings must agree ... */
    if (e->tr_valid && ntc_ok) {
        d = e->tr_mc - s->t_ntc_mc;
        if (d > XCHECK_MK || d < -XCHECK_MK) {
            if (f->xc_cnt < XCHECK_PERIODS) {
                f->xc_cnt++;
            }
            if (f->xc_cnt >= XCHECK_PERIODS) {
                flags |= FLT_BIT(FAULT_SENSOR);
            }
        } else {
            f->xc_cnt = 0;
        }
        f->nr_cnt = 0;
    } else if (ntc_ok && duty >= NORISE_DUTY && s->vbus_mv >= NORISE_VBUS_MV) {
        /* ... or, without T_R, sustained heating must show on the NTC */
        if (f->nr_cnt == 0) {
            f->nr_t0_mc = s->t_ntc_mc;
        }
        if (++f->nr_cnt >= NORISE_PERIODS) {
            if (s->t_ntc_mc - f->nr_t0_mc < NORISE_MK) {
                flags |= FLT_BIT(FAULT_SENSOR);
            }
            f->nr_cnt = 0;
        }
    } else {
        f->nr_cnt = 0;
    }

    if (s->on_valid) {
        int32_t lim = OC_ABS_MA;

        /* over-current */
        if (limit_ma != 0 && limit_ma * OC_CONTRACT_PCT / 100 < lim) {
            lim = limit_ma * OC_CONTRACT_PCT / 100;
        }
        if (hit8(&f->oc_cnt, s->ion_ma > lim, OC_SAMPLES)) {
            flags |= FLT_BIT(FAULT_OVERCURRENT);
            f->oc_cnt = 0;
        }
        /* heater open */
        if (hit8(&f->open_cnt, s->ion_ma < ISENSE_MIN_MA && s->von_mv > OPEN_MIN_VBUS_MV,
                 OPEN_SAMPLES)) {
            flags |= FLT_BIT(FAULT_HEATER_OPEN);
        }
    }

    /* supply voltage away from the selected one */
    if (sel_mv != 0) {
        int32_t lo = sel_mv * VBUS_LOW_PCT / 100;
        int32_t hi = sel_mv * VBUS_HIGH_PCT / 100;

        if (hit8(&f->vbus_cnt,
                 s->vbus_mv < lo || s->vbus_mv > hi
                 || (s->on_valid && (s->von_mv < lo || s->von_mv > hi)),
                 VBUS_FAULT_PERIODS)) {
            flags |= FLT_VBUS;
            f->vbus_cnt = 0;
        }
    } else {
        f->vbus_cnt = 0;
    }
    return flags;
}
