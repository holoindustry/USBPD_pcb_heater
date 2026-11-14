/*
 * Host tests: the firmware logic of src/ against the simulated board of sim.c.
 * Every test prints one line; the exit status is non-zero if any check failed.
 */
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "sim.h"
#include "../src/app.h"
#include "../src/ntc.h"

/* ------------------------------------------------------------- test harness */

static int  tests_failed;
static int  checks_failed;              /* in the current test */
static char why[1024];

static void check(int ok, const char *fmt, ...)
{
    va_list ap;
    size_t n = strlen(why);

    if (ok) {
        return;
    }
    checks_failed++;
    if (n < sizeof why - 2) {
        va_start(ap, fmt);
        n += (size_t)snprintf(why + n, sizeof why - n, "        - ");
        n += (size_t)vsnprintf(why + n, n < sizeof why ? sizeof why - n : 0, fmt, ap);
        if (n < sizeof why - 1) {
            strcat(why, "\n");
        }
        va_end(ap);
    }
}

static void report(const char *name, const char *fmt, ...)
{
    va_list ap;

    printf("%s %-19s ", checks_failed ? "FAIL" : "PASS", name);
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf("\n");
    if (checks_failed) {
        fputs(why, stdout);
        tests_failed++;
    }
    checks_failed = 0;
    why[0] = 0;
}

/* ------------------------------------------------------------ chargers used */

static const sim_offer_t W65[] = { { 5000, 3000 }, { 9000, 3000 }, { 15000, 3000 }, { 20000, 3250 } };
static const sim_offer_t W60[] = { { 5000, 3000 }, { 9000, 3000 }, { 15000, 3000 }, { 20000, 3000 } };
static const sim_offer_t W45[] = { { 20000, 2250 }, { 15000, 3000 }, { 9000, 3000 }, { 5000, 3000 } };
static const sim_offer_t W30[] = { { 20000, 1500 }, { 15000, 2000 }, { 9000, 3000 }, { 5000, 3000 } };
static const sim_offer_t W20[] = { { 12000, 1670 }, { 9000, 2220 }, { 5000, 3000 } };
static const sim_offer_t W5[] = { { 5000, 3000 } };

#define OFFERS(a)   sim_set_offers(a, (int)(sizeof(a) / sizeof(a)[0]))

/* --------------------------------------------------------- running the world */

typedef struct {
    double from, to;                    /* statistics window, s */
    double sum, energy, lo, hi;
    int    n;
} win_t;

static struct {
    double t_fault;                     /* when a fault latched, <0 = none */
    double top_at_fault;
    int    used_r;                      /* the control temperature was T_R based at some time */
    int    max_duty;
    int    led_edges_mark;
} obs;

static void win_init(win_t *w, double from, double to)
{
    memset(w, 0, sizeof *w);
    w->from = from;
    w->to = to;
    w->lo = 1e9;
    w->hi = -1e9;
}

static double win_mean(const win_t *w)
{
    return w->n ? w->sum / w->n : NAN;
}

static double win_power(const win_t *w)
{
    return w->n ? w->energy / (w->n * PWM_PERIOD_MS / 1000.0) : NAN;
}

static void start(void)
{
    memset(&obs, 0, sizeof obs);
    obs.t_fault = -1;
    sim_start();
}

static void run_to(double t_end, win_t *w1, win_t *w2)
{
    win_t *w[2] = { w1, w2 };
    int i;

    while (sim.t < t_end - 1e-9) {
        sim_period();
        for (i = 0; i < 2; i++) {
            if (w[i] != NULL && sim.t > w[i]->from + 1e-9 && sim.t <= w[i]->to + 1e-9) {
                w[i]->sum += sim.p_top_mean;
                w[i]->energy += sim.p_energy_j;
                w[i]->lo = fmin(w[i]->lo, sim.p_top_min);
                w[i]->hi = fmax(w[i]->hi, sim.p_top_max);
                w[i]->n++;
            }
        }
        if (app.fault != FAULT_NONE && obs.t_fault < 0) {
            obs.t_fault = sim.t;
            obs.top_at_fault = plant_t_top(&sim.plant);
        }
        obs.used_r |= app.e.uses_r;
        if (app.duty > obs.max_duty) {
            obs.max_duty = app.duty;
        }
    }
}

/* LED edges per second over the next `secs` seconds (keeps the world running) */
static double led_rate(double secs)
{
    int e0 = sim.led_edges;

    run_to(sim.t + secs, NULL, NULL);
    return (sim.led_edges - e0) / secs;
}

static void check_no_supply_abuse(void)
{
    check(sim.oc_time == 0, "heater drew more than the contract current for %.1f ms (max %.2f A, contract %.2f A)",
          sim.oc_time * 1e3, sim.i_max, sim.contract_ma / 1000.0);
    check(sim.trans_heat_time == 0, "heater was on during a voltage change (%.1f ms)", sim.trans_heat_time * 1e3);
    check(sim.hard_resets == 0, "firmware sent a PD hard reset");
}

static void check_settled(const win_t *w, double band, double lo, double hi)
{
    double m = win_mean(w);

    check(w->hi - m <= band && m - w->lo <= band, "not settled: %.2f .. %.2f C around a mean of %.2f C (+-%.1f K allowed)",
          w->lo, w->hi, m, band);
    check(m >= lo && m <= hi, "mean %.2f C outside %.0f .. %.0f C", m, lo, hi);
}

/* --------------------------------------------------------------- unit tests */

