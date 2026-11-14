/* NTC divider reading -> temperature, by table and linear interpolation. */
#ifndef NTC_H
#define NTC_H

#include <stdint.h>

enum { NTC_OK = 0, NTC_OPEN = 1, NTC_SHORT = 2 };

/* raw: sum of ADC_OVERSAMPLE conversions (0..ADC_FULL_SCALE).
 * Returns NTC_OK and the temperature in m°C (clamped to the table range, -30..160 C),
 * or NTC_OPEN / NTC_SHORT with *t_mc untouched. */
int ntc_convert(uint32_t raw, int32_t *t_mc);

#endif /* NTC_H */
