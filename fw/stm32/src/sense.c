#include "sense.h"
#include "ntc.h"

/* raw sum -> mV at the pin is raw * ADC_VREF_MV / ADC_FULL_SCALE */
#define VBUS_NUM        (ADC_VREF_MV * VSENSE_DIV_NUM)
#define VBUS_DEN        (ADC_FULL_SCALE * VSENSE_DIV_DEN)
#define MA_NUM          (ADC_VREF_MV * 1000 / ISENSE_MV_PER_A)
#define MA_DEN          ADC_FULL_SCALE
/* R = V / I; the ADC reference cancels: R[0.1 mΩ] = raw_v * R_SCALE / raw_i */
#define R_SCALE         (10u * ISENSE_MV_PER_A * VSENSE_DIV_NUM / VSENSE_DIV_DEN)
#define ZERO_MAX_RAW    ((uint32_t)ISENSE_ZERO_MAX_MA * MA_DEN / MA_NUM)

/* all products below stay inside 32 bits */
_Static_assert((uint64_t)ADC_FULL_SCALE * VBUS_NUM < 0xFFFFFFFFull, "vbus overflow");
_Static_assert((uint64_t)ADC_FULL_SCALE * MA_NUM < 0xFFFFFFFFull, "current overflow");
_Static_assert((uint64_t)ADC_FULL_SCALE * R_SCALE < 0xFFFFFFFFull, "resistance overflow");
_Static_assert(ADC_FULL_SCALE <= 0xFFFF, "samples are 16 bit");

static int32_t raw_to_vbus_mv(uint32_t raw)
{
    return (int32_t)(raw * VBUS_NUM / VBUS_DEN);
}

static int32_t raw_to_ma(uint32_t raw)
{
    return (int32_t)(raw * MA_NUM / MA_DEN);
}

void sense_update(sense_t *s, const hal_period_t *p)
{
    const uint16_t *quiet;
    int32_t t;

    s->on_valid = p->duty >= ON_VALID_MIN_DUTY;
    s->off_valid = p->duty <= OFF_VALID_MAX_DUTY;

    /* zero-current reading of the amplifier, tracked in OFF windows only */
    if (s->off_valid) {
        uint32_t raw = p->off[ADC_CH_ISENSE];

        s->ioff_ma = raw_to_ma(raw);
        if (raw <= ZERO_MAX_RAW) {
            if (!s->zero_init) {
                s->zero_x8 = (uint16_t)(raw * 8u);
                s->zero_init = 1;
            } else {
                s->zero_x8 = (uint16_t)(s->zero_x8 - s->zero_x8 / 8u + raw);
            }
        }
    }

    /* slow signals: prefer the window without heater current */
    quiet = s->off_valid ? p->off : p->on;
    s->vbus_mv = raw_to_vbus_mv(quiet[ADC_CH_VSENSE]);
    s->ntc_state = (uint8_t)ntc_convert(quiet[ADC_CH_NTC1], &s->t_ntc_mc);

    /* optional second NTC: the pin normally floats, so it only counts while it has been
     * tracking NTC1 for a while */
    if (s->ntc_state == NTC_OK && ntc_convert(quiet[ADC_CH_NTC2], &t) == NTC_OK
        && t - s->t_ntc_mc < NTC2_AGREE_MK && s->t_ntc_mc - t < NTC2_AGREE_MK) {
        s->t_ntc2_mc = t;
        if (s->ntc2_cnt < NTC2_AGREE_PERIODS) {
            s->ntc2_cnt++;
        }
    } else {
        s->ntc2_cnt = 0;
    }
    s->ntc2_ok = s->ntc2_cnt >= NTC2_AGREE_PERIODS;

    /* heater current and resistance inside the ON part */
    s->r_valid = 0;
    if (s->on_valid) {
        uint32_t raw_v = p->on[ADC_CH_VSENSE];
        uint32_t raw_i = p->on[ADC_CH_ISENSE];
        uint32_t zero = s->zero_x8 / 8u;

        raw_i = raw_i > zero ? raw_i - zero : 0;
        s->von_mv = raw_to_vbus_mv(raw_v);
        s->ion_ma = raw_to_ma(raw_i);
        if (s->ion_ma >= ISENSE_MIN_MA) {
            s->r_x = raw_v * R_SCALE / raw_i;
            s->r_valid = 1;
        }
    }
}