static void test_ntc_table(void)
{
    double worst = 0, t;
    int32_t mc;

    for (t = 0.0; t <= 150.0; t += 0.05) {
        uint32_t raw = (uint32_t)lround(sim_ntc_ratio(t) * ADC_FULL_SCALE);
        int st = ntc_convert(raw, &mc);

        check(st == NTC_OK, "ntc_convert rejects %.2f C", t);
        if (st != NTC_OK) {
            break;
        }
        worst = fmax(worst, fabs(mc / 1000.0 - t));
    }
    check(worst <= 0.3, "table is off by %.3f K", worst);
    check(ntc_convert(ADC_FULL_SCALE, &mc) == NTC_OPEN, "open NTC (pin at 3V3) not detected");
    check(ntc_convert(ADC_FULL_SCALE * 995u / 1000u, &mc) == NTC_OPEN, "nearly open NTC not detected");
    check(ntc_convert(0, &mc) == NTC_SHORT, "shorted NTC not detected");
    check(ntc_convert((uint32_t)lround(sim_ntc_ratio(-25.0) * ADC_FULL_SCALE), &mc) == NTC_OK, "-25 C rejected");
    check(ntc_convert((uint32_t)lround(sim_ntc_ratio(200.0) * ADC_FULL_SCALE), &mc) == NTC_OK && mc >= 150000,
          "200 C does not read as hot");
    report("ntc-table", "worst %.3fK of 0.3K, 0..150C", worst);
}

static void test_plant(void)
{
    plant_t pl;
    double t99 = -1, h_top, h_bot;
    int k;

    plant_init(&pl, 9.0, PLANT_T_AMB);
    for (k = 0; k < 30000 && t99 < 0; k++) {
        plant_step(&pl, 20.0 * 20.0 / plant_r_heater(&pl), PLANT_DT);
        if (plant_t_top(&pl) >= 99.0) {
            t99 = (k + 1) * PLANT_DT;
        }
    }
    plant_coeffs(100.0, &h_top, &h_bot);
    check(t99 > 33.5 && t99 < 34.5, "20 V warm-up to 99 C takes %.2f s, Python model: 33.95 s", t99);
    check(fabs(h_top - 18.5788) < 1e-3 && fabs(h_bot - 6.6844) < 1e-3, "surface coefficients differ from the Python model");
    check(fabs(plant_heat_capacity(&pl) - 17.1358) < 1e-3, "heat capacity differs from the Python model");
    report("plant", "20V: 99C after %.2fs", t99);
}

static void test_pi(void)
{
    pi_t pi = { 0 };
    int i, d = 0, max_d = 0;

    for (i = 0; i < 5000; i++) {                /* 200 s far below the set-point: saturated */
        d = pi_step(&pi, 60000);
    }
    check(d == PWM_STEPS, "not at full duty with 60 K error");
    check(pi.integ_nd == 0, "integrator wound up while saturated (%d)", (int)pi.integ_nd);
    for (i = 0; i < 5000; i++) {                /* 200 s far above: off, no negative wind-up */
        d = pi_step(&pi, -60000);
    }
    check(d == 0 && pi.integ_nd == 0, "integrator wound down while saturated (%d)", (int)pi.integ_nd);
    for (i = 0; i < 25; i++) {                  /* 1 s at +1 K: P = 0.25, I = 0.012 duty */
        d = pi_step(&pi, 1000);
        max_d = d > max_d ? d : max_d;
    }
    check(d >= 260 && d <= 263, "1 K error for 1 s gives duty %d, expected 262", d);
    check(pi_step(&pi, 0) == 12, "integral after 1 K s is not 0.012 duty");
    report("pi-antiwindup", "ok");
}

static void test_pick(void)
{
    /* offers for 20, 15, 12, 9 V; 9.0 ohm -> r20_x = 90000 */
    static const uint16_t w65[CH_NV] = { 3250, 3000, 0, 3000 };
    static const uint16_t w45[CH_NV] = { 2250, 3000, 0, 3000 };
    static const uint16_t w30[CH_NV] = { 1500, 2000, 0, 3000 };
    static const uint16_t w20[CH_NV] = { 0, 0, 1500, 2000 };
    static const uint16_t w18[CH_NV] = { 0, 0, 0, 2000 };
    static const uint16_t none[CH_NV] = { 0, 0, 0, 500 };

    check(charger_pick(w65, 90000, 0xFFFF, 0) == 0, "65 W: not 20 V");
    check(charger_pick(w45, 90000, 0xFFFF, 0) == 1, "45 W: not 15 V");
    check(charger_pick(w30, 90000, 0xFFFF, 0) == 1, "30 W: not 15 V");
    check(charger_pick(w20, 90000, 0xFFFF, 0) == 2, "20 W: not 12 V");
    check(charger_pick(w18, 90000, 0xFFFF, 0) == 3, "18 W: not 9 V");
    check(charger_pick(none, 90000, 0xFFFF, 0) == -1, "9 V / 0.5 A accepted");
    check(charger_pick(w65, 79000, 0xFFFF, 0) == 0, "65 W, 7.9 ohm: not 20 V");
    check(charger_pick(w45, 79000, 0xFFFF, 0) == 1, "45 W, 7.9 ohm: not 15 V");
    check(charger_pick(w65, 90000, 19999, 0) == 1, "step-down below 20 V does not give 15 V");
    check(charger_pick(w65, 66000, 0xFFFF, 0) == 1, "6.6 ohm on 20 V / 3.25 A accepted (needs 3.27 A)");
    /* margin: 20 V / 9 ohm = 2.222 A, x 1.08 = 2.4 A */
    {
        uint16_t edge[CH_NV] = { 2400, 0, 0, 0 };

        check(charger_pick(edge, 90000, 0xFFFF, 0) == 0, "offer equal to 1.08 x V/R20 rejected");
        edge[0] = 2350;
        check(charger_pick(edge, 90000, 0xFFFF, 0) == -1, "offer below 1.08 x V/R20 accepted");
    }
    check(charger_pick(w65, 0, 0xFFFF, 0) == -1, "selection without a resistance");
    check(est_r20(118290, 100000) >= 89950 && est_r20(118290, 100000) <= 90050, "R20 from 11.829 ohm at 100 C: %u",
          (unsigned)est_r20(118290, 100000));
    report("pick-rule", "ok");
}

