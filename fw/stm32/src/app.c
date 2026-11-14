#include "app.h"
#include "ntc.h"

app_t app;

/* ------------------------------------------------------------------ logging */

static char *put_int(char *p, int32_t v)
{
    char tmp[11];
    uint32_t u = v < 0 ? 0u - (uint32_t)v : (uint32_t)v;
    int n = 0;

    if (v < 0) {
        *p++ = '-';
    }
    do {
        tmp[n++] = (char)('0' + u % 10u);
        u /= 10u;
    } while (u != 0);
    while (n > 0) {
        *p++ = tmp[--n];
    }
    *p++ = ' ';
    return p;
}

/* One line per second, integers only:
 *   t[s] state VBUS[mV] I[mA] R[mΩ] T_NTC T_R T_ctl[0.1 C] duty[0.1 %] Vsel[V] fault
 * I is the heater current in the ON window, or the OFF-window reading if there was no
 * ON window. T_R is -9999 without a resistance reference. */
static void log_line(const app_t *a)
{
    char buf[96];
    char *p = buf;

    p = put_int(p, (int32_t)(a->tick / PWM_HZ));
    p = put_int(p, a->state);
    p = put_int(p, a->s.vbus_mv);
    p = put_int(p, a->s.on_valid ? a->s.ion_ma : a->s.ioff_ma);
    p = put_int(p, (int32_t)(a->e.r_x / 10u));
    p = put_int(p, a->s.t_ntc_mc / 100);
    p = put_int(p, a->e.r0_x != 0 ? a->e.tr_mc / 100 : -9999);
    p = put_int(p, a->e.tctl_mc / 100);
    p = put_int(p, a->duty);
    p = put_int(p, a->ch.sel_mv / 1000);
    p = put_int(p, a->fault);
    p[-1] = '\r';
    *p++ = '\n';
    hal_log(buf, (unsigned)(p - buf));
}

/* ------------------------------------------------------------------- faults */

static void enter_fault(app_t *a, uint8_t code)
{
    if (a->fault == FAULT_NONE) {
        a->fault = code;
    }
    a->state = ST_FAULT;
    hal_heater_off();
}

static void handle_faults(app_t *a, unsigned flags)
{
    unsigned code;

    /* dangerous ones first: besides the gate, take the supply down to 5 V. Repeat the
     * request once a second for as long as VBUS has not followed. */
    if (flags & (FLT_BIT(FAULT_OVERTEMP) | FLT_BIT(FAULT_SWITCH_SHORT))) {
        if (!a->emergency || (a->tick % PWM_HZ == 0 && a->s.vbus_mv > EMERGENCY_5V_MV)) {
            charger_force_5v();
        }
        a->emergency = 1;
    }

    /* over-current: off at once, then one voltage lower; latch if it happens again */
    if (flags & FLT_BIT(FAULT_OVERCURRENT)) {
        flags &= ~FLT_BIT(FAULT_OVERCURRENT);
        if (a->state != ST_FAULT && a->state != ST_NO_POWER) {
            hal_heater_off();
            a->oc_events++;
            if (a->oc_events >= OC_MAX_EVENTS || !charger_step_down(&a->ch, a->s.r_x)) {
                flags |= FLT_BIT(FAULT_OVERCURRENT);
            } else {
                a->state = ST_NEGOTIATE;
            }
        }
    }

    for (code = FAULT_NTC; code <= FAULT_HEATER_OPEN; code++) {
        if (flags & FLT_BIT(code)) {
            enter_fault(a, (uint8_t)code);
            break;
        }
    }

    /* supply voltage gone: heater off, select again */
    if ((flags & FLT_VBUS) && (a->state == ST_CALIBRATE || a->state == ST_HEAT || a->state == ST_HOLD)) {
        hal_heater_off();
        charger_restart(&a->ch);
        a->state = ST_NEGOTIATE;
    }
}

/* ------------------------------------------------------------------- states */

static void start_heating(app_t *a)
{
    a->pi.integ_nd = 0;
    a->meas_timer = 0;
    a->off_timer = 0;
    a->state = ST_HEAT;
}

static uint16_t step_negotiate(app_t *a)
{
    uint16_t duty = charger_step(&a->ch, &a->s);

    switch (a->ch.st) {
    case CH_DONE:
        a->weak = a->ch.sel_mv < WEAK_BELOW_MV;
        a->cal_n = 0;
        a->cal_timer = 0;
        a->cal_r_sum = 0;
        a->cal_t_sum = 0;
        a->state = ST_CALIBRATE;
        break;
    case CH_NO_POWER:
        a->state = ST_NO_POWER;
        hal_heater_off();
        break;
    case CH_PROBE_FAILED:
        enter_fault(a, FAULT_HEATER_OPEN);
        break;
    default:
        break;
    }
    return duty;
}

