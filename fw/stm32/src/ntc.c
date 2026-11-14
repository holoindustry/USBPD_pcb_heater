#include "ntc.h"
#include "../config.h"
#include "ntc_table.h"

_Static_assert((uint64_t)ADC_FULL_SCALE * 65535u <= 0xFFFFFFFFull, "ratio overflow");

int ntc_convert(uint32_t raw, int32_t *t_mc)
{
    uint32_t q, hi, lo;
    unsigned i;

    if (raw > ADC_FULL_SCALE) {
        raw = ADC_FULL_SCALE;
    }
    q = raw * 65535u / ADC_FULL_SCALE;      /* divider ratio, 0..65535 */
    if (q > NTC_OPEN_Q16) {
        return NTC_OPEN;
    }
    if (q < NTC_SHORT_Q16) {
        return NTC_SHORT;
    }
    /* the table falls with temperature; find the segment [i, i+1] that holds q */
    if (q >= ntc_table[0]) {
        *t_mc = NTC_TABLE_T_MIN_MC;
        return NTC_OK;
    }
    for (i = 1; i < NTC_TABLE_LEN; i++) {
        if (q >= ntc_table[i]) {
            break;
        }
    }
    if (i == NTC_TABLE_LEN) {
        *t_mc = NTC_TABLE_T_MIN_MC + (NTC_TABLE_LEN - 1) * NTC_TABLE_STEP_MK;
        return NTC_OK;
    }
    hi = ntc_table[i - 1];
    lo = ntc_table[i];
    *t_mc = NTC_TABLE_T_MIN_MC + (int32_t)(i - 1) * NTC_TABLE_STEP_MK
            + (int32_t)((hi - q) * NTC_TABLE_STEP_MK / (hi - lo));
    return NTC_OK;
}