static int flashes_per_cycle(led_mode_t mode, uint8_t code, int periods, int *lit)
{
    led_t l = { .mode = 0xFF };
    int i, prev = 0, rises = 0;

    *lit = 0;
    for (i = 0; i < periods; i++) {
        int on = led_step(&l, mode, code);

        rises += on && !prev;
        *lit += on;
        prev = on;
    }
    return rises;
}

static void test_led(void)
{
    int lit, code;

    check(flashes_per_cycle(LED_NEGOTIATE, 0, 50, &lit) == 10 && lit == 20, "negotiating: not a 5 Hz blink");
    flashes_per_cycle(LED_HEATING, 0, 50, &lit);
    check(lit == 50, "heating: not solid");
    flashes_per_cycle(LED_AT_TEMP, 0, 100, &lit);
    check(lit == 100 - 2 * 3, "at temperature: not one 120 ms off-blip per 2 s");
    flashes_per_cycle(LED_WEAK, 0, 100, &lit);
    check(lit == 100 - 4 * 3, "weak charger: not two off-blips per 2 s");
    check(flashes_per_cycle(LED_NO_POWER, 0, 100, &lit) == 2 && lit == 50, "no power: not 1 s on / 1 s off");
    for (code = 1; code <= 6; code++) {
        int cycle = code * 10 + 30;

        check(flashes_per_cycle(LED_FAULT, (uint8_t)code, cycle, &lit) == code && lit == code * 5,
              "fault %d: wrong number of flashes", code);
        check(flashes_per_cycle(LED_FAULT, (uint8_t)code, 3 * cycle, &lit) == 3 * code, "fault %d: cycle does not repeat", code);
    }
    report("led-patterns", "ok");
}

/* the no-rise check replaces the cross-check when there is no T_R */
static void test_no_rise(void)
{
    fault_t f = { 0 };
    sense_t s = { .off_valid = 0, .on_valid = 1, .ntc_state = NTC_OK, .vbus_mv = 12000, .von_mv = 12000,
                  .ion_ma = 1300, .t_ntc_mc = 60000 };
    est_t e = { 0 };                            /* no reference: T_R unavailable */
    unsigned flags = 0;
    int i, tripped_at = -1;

    for (i = 0; i < 3000 && tripped_at < 0; i++) {
        flags = fault_step(&f, &s, &e, 1000, 12000, 0);
        if (flags & FLT_BIT(FAULT_SENSOR)) {
            tripped_at = i + 1;
        }
    }
    check(tripped_at == NORISE_PERIODS, "flat NTC at full duty: tripped after %d periods, expected %d", tripped_at, NORISE_PERIODS);
    check((flags & ~FLT_BIT(FAULT_SENSOR)) == 0, "other flags set: 0x%x", flags);

    memset(&f, 0, sizeof f);                    /* NTC rising 3 K per 90 s: fine */
    for (i = 0, flags = 0; i < 3 * NORISE_PERIODS; i++) {
        s.t_ntc_mc = 60000 + i * 3000 / NORISE_PERIODS;
        flags |= fault_step(&f, &s, &e, 1000, 12000, 0);
    }
    check(flags == 0, "tripped although the NTC rises (0x%x)", flags);

    memset(&f, 0, sizeof f);                    /* 9 V: too little power to demand a rise */
    s.t_ntc_mc = 60000;
    s.vbus_mv = s.von_mv = 9000;
    for (i = 0, flags = 0; i < 3 * NORISE_PERIODS; i++) {
        flags |= fault_step(&f, &s, &e, 1000, 9000, 0);
    }
    check(flags == 0, "tripped at 9 V (0x%x)", flags);

    memset(&f, 0, sizeof f);                    /* 80 % duty: not checked */
    s.vbus_mv = s.von_mv = 12000;
    for (i = 0, flags = 0; i < 3 * NORISE_PERIODS; i++) {
        flags |= fault_step(&f, &s, &e, 800, 12000, 0);
    }
    check(flags == 0, "tripped at 80 %% duty (0x%x)", flags);

    memset(&f, 0, sizeof f);                    /* with a valid T_R the cross-check is used instead */
    e.r0_x = 90000;
    e.tr_valid = 1;
    e.tr_mc = 62000;
    for (i = 0, flags = 0; i < 3 * NORISE_PERIODS; i++) {
        flags |= fault_step(&f, &s, &e, 1000, 12000, 0);
    }
    check(flags == 0, "no-rise check active although T_R is available (0x%x)", flags);
    e.tr_mc = 60000 + XCHECK_MK + 1000;
    for (i = 0, tripped_at = -1; i < 1000 && tripped_at < 0; i++) {
        if (fault_step(&f, &s, &e, 1000, 12000, 0) & FLT_BIT(FAULT_SENSOR)) {
            tripped_at = i + 1;
        }
    }
    check(tripped_at == XCHECK_PERIODS, "cross-check tripped after %d periods, expected %d", tripped_at, XCHECK_PERIODS);
    report("no-rise+xcheck", "trip after %ds / %ds", NORISE_PERIODS / PWM_HZ, XCHECK_PERIODS / PWM_HZ);
}

