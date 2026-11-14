/* Hot plate application: everything that does not touch a register. */
#ifndef APP_H
#define APP_H

#include <stdint.h>
#include "hal.h"
#include "sense.h"
#include "est.h"
#include "pi.h"
#include "charger.h"
#include "fault.h"
#include "led.h"

typedef enum {
    ST_NEGOTIATE = 0,   /* waiting for / selecting the charger voltage */
    ST_CALIBRATE = 1,   /* capturing the heater's reference resistance */
    ST_HEAT = 2,        /* warming up */
    ST_HOLD = 3,        /* at temperature */
    ST_NO_POWER = 4,    /* only 5 V available: heater stays off */
    ST_FAULT = 5        /* latched until power cycle */
} app_state_t;

typedef struct {
    uint32_t  tick;         /* PWM periods since start */
    uint8_t   state;        /* app_state_t */
    uint8_t   fault;        /* latched fault code, FAULT_x */
    uint8_t   emergency;    /* 5 V has been demanded from the charger */
    uint8_t   oc_events;    /* over-current events so far */
    uint8_t   weak;         /* selected voltage cannot reach the set-point */
    uint8_t   led_on;
    uint8_t   cal_n;        /* reference samples collected */
    uint16_t  cal_timer;
    uint32_t  cal_r_sum;
    int32_t   cal_t_sum;
    uint16_t  meas_timer;   /* periods since a duty that gives a resistance sample */
    uint16_t  off_timer;    /* periods since a duty that gives an OFF window */
    uint16_t  duty;         /* duty commanded in this step */
    sense_t   s;
    est_t     e;
    pi_t      pi;
    charger_t ch;
    fault_t   f;
    led_t     led;
} app_t;

extern app_t app;

void app_init(void);

/* Call once per PWM period with the samples of the period that just ended. */
void app_step(const hal_period_t *p);

#endif /* APP_H */
