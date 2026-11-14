#include "led.h"

#define CYCLE           50      /* 2 s */
#define BLIP            3       /* 120 ms */
#define FLASH           5       /* fault code: 200 ms on, 200 ms off */
#define FAULT_PAUSE     30      /* 1.2 s */

int led_step(led_t *l, led_mode_t mode, uint8_t code)
{
    uint16_t cycle = CYCLE;
    uint16_t ph;
    int on;

    if (l->mode != (uint8_t)mode) {
        l->mode = (uint8_t)mode;
        l->phase = 0;
    }
    if (mode == LED_NEGOTIATE) {
        cycle = 5;                                  /* 5 Hz */
    } else if (mode == LED_FAULT) {
        cycle = (uint16_t)(code * 2 * FLASH + FAULT_PAUSE);
    }
    ph = l->phase % cycle;
    l->phase = (uint16_t)(ph + 1);

    switch (mode) {
    case LED_NEGOTIATE:
        on = ph < 2;
        break;
    case LED_HEATING:
        on = 1;
        break;
    case LED_AT_TEMP:
        on = ph >= BLIP;
        break;
    case LED_WEAK:
        on = !(ph < BLIP || (ph >= 2 * BLIP && ph < 3 * BLIP));
        break;
    case LED_NO_POWER:
        on = ph < CYCLE / 2;
        break;
    default:                                        /* LED_FAULT */
        on = ph < code * 2 * FLASH && ph % (2 * FLASH) < FLASH;
        break;
    }
    return on;
}