/* ---------------------------------------------------------------- scenarios */

static void scn_65w(void)
{
    win_t w;
    double rate;

    sim_defaults();
    OFFERS(W65);
    start();
    win_init(&w, 120, 300);
    run_to(300, &w, NULL);
    check(app.ch.sel_mv == 20000, "selected %d mV, expected 20 V", app.ch.sel_mv);
    check(sim.t99 > 0 && sim.t99 <= 45, "99 C reached at %.1f s (limit 45 s)", sim.t99);
    check(sim.top_max <= 106, "peak %.1f C (limit 106 C)", sim.top_max);
    check_settled(&w, 1.5, 99, 103);
    check(win_power(&w) > 9.3 && win_power(&w) < 10.7, "holding takes %.2f W, expected about 10 W", win_power(&w));
    check(app.fault == FAULT_NONE && app.state == ST_HOLD, "state %d fault %d at the end", app.state, app.fault);
    check(app.e.trusted && obs.used_r, "trace resistance not used for control");
    check(sim.n_requests == 0, "sent %d PD requests although the chip already had 20 V", sim.n_requests);
    check_no_supply_abuse();
    rate = led_rate(20);
    check(fabs(rate - 1.0) < 0.11, "LED not in the at-temperature pattern (%.2f edges/s)", rate);
    check(sim.log_lines >= 300 && sim.log_lines <= 322, "%d log lines in 320 s", sim.log_lines);
    report("1-65W", "20V t99=%.1fs peak=%.1fC settled=%.2f..%.2fC mean=%.2fC hold=%.1fW",
           sim.t99, sim.top_max, w.lo, w.hi, win_mean(&w), win_power(&w));
}

static void scn_45w(void)
{
    win_t w;

    sim_defaults();
    OFFERS(W45);
    start();
    win_init(&w, 150, 300);
    run_to(300, &w, NULL);
    check(app.ch.sel_mv == 15000, "selected %d mV, expected 15 V", app.ch.sel_mv);
    check(app.ch.limit_ma == 3000, "contract current %d mA, expected 3000", app.ch.limit_ma);
    check(app.fault == FAULT_NONE, "fault %d", app.fault);
    check(sim.t99 > 0, "never reached 99 C");
    check_settled(&w, 1.5, 99, 103);
    check_no_supply_abuse();
    report("2-45W", "15V imax=%.2fA/%.2fA t99=%.1fs", sim.i_max, sim.contract_ma / 1000.0, sim.t99);
}

static void scn_30w(void)
{
    sim_defaults();
    OFFERS(W30);
    start();
    run_to(200, NULL, NULL);
    check(app.ch.sel_mv == 15000, "selected %d mV, expected 15 V", app.ch.sel_mv);
    check(sim.contract_mv == 15000 && fabs(sim.v_src - 15.0) < 0.01, "source is at %.2f V", sim.v_src);
    check(sim.n_requests == 1, "%d PD requests, expected 1 (9 V -> 15 V)", sim.n_requests);
    check(app.fault == FAULT_NONE, "fault %d", app.fault);
    check(sim.t99 > 0, "never reached 99 C");
    check_no_supply_abuse();
    report("3-30W", "15V (asked, was 9V) imax=%.2fA/%.2fA t99=%.1fs", sim.i_max, sim.contract_ma / 1000.0, sim.t99);
}

static void scn_20w(void)
{
    sim_defaults();
    OFFERS(W20);
    start();
    run_to(300, NULL, NULL);
    check(app.ch.sel_mv == 12000, "selected %d mV, expected 12 V", app.ch.sel_mv);
    check(sim.t99 > 0 && sim.t99 <= 240, "99 C reached at %.1f s (limit 240 s)", sim.t99);
    check(app.fault == FAULT_NONE, "fault %d", app.fault);
    check(!app.weak, "12 V flagged as weak charger");
    check_no_supply_abuse();
    report("4-20W", "12V imax=%.2fA/%.2fA t99=%.1fs", sim.i_max, sim.contract_ma / 1000.0, sim.t99);
}

static void scn_5v(void)
{
    win_t w;
    double rate;

    sim_defaults();
    OFFERS(W5);
    start();
    win_init(&w, 0, 60);
    run_to(60, &w, NULL);
    check(app.state == ST_NO_POWER, "state %d, expected no-power", app.state);
    check(w.energy == 0 && obs.max_duty == 0, "heater was switched on (%.3f J)", w.energy);
    check(sim.top_max < PLANT_T_AMB + 0.01, "plate warmed up to %.2f C", sim.top_max);
    check(sim.n_requests == 0, "sent PD requests");
    check(app.fault == FAULT_NONE, "fault %d", app.fault);
    rate = led_rate(20);
    check(fabs(rate - 1.0) < 0.11 && app.led.mode == LED_NO_POWER, "LED not in the no-power pattern (%.2f edges/s)", rate);
    report("5-5V-only", "heat=%.0fJ state=no-power", w.energy);
}

