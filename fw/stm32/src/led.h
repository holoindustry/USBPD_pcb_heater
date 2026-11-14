/* Status LED patterns, stepped once per PWM period (40 ms). */
#ifndef LED_H
#define LED_H

#include <stdint.h>

typedef enum {
    LED_NEGOTIATE,      /* fast blink */
    LED_HEATING,        /* solid */
    LED_AT_TEMP,        /* solid with one short off-blip every 2 s */
    LED_WEAK,           /* solid with two short off-blips every 2 s (9 V charger) */
    LED_NO_POWER,       /* slow even blink, 1 s on / 1 s off */
    LED_FAULT           /* N short flashes, then a pause; N = fault code */
} led_mode_t;

typedef struct {
    uint8_t  mode;
    uint16_t phase;
} led_t;

/* Returns the LED state (1 = lit) for this period. */
int led_step(led_t *l, led_mode_t mode, uint8_t code);

#endif /* LED_H */