/* A few short pulses at the selected voltage before real heating starts. They show the
 * current the heater will draw (over-current check on 3 ms pulses instead of full
 * periods) and, the first time, give the reference resistance R0 at the NTC temperature
 * T0: each pulse starts from rest, far enough from the previous one that the trace is
 * back at plate temperature. */
static uint16_t step_calibrate(app_t *a)
{
    uint16_t duty = 0;

    if (a->s.r_valid) {
        a->cal_r_sum += a->s.r_x;
        a->cal_t_sum += a->s.t_ntc_mc;
        a->cal_n++;
    }
    if (a->cal_n >= CAL_PULSES || a->cal_timer >= CAL_TIMEOUT) {
        if (a->e.r0_x == 0 && a->cal_n != 0) {
            est_set_reference(&a->e, a->cal_r_sum / a->cal_n, a->cal_t_sum / a->cal_n);
        }
        start_heating(a);                   /* without any sample: NTC only, no-rise check */
    } else if (a->cal_timer % CAL_SPACING == 0) {
        duty = MEAS_PULSE_DUTY;
    }
    a->cal_timer++;
    return duty;
}

static uint16_t step_control(app_t *a)
{
    int32_t err = SETPOINT_MC - a->e.tctl_mc;
    uint16_t duty;

    if (a->s.ntc_state != NTC_OK) {
        return 0;                           /* no temperature: no heat (fault follows) */
    }
    duty = pi_step(&a->pi, err);
    if (duty < PWM_MIN_PULSE) {
        duty = 0;                           /* no slivers: they only heat the switch */
    } else if (duty > PWM_STEPS - PWM_MIN_PULSE) {
        duty = PWM_STEPS;
    }

    /* keep the resistance reading alive when the controller asks for (almost) nothing */
    if (duty >= ON_VALID_MIN_DUTY) {
        a->meas_timer = 0;
    } else if (++a->meas_timer >= MEAS_INTERVAL) {
        a->meas_timer = 0;
        duty = MEAS_PULSE_DUTY;
    }
    /* keep the zero-current / shorted-switch check alive at (almost) full duty */
    if (duty <= OFF_VALID_MAX_DUTY) {
        a->off_timer = 0;
    } else if (++a->off_timer >= OFF_INTERVAL || fault_short_suspected(&a->f)) {
        a->off_timer = 0;
        duty = OFF_VALID_MAX_DUTY;
    }

    if (err <= AT_TEMP_ENTER_MK) {
        a->state = ST_HOLD;
    } else if (err > AT_TEMP_LEAVE_MK) {
        a->state = ST_HEAT;
    }
    return duty;
}

/* --------------------------------------------------------------------- main */

void app_init(void)
{
    static const char header[] = "# t st mV mA mR Tn Tr Tc duty V f\r\n";

    app = (app_t){ .state = ST_NEGOTIATE };
    charger_init(&app.ch);
    hal_heater_off();
    hal_vset_low(0);
    hal_log(header, sizeof header - 1);
}

void app_step(const hal_period_t *p)
{
    app_t *a = &app;
    uint16_t duty = 0;
    led_mode_t mode;

    a->tick++;
    sense_update(&a->s, p);
    est_update(&a->e, a->s.r_valid, a->s.r_x, a->s.t_ntc_mc);
    handle_faults(a, fault_step(&a->f, &a->s, &a->e, p->duty,
                                a->state >= ST_CALIBRATE ? a->ch.sel_mv : 0, a->ch.limit_ma));

    switch (a->state) {
    case ST_NEGOTIATE:
        duty = step_negotiate(a);
        mode = LED_NEGOTIATE;
        break;
    case ST_CALIBRATE:
        duty = step_calibrate(a);
        mode = LED_NEGOTIATE;
        break;
    case ST_HEAT:
    case ST_HOLD:
        duty = step_control(a);
        mode = a->weak ? LED_WEAK : a->state == ST_HOLD ? LED_AT_TEMP : LED_HEATING;
        break;
    case ST_NO_POWER:
        mode = LED_NO_POWER;
        break;
    default:
        mode = LED_FAULT;
        break;
    }

    a->duty = duty;
    if (a->state == ST_FAULT || a->state == ST_NO_POWER) {
        hal_heater_off();
    } else {
        hal_pwm_set(duty);
    }
    a->led_on = (uint8_t)led_step(&a->led, mode, a->fault);
    hal_led(a->led_on);

    if (a->tick % LOG_PERIODS == 0) {
        log_line(a);
    }
}