static void scn_ntc_open(void)
{
    double rate;

    sim_defaults();
    sim.t_ntc_open = 100;
    start();
    run_to(200, NULL, NULL);
    check(app.fault == FAULT_NTC && app.state == ST_FAULT, "state %d fault %d, expected NTC fault", app.state, app.fault);
    check(sim.t_last_gate_heat > 99 && sim.t_last_gate_heat <= 101, "heater last on at %.3f s", sim.t_last_gate_heat);
    check(obs.t_fault > 100 && obs.t_fault <= 101, "fault latched at %.2f s", obs.t_fault);
    rate = led_rate(16);
    check(fabs(rate - 2.0 / 1.6) < 0.13, "LED not flashing code 1 (%.2f edges/s)", rate);
    check(app.fault == FAULT_NTC && sim.t_last_gate_heat <= 101, "fault did not stay latched");
    report("6-ntc-open", "off after %.0fms, fault %d latched", (sim.t_last_gate_heat - 100) * 1e3, app.fault);
}

static void scn_switch_short(void)
{
    sim_defaults();
    sim.t_switch_short = 100;
    start();
    run_to(250, NULL, NULL);
    check(app.fault == FAULT_SWITCH_SHORT, "fault %d, expected %d", app.fault, FAULT_SWITCH_SHORT);
    check(sim.t_req_5v > 100 && sim.t_req_5v <= 102, "5 V demanded at %.2f s", sim.t_req_5v);
    check(sim.vset_low, "VSET not pulled low");
    check(sim.contract_mv == 5000 && sim.v_src < 5.1, "source still at %.1f V", sim.v_src);
    check(sim.top_max < 130, "top copper reached %.1f C (limit 130 C)", sim.top_max);
    report("7-switch-short", "fault %d, 5V asked after %.0fms, peak=%.1fC",
           app.fault, (sim.t_req_5v - 100) * 1e3, sim.top_max);
}

static void scn_ntc_stuck(void)
{
    sim_defaults();
    sim.ntc_stuck_c = 60;
    start();
    run_to(250, NULL, NULL);
    check(app.fault != FAULT_NONE, "no fault");
    check(sim.top_max < 140, "top copper reached %.1f C (limit 140 C)", sim.top_max);
    check(!obs.used_r, "T_R used for control with a reference captured at %d m°C", (int)app.e.t0_mc);
    report("8-ntc-stuck-60C", "fault %d at %.1fs, top=%.1fC", app.fault, obs.t_fault, sim.top_max);
}

static void scn_low_r(void)
{
    double i60;

    sim_defaults();
    sim.r20 = 7.9;
    OFFERS(W60);
    start();
    run_to(200, NULL, NULL);
    check(app.ch.sel_mv == 20000, "60 W: selected %d mV, expected 20 V", app.ch.sel_mv);
    check(app.fault == FAULT_NONE && app.oc_events == 0, "60 W: fault %d, %d over-current events", app.fault, app.oc_events);
    check(sim.t99 > 0, "60 W: never reached 99 C");
    check_no_supply_abuse();
    i60 = sim.i_max;

    sim_defaults();
    sim.r20 = 7.9;
    OFFERS(W45);
    start();
    run_to(200, NULL, NULL);
    check(app.ch.sel_mv == 15000, "45 W: selected %d mV, expected 15 V", app.ch.sel_mv);
    check(app.fault == FAULT_NONE && app.oc_events == 0, "45 W: fault %d, %d over-current events", app.fault, app.oc_events);
    check(sim.t99 > 0, "45 W: never reached 99 C");
    check_no_supply_abuse();
    report("9-7.9ohm", "60W:20V imax=%.2fA/3A; 45W:15V imax=%.2fA/3A", i60, sim.i_max);
}

static void scn_load_step(void)
{
    win_t before, after, dip;

    sim_defaults();
    sim.t_load = 150;
    sim.load_h = 30;
    start();
    win_init(&before, 120, 150);
    run_to(150, &before, NULL);
    win_init(&dip, 150, 200);
    win_init(&after, 250, 300);
    run_to(300, &dip, &after);
    check(fabs(win_mean(&after) - win_mean(&before)) <= 2.0, "mean %.2f C before, %.2f C after", win_mean(&before), win_mean(&after));
    check(after.lo >= win_mean(&before) - 2.0 && after.hi <= win_mean(&before) + 2.0,
          "after the step %.2f .. %.2f C, before %.2f C", after.lo, after.hi, win_mean(&before));
    check(win_power(&after) > win_power(&before) + 2.0, "power did not rise (%.1f -> %.1f W)", win_power(&before), win_power(&after));
    check(app.fault == FAULT_NONE, "fault %d", app.fault);
    report("10-load-step", "before=%.2fC dip=%.2fC after=%.2f..%.2fC", win_mean(&before), dip.lo, after.lo, after.hi);
}

static void scn_warm_start(void)
{
    win_t w;

    sim_defaults();
    sim.t_start = 80;
    start();
    win_init(&w, 120, 300);
    run_to(300, &w, NULL);
    check(!app.e.trusted, "resistance reference trusted although captured at %d m°C", (int)app.e.t0_mc);
    check(!obs.used_r, "T_R was used for control");
    check(app.fault == FAULT_NONE, "fault %d", app.fault);
    check(sim.top_max <= 106, "peak %.1f C", sim.top_max);
    check_settled(&w, 1.5, 99, 103);
    check_no_supply_abuse();
    report("11-warm-start", "NTC-only peak=%.1fC settled=%.2f..%.2fC mean=%.2fC", sim.top_max, w.lo, w.hi, win_mean(&w));
}

/* ----------------------------------------------------- additional scenarios */

static void scn_no_pd_chip(void)
{
    double t99;

    sim_defaults();
    sim.pd_absent = 1;
    sim.fixed_vbus = 12.0;
    start();
    run_to(300, NULL, NULL);
    check(app.ch.sel_mv > 11500 && app.ch.sel_mv < 12500, "selected %d mV on a 12 V supply", app.ch.sel_mv);
    check(app.ch.limit_ma == 0, "contract current %d although unknown", app.ch.limit_ma);
    check(sim.t99 > 0 && sim.t99 < 240, "99 C at %.1f s", sim.t99);
    check(app.fault == FAULT_NONE, "fault %d", app.fault);
    t99 = sim.t99;

    sim_defaults();
    sim.pd_absent = 1;
    sim.fixed_vbus = 5.0;
    start();
    run_to(30, NULL, NULL);
    check(app.state == ST_NO_POWER && obs.max_duty == 0, "5 V without PD chip: state %d, duty %d", app.state, obs.max_duty);
    report("12-no-i2c", "12V supply: t99=%.1fs; 5V supply: no-power", t99);
}

static void scn_request_rejected(void)
{
    double rate;

    sim_defaults();
    OFFERS(W30);
    sim.reject_mv = 15000;
    start();
    run_to(120, NULL, NULL);
    check(app.ch.sel_mv == 9000, "selected %d mV, expected 9 V after the 15 V request failed", app.ch.sel_mv);
    check(app.weak && app.state == ST_HEAT, "weak %d state %d", app.weak, app.state);
    check(app.fault == FAULT_NONE, "fault %d", app.fault);
    check(plant_t_top(&sim.plant) > 60, "not heating at 9 V (%.1f C)", plant_t_top(&sim.plant));
    check_no_supply_abuse();
    rate = led_rate(20);
    check(fabs(rate - 2.0) < 0.11 && app.led.mode == LED_WEAK, "LED not in the weak-charger pattern (%.2f edges/s)", rate);
    report("13-request-refused", "falls back to 9V, weak-charger code");
}

static void scn_slow_pd(void)
{
    sim_defaults();
    sim.pd_ready_s = 2.4;
    start();
    run_to(60, NULL, NULL);
    check(app.ch.sel_mv == 20000 && app.ch.pd_ok, "selected %d mV, pd_ok %d", app.ch.sel_mv, app.ch.pd_ok);
    check(sim.t99 > 0 && sim.t99 <= 45, "99 C at %.1f s", sim.t99);
    check_no_supply_abuse();
    report("14-slow-pd", "20V t99=%.1fs", sim.t99);
}

static void scn_overcurrent(void)
{
    double oc1;
    int fault1;

    sim_defaults();                             /* heater falls to 45 %: 3.7 A at 20 V, 2.8 A at 15 V */
    sim.t_heater_r = 60;
    sim.heater_r_factor = 0.45;
    start();
    run_to(66, NULL, NULL);
    check(app.oc_events == 1 && app.fault == FAULT_NONE, "%d over-current events, fault %d", app.oc_events, app.fault);
    check(app.ch.sel_mv == 15000 && sim.contract_mv == 15000, "selected %d mV, expected a step down to 15 V", app.ch.sel_mv);
    check(app.state == ST_HEAT || app.state == ST_HOLD, "state %d, expected heating again", app.state);
    check(sim.oc_time < 0.05, "over the contract current for %.0f ms", sim.oc_time * 1e3);
    check(sim.trans_heat_time == 0, "heater on during the voltage change");
    oc1 = sim.oc_time;
    run_to(90, NULL, NULL);                     /* a heater at 45 % no longer fits its temperature */
    check(app.fault == FAULT_SENSOR, "fault %d, expected the cross-check to stop it", app.fault);
    check(sim.oc_time == oc1, "more over-current after the step down");
    fault1 = app.fault;

    sim_defaults();                             /* down to 30 %: 5.6 A at 20 V, 4.2 A at 15 V */
    sim.t_heater_r = 60;
    sim.heater_r_factor = 0.30;
    start();
    run_to(120, NULL, NULL);
    check(app.fault == FAULT_OVERCURRENT && app.state == ST_FAULT, "state %d fault %d, expected over-current", app.state, app.fault);
    check(app.oc_events == 2, "%d over-current events", app.oc_events);
    check(sim.oc_time < 0.05, "over the contract current for %.0f ms", sim.oc_time * 1e3);
    check(sim.t_last_gate_heat < 62, "heater still on at %.1f s", sim.t_last_gate_heat);
    report("15-over-current", "1st: off in %.0fms, steps to 15V (then fault %d); repeat: fault %d",
           oc1 * 1e3, fault1, app.fault);
}

static void scn_heater_open(void)
{
    sim_defaults();
    sim.t_heater_open = 50;
    start();
    run_to(80, NULL, NULL);
    check(app.fault == FAULT_HEATER_OPEN, "fault %d, expected %d", app.fault, FAULT_HEATER_OPEN);
    check(obs.t_fault > 50 && obs.t_fault < 51, "fault at %.2f s", obs.t_fault);
    report("16-heater-open", "fault %d after %.0fms", app.fault, (obs.t_fault - 50) * 1e3);
}

static void scn_wrong_heater(void)
{
    sim_defaults();                             /* 5 ohm: would draw 4 A at 20 V */
    sim.r20 = 5.0;
    start();
    run_to(30, NULL, NULL);
    check(app.fault == FAULT_HEATER_OPEN && app.state == ST_FAULT, "5 ohm: state %d fault %d", app.state, app.fault);
    check(sim.t_last_gate_heat < 2.0, "5 ohm: heater on at %.2f s", sim.t_last_gate_heat);
    check(sim.top_max < PLANT_T_AMB + 1.0, "5 ohm: plate warmed to %.2f C", sim.top_max);   /* one 3.4 ms pulse */

    sim_defaults();                             /* 13 ohm: e.g. wrong sense gain */
    sim.r20 = 13.0;
    start();
    run_to(30, NULL, NULL);
    check(app.fault == FAULT_HEATER_OPEN && app.state == ST_FAULT, "13 ohm: state %d fault %d", app.state, app.fault);
    check(sim.t_last_gate_heat < 2.0, "13 ohm: heater on at %.2f s", sim.t_last_gate_heat);
    report("23-wrong-heater", "5/13ohm: fault %d after the probe pulse", app.fault);
}

static void scn_overtemp(void)
{
    sim_defaults();
    sim.t_ntc_offset = 100;
    sim.ntc_offset_k = 35;
    start();
    run_to(130, NULL, NULL);
    check(app.fault == FAULT_OVERTEMP, "fault %d, expected %d", app.fault, FAULT_OVERTEMP);
    check(sim.t_req_5v > 100 && sim.t_req_5v < 101, "5 V demanded at %.2f s", sim.t_req_5v);
    check(sim.vset_low && sim.contract_mv == 5000, "VSET %d, contract %d mV", sim.vset_low, sim.contract_mv);
    check(sim.t_last_gate_heat < 101, "heater still on at %.1f s", sim.t_last_gate_heat);
    report("17-over-temp", "fault %d, 5V asked after %.0fms", app.fault, (sim.t_req_5v - 100) * 1e3);
}

static void scn_vbus_dropout(void)
{
    win_t w;
    double t_off;

    sim_defaults();
    sim.t_src_drop = 80;
    sim.src_drop_s = 2.0;
    start();
    run_to(82, NULL, NULL);
    t_off = sim.t_last_gate_heat;
    check(app.state == ST_NEGOTIATE, "state %d while VBUS is at 5 V", app.state);
    win_init(&w, 150, 220);
    run_to(220, &w, NULL);
    check(t_off < 80.5, "heater still on %.0f ms after VBUS fell", (t_off - 80) * 1e3);
    check(app.fault == FAULT_NONE && app.ch.sel_mv == 20000, "fault %d, %d mV", app.fault, app.ch.sel_mv);
    check_settled(&w, 1.5, 99, 103);
    check(sim.trans_heat_time == 0, "heater on while the source returned to 20 V");
    report("18-vbus-dropout", "off after %.0fms, reselects, mean=%.2fC", (t_off - 80) * 1e3, win_mean(&w));
}

static void scn_ntc2(void)
{
    win_t w;
    int ok_float;

    sim_defaults();                             /* floating pin, as in every other test */
    start();
    win_init(&w, 120, 200);
    run_to(200, &w, NULL);
    ok_float = app.s.ntc2_ok;

    sim_defaults();
    sim.ntc2_fitted = 1;
    start();
    win_init(&w, 120, 200);
    run_to(200, &w, NULL);
    check(!ok_float, "floating NTC2 pin accepted as a sensor");
    check(app.s.ntc2_ok, "fitted NTC2 not recognised");
    check(app.fault == FAULT_NONE, "fault %d", app.fault);
    check_settled(&w, 1.5, 99, 103);
    report("19-ntc2", "fitted: used; floating: ignored");
}

static void scn_ntc_detached_cold(void)
{
    sim_defaults();
    sim.ntc_stuck_c = 25;
    start();
    run_to(200, NULL, NULL);
    check(app.fault == FAULT_SENSOR, "fault %d, expected %d", app.fault, FAULT_SENSOR);
    check(sim.top_max < 140, "top copper reached %.1f C", sim.top_max);
    report("20-ntc-stuck-25C", "fault %d at %.1fs, top=%.1fC", app.fault, obs.t_fault, sim.top_max);
}

/* the controller wants no heat at all: one measurement pulse per second keeps T_R alive */
static void scn_measurement_pulses(void)
{
    win_t w;
    int pulses = 0, other = 0, max_age = 0;
    double worst = 0;

    sim_defaults();
    sim.t_ext = 150;
    sim.p_ext_w = 11.5;
    start();
    run_to(200, NULL, NULL);
    win_init(&w, 200, 260);
    while (sim.t < 260 - 1e-9) {
        run_to(sim.t + PWM_PERIOD_MS / 1000.0, &w, NULL);
        pulses += app.duty == MEAS_PULSE_DUTY;
        other += app.duty != MEAS_PULSE_DUTY && app.duty != 0;
        max_age = app.e.age > max_age ? app.e.age : max_age;
        worst = fmax(worst, fabs(app.e.tr_mc / 1000.0 - sim.p_top_mean));
    }
    check(win_mean(&w) > 103, "plate at %.1f C: the external heat does not saturate the controller", win_mean(&w));
    check(pulses >= 58 && pulses <= 62 && other == 0, "%d measurement pulses and %d other non-zero duties in 60 s", pulses, other);
    check(max_age <= MEAS_INTERVAL + 2 && app.e.tr_valid && app.e.uses_r, "T_R went stale (age %d periods)", max_age);
    check(worst < 1.5, "T_R off by %.2f K from the top copper", worst);
    check(win_power(&w) < 0.5, "pulses add %.2f W", win_power(&w));
    check(app.fault == FAULT_NONE, "fault %d", app.fault);
    report("21-meas-pulses", "duty 0: %d pulses/min, T_R within %.2fK", pulses, worst);
}

/* board-to-board and set-up tolerances: no combination may overload a charger */
static void scn_tolerances(void)
{
    static const struct { const char *name; const sim_offer_t *o; int n; } chg[] = {
        { "65", W65, 4 }, { "60", W60, 4 }, { "45", W45, 4 }, { "30", W30, 4 }, { "20", W20, 3 },
    };
    static const double r20[] = { 7.92, 9.0, 10.08 };
    static const int cand_mv[] = { 20000, 15000, 12000, 9000 };
    static const int code_ma[16] = { 500, 700, 1000, 1250, 1500, 1750, 2000, 2250, 2500, 2750, 3000, 3250, 3500, 4000, 4500, 5000 };
    unsigned c, r, v;
    int runs = 0, k, j;

    for (r = 0; r < 3; r++) {
        for (c = 0; c < 5; c++) {
            int expect = 0;

            /* the rule, from the true resistance: highest voltage whose offer (as the PD
             * chip reports it) covers 1.08 x V / R20 */
            for (v = 0; v < 4 && expect == 0; v++) {
                for (j = 0; j < chg[c].n; j++) {
                    if (chg[c].o[j].mv == cand_mv[v]) {
                        for (k = 15; k > 0 && code_ma[k] > chg[c].o[j].ma; k--) {
                        }
                        if (code_ma[k] >= 1.08 * cand_mv[v] / (r20[r] + 0.04)) {
                            expect = cand_mv[v];
                        }
                    }
                }
            }
            sim_defaults();
            sim_set_offers(chg[c].o, chg[c].n);
            sim.r20 = r20[r];
            sim.isense_zero_v = (runs % 3) * 0.015;         /* 0, 15, 30 mV */
            sim.r_cable = runs % 2 ? 0.25 : 0.05;
            sim.adc_noise_lsb = 1.5;
            start();
            run_to(150, NULL, NULL);
            runs++;
            check(app.ch.sel_mv == expect, "%.2f ohm on %s W: selected %d mV, expected %d", r20[r], chg[c].name, app.ch.sel_mv, expect);
            check(app.fault == FAULT_NONE && app.oc_events == 0, "%.2f ohm on %s W: fault %d, %d over-current events",
                  r20[r], chg[c].name, app.fault, app.oc_events);
            check(sim.oc_time == 0 && sim.trans_heat_time == 0, "%.2f ohm on %s W: %.1f ms over the contract current (%.2f A of %.2f A)",
                  r20[r], chg[c].name, sim.oc_time * 1e3, sim.i_max, sim.contract_ma / 1000.0);
            check(expect < 12000 || plant_t_top(&sim.plant) > (expect >= 15000 ? 99.0 : 85.0), "%.2f ohm on %s W: only %.1f C after 150 s",
                  r20[r], chg[c].name, plant_t_top(&sim.plant));
        }
    }
    report("22-tolerances", "%d R20/charger combinations, none over contract current", runs);
}

static void test_log_format(void)
{
    int v[11], n, len;
    char tail;

    sim_defaults();
    start();
    run_to(60, NULL, NULL);
    len = (int)strlen(sim.last_log);
    n = sscanf(sim.last_log, "%d %d %d %d %d %d %d %d %d %d %d%c", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6],
               &v[7], &v[8], &v[9], &v[10], &tail);
    check(n == 12 && tail == '\r' && len > 2 && sim.last_log[len - 1] == '\n', "log line is not 11 integers + CR LF: \"%s\"", sim.last_log);
    if (n == 12) {
        check(v[0] == 60 && v[1] == ST_HOLD && v[9] == 20 && v[10] == 0, "t %d state %d Vsel %d fault %d", v[0], v[1], v[9], v[10]);
        check(abs(v[2] - 20000) < 300, "VBUS %d mV", v[2]);
        check(v[4] > 11000 && v[4] < 12500, "R %d mohm", v[4]);
        check(abs(v[5] - 1000) < 30 && abs(v[6] - 1010) < 40 && abs(v[7] - 1000) < 30, "T_NTC %d T_R %d T_ctl %d (0.1 C)", v[5], v[6], v[7]);
        check(v[8] > 150 && v[8] < 500, "duty %d", v[8]);
    }
    sim.last_log[len > 2 ? len - 2 : 0] = 0;
    report("uart-log", "\"%s\"", sim.last_log);
}

int main(void)
{
    test_ntc_table();
    test_plant();
    test_pi();
    test_pick();
    test_led();
    test_no_rise();
    test_log_format();
    scn_65w();
    scn_45w();
    scn_30w();
    scn_20w();
    scn_5v();
    scn_ntc_open();
    scn_switch_short();
    scn_ntc_stuck();
    scn_low_r();
    scn_load_step();
    scn_warm_start();
    scn_no_pd_chip();
    scn_request_rejected();
    scn_slow_pd();
    scn_overcurrent();
    scn_heater_open();
    scn_overtemp();
    scn_vbus_dropout();
    scn_ntc2();
    scn_ntc_detached_cold();
    scn_measurement_pulses();
    scn_tolerances();
    scn_wrong_heater();

    if (tests_failed) {
        printf("%d test(s) FAILED\n", tests_failed);
        return 1;
    }
    printf("all tests passed\n");
    return 0;
}
