#include "sim.h"
#include "../src/app.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

sim_t sim;

#define PERIOD_S        (PWM_PERIOD_MS / 1000.0)
#define DT              (PERIOD_S / SIM_SUBSTEPS)
#define TICKS_PER_SUB   (PWM_STEPS / SIM_SUBSTEPS)
#define ON_SAMPLE_SUB   ((ON_SAMPLE_TICK + SAMPLE_TICKS / 2) / TICKS_PER_SUB)
#define OFF_SAMPLE_SUB  ((OFF_SAMPLE_TICK + SAMPLE_TICKS / 2) / TICKS_PER_SUB)

#define VREF            3.3
#define NTC_R25         100e3
#define NTC_B           3950.0
#define NTC_PULLUP      22e3
#define VBUS_SLEW       60.0        /* V/s */
#define PD_REQ_DELAY    0.08        /* request -> source starts to move */
#define PD_SETTLE       0.03        /* voltage reached -> PS_RDY */
#define PD_AUTO_MA      2500        /* the chip alone takes the highest offer with this much */

static const int code_ma[16] = {
    500, 700, 1000, 1250, 1500, 1750, 2000, 2250, 2500, 2750, 3000, 3250, 3500, 4000, 4500, 5000
};

/* ------------------------------------------------------------------ helpers */

static double frand(void)           /* uniform 0..1, deterministic */
{
    sim.rng = sim.rng * 1664525u + 1013904223u;
    return (sim.rng >> 8) / 16777216.0;
}

static double gauss(void)
{
    return (frand() + frand() + frand() + frand() - 2.0) * 1.7320508;
}

double sim_ntc_ratio(double t_c)
{
    double r = NTC_R25 * exp(NTC_B * (1 / (t_c + 273.15) - 1 / 298.15));

    return r / (r + NTC_PULLUP);
}

static int active(double t_event)
{
    return t_event >= 0 && sim.t >= t_event;
}

/* sum of ADC_OVERSAMPLE noisy 12-bit conversions */
static uint16_t adc(double volts)
{
    unsigned acc = 0;
    int i;

    for (i = 0; i < ADC_OVERSAMPLE; i++) {
        double x = floor(volts / VREF * 4096.0 + sim.adc_noise_lsb * gauss());

        acc += (unsigned)(x < 0 ? 0 : x > 4095 ? 4095 : x);
    }
    return (uint16_t)acc;
}

/* ------------------------------------------------------- source and PD chip */

static const sim_offer_t *find_offer(int mv)
{
    int i;

    for (i = 0; i < sim.n_offers; i++) {
        if (sim.offers[i].mv == mv) {
            return &sim.offers[i];
        }
    }
    return NULL;
}

static void set_contract(int mv, int ma)
{
    sim.contract_mv = mv;
    sim.contract_ma = ma;
    sim.v_target = mv / 1000.0;
    sim.t_trans_end = sim.t + fabs(sim.v_target - sim.v_src) / VBUS_SLEW + PD_SETTLE;
}

/* what the HUSB238 does by itself: highest voltage that can supply 2.5 A, else 5 V */
static void auto_contract(void)
{
    const sim_offer_t *best = find_offer(5000);
    int i;

    for (i = 0; i < sim.n_offers; i++) {
        if (sim.offers[i].ma >= PD_AUTO_MA && (best == NULL || sim.offers[i].mv > best->mv)) {
            best = &sim.offers[i];
        }
    }
    if (best != NULL) {
        set_contract(best->mv, best->ma);
    }
}

static void request(int mv, double delay)
{
    sim.req_mv = mv;
    sim.t_req_apply = sim.t + delay;
    sim.pd_response = 0;
    sim.t_trans_end = sim.t + delay + PD_SETTLE;    /* the heater must be off from now on */
    if (mv == 5000 && sim.t_req_5v < 0) {
        sim.t_req_5v = sim.t;
    }
}

static void source_step(double i_heater, double on_time)
{
    if (sim.pd_absent) {
        sim.v_src = sim.fixed_vbus;
        return;
    }
    if (!sim.auto_done && sim.t >= sim.pd_ready_s - 0.2) {
        auto_contract();
        sim.auto_done = 1;
    }
    if (!sim.pd_listed && sim.t >= sim.pd_ready_s) {
        sim.pd_listed = 1;
    }
    if (sim.t_src_drop >= 0 && !sim.dropped && sim.t >= sim.t_src_drop) {
        const sim_offer_t *o = find_offer(5000);

        sim.dropped = 1;                            /* e.g. a second device was plugged in */
        sim.pd_listed = 0;
        sim.auto_done = 0;
        sim.pd_ready_s = sim.t + sim.src_drop_s;
        set_contract(5000, o ? o->ma : 3000);
        sim.t_trans_end = 0;                        /* not the firmware's doing */
        sim.v_src = 5.0;
    }
    if (sim.req_mv != 0 && sim.t >= sim.t_req_apply) {
        const sim_offer_t *o = find_offer(sim.req_mv);

        if (o != NULL && sim.req_mv != sim.reject_mv) {
            set_contract(o->mv, o->ma);
        } else {
            sim.pd_response = 5;                    /* fail */
        }
        sim.req_mv = 0;
    }
    if (sim.v_src < sim.v_target) {
        sim.v_src = fmin(sim.v_target, sim.v_src + VBUS_SLEW * DT);
    } else if (sim.v_src > sim.v_target) {
        sim.v_src = fmax(sim.v_target, sim.v_src - VBUS_SLEW * DT);
    }
    if (sim.t_trans_end > 0 && sim.t >= sim.t_trans_end && sim.req_mv == 0
        && sim.v_src == sim.v_target && sim.pd_response == 0) {
        sim.pd_response = 1;                        /* success */
    }

    if (on_time > 0) {
        if (i_heater > sim.contract_ma / 1000.0 * 1.0001) {
            sim.oc_time += on_time;
        }
        if (sim.t < sim.t_trans_end && i_heater > 0.05) {
            sim.trans_heat_time += on_time;
        }
    }
}

static uint8_t pdo_reg(int mv)
{
    const sim_offer_t *o = sim.pd_listed ? find_offer(mv) : NULL;
    int code = 0;

    if (o == NULL) {
        return 0;
    }
    while (code < 15 && code_ma[code + 1] <= o->ma) {
        code++;
    }
    return (uint8_t)(0x80 | code);
}

int hal_pd_read(uint8_t reg, uint8_t *val)
{
    static const int pdo_mv[6] = { 5000, 9000, 12000, 15000, 18000, 20000 };
    static const int mv_code[7] = { 0, 5000, 9000, 12000, 15000, 18000, 20000 };
    int i;

    if (sim.pd_absent) {
        return -1;
    }
    *val = 0;
    if (reg == 0x00 && sim.pd_listed) {
        for (i = 1; i < 7; i++) {
            if (mv_code[i] == sim.contract_mv) {
                *val = (uint8_t)(i << 4 | (pdo_reg(sim.contract_mv) & 0x0F));
            }
        }
    } else if (reg == 0x01) {
        *val = (uint8_t)((sim.pd_listed ? 0x40 : 0) | sim.pd_response << 3);
    } else if (reg >= 0x02 && reg <= 0x07) {
        *val = pdo_reg(pdo_mv[reg - 2]);
    } else if (reg == 0x08) {
        *val = sim.reg_sel;
    }
    return 0;
}

int hal_pd_write(uint8_t reg, uint8_t val)
{
    static const struct { uint8_t sel; int mv; } sel_mv[6] = {
        { 0x1, 5000 }, { 0x2, 9000 }, { 0x3, 12000 }, { 0x8, 15000 }, { 0x9, 18000 }, { 0xA, 20000 }
    };
    int i;

    if (sim.pd_absent) {
        return -1;
    }
    if (reg == 0x08) {
        sim.reg_sel = val;
    } else if (reg == 0x09) {
        if ((val & 0x1F) == 0x01) {                 /* request the selected PDO */
            sim.n_requests++;
            for (i = 0; i < 6; i++) {
                if (sel_mv[i].sel == sim.reg_sel >> 4) {
                    request(sel_mv[i].mv, PD_REQ_DELAY);
                }
            }
        } else if ((val & 0x1F) == 0x10) {
            sim.hard_resets++;                      /* would power-cycle the board */
        }
    }
    return 0;
}

void hal_vset_low(int low)
{
    if (low && !sim.vset_low && !sim.pd_absent) {
        request(5000, 0.05);
    }
    if (low && sim.t_req_5v < 0) {
        sim.t_req_5v = sim.t;
    }
    sim.vset_low = low;
}

/* ----------------------------------------------------------------- HAL rest */

void hal_pwm_set(uint16_t duty)
{
    sim.duty_cmd = duty > PWM_STEPS ? PWM_STEPS : duty;
}

void hal_heater_off(void)
{
    sim.duty_cmd = 0;
    sim.pin_af = 0;
    sim.dirty = 1;
}

void hal_led(int on)
{
    on = on != 0;
    if (on != sim.led) {
        sim.led_edges++;
    }
    sim.led = on;
}

void hal_log(const char *s, unsigned len)
{
    if (len >= sizeof sim.last_log) {
        len = sizeof sim.last_log - 1;
    }
    memcpy(sim.last_log, s, len);
    sim.last_log[len] = 0;
    sim.log_lines++;
    if (getenv("SIM_LOG") != NULL) {
        fputs(sim.last_log, stdout);
    }
}

/* -------------------------------------------------------------------- world */

void sim_defaults(void)
{
    static const sim_offer_t w65[] = { { 5000, 3000 }, { 9000, 3000 }, { 15000, 3000 }, { 20000, 3250 } };

    memset(&sim, 0, sizeof sim);
    sim.r20 = 9.0;
    sim.t_start = PLANT_T_AMB;
    sim.r_series = 0.04;
    sim.r_cable = 0.10;
    sim.isense_zero_v = 0.008;
    sim.adc_noise_lsb = 0.7;
    sim.pd_ready_s = 1.0;
    sim.fixed_vbus = 5.0;
    sim.ntc_stuck_c = NAN;
    sim.t_ntc_open = sim.t_ntc_offset = sim.t_switch_short = sim.t_load = -1;
    sim.t_heater_r = sim.t_heater_open = sim.t_src_drop = sim.t_ext = -1;
    sim.heater_r_factor = 1.0;
    sim_set_offers(w65, 4);
}

void sim_set_offers(const sim_offer_t *offers, int n)
{
    sim.n_offers = n;
    memcpy(sim.offers, offers, (size_t)n * sizeof offers[0]);
}

void sim_start(void)
{
    const sim_offer_t *o = find_offer(5000);

    plant_init(&sim.plant, sim.r20, sim.t_start);
    sim.t = 0;
    sim.rng = 12345;
    sim.v_src = sim.v_target = sim.pd_absent ? sim.fixed_vbus : 5.0;
    sim.contract_mv = 5000;
    sim.contract_ma = sim.pd_absent ? 100000 : o ? o->ma : 3000;
    sim.top_max = sim.t_start;
    sim.t99 = sim.t_req_5v = sim.t_last_gate_heat = -1;
    app_init();
}

static double ntc1_volts(void)
{
    double t = sim.plant.t_sensor;

    if (active(sim.t_ntc_open)) {
        return VREF;
    }
    if (!isnan(sim.ntc_stuck_c)) {
        t = sim.ntc_stuck_c;
    }
    if (active(sim.t_ntc_offset)) {
        t += sim.ntc_offset_k;
    }
    return VREF * sim_ntc_ratio(t);
}

static void sample(uint16_t out[ADC_NCH], double v_board, double i_heater)
{
    double v_i = i_heater * (ISENSE_MV_PER_A / 1000.0) + sim.isense_zero_v;
    double v_ntc2;

    if (sim.ntc2_fitted) {
        v_ntc2 = VREF * sim_ntc_ratio(0.6 * plant_t_top(&sim.plant) + 0.4 * plant_t_bottom(&sim.plant));
    } else {
        /* floating pin: some charge left from the previous channel, drifting */
        v_ntc2 = 0.5 * v_board / 11.0 + 0.9 + 0.6 * sin(sim.t / 3.0);
    }
    out[ADC_CH_NTC1] = adc(ntc1_volts());
    out[ADC_CH_ISENSE] = adc(v_i > 3.25 ? 3.25 : v_i);
    out[ADC_CH_VSENSE] = adc(v_board * VSENSE_DIV_DEN / VSENSE_DIV_NUM);
    out[ADC_CH_NTC2] = adc(v_ntc2);
}

void sim_period(void)
{
    hal_period_t p;
    uint16_t duty = sim.pin_af ? sim.duty_active : 0;
    uint16_t next;
    double t0 = sim.t;
    double top_sum = 0;
    int shorted, i;

    sim.p_top_min = 1e9;
    sim.p_top_max = -1e9;
    sim.p_energy_j = 0;
    sim.plant.h_extra_top = active(sim.t_load) ? sim.load_h : 0.0;

    for (i = 0; i < SIM_SUBSTEPS; i++) {
        double gate_frac, on_frac, r_h, r_tot, i_on, p_heat, top;
        int tick0 = i * TICKS_PER_SUB;

        sim.t = t0 + i * DT;
        shorted = active(sim.t_switch_short);
        gate_frac = (duty - tick0) / (double)TICKS_PER_SUB;
        gate_frac = gate_frac < 0 ? 0 : gate_frac > 1 ? 1 : gate_frac;
        on_frac = shorted ? 1.0 : gate_frac;

        r_h = plant_r_heater(&sim.plant) * (active(sim.t_heater_r) ? sim.heater_r_factor : 1.0);
        if (active(sim.t_heater_open)) {
            r_h = 1e9;
        }
        r_tot = r_h + sim.r_series;
        i_on = sim.v_src / (r_tot + sim.r_cable);
        p_heat = i_on * i_on * r_h;

        if (i == ON_SAMPLE_SUB) {
            int on = shorted || duty > ON_SAMPLE_TICK + SAMPLE_TICKS / 2;

            sample(p.on, on ? i_on * r_tot : sim.v_src, on ? i_on : 0.0);
        }
        if (i == OFF_SAMPLE_SUB) {
            int on = shorted || duty > OFF_SAMPLE_TICK + SAMPLE_TICKS / 2;

            sample(p.off, on ? i_on * r_tot : sim.v_src, on ? i_on : 0.0);
        }

        plant_step(&sim.plant, p_heat * on_frac + (active(sim.t_ext) ? sim.p_ext_w : 0.0), DT);
        source_step(i_on, on_frac * DT);

        top = plant_t_top(&sim.plant);
        top_sum += top;
        sim.p_top_min = fmin(sim.p_top_min, top);
        sim.p_top_max = fmax(sim.p_top_max, top);
        sim.p_energy_j += p_heat * on_frac * DT;
        if (on_frac > 0 && i_on > sim.i_max) {
            sim.i_max = i_on;
        }
        if (gate_frac > 0) {
            sim.t_last_gate_heat = sim.t + DT;
        }
        if (sim.t99 < 0 && top >= 99.0) {
            sim.t99 = sim.t + DT;
        }
    }
    sim.p_top_mean = top_sum / SIM_SUBSTEPS;
    sim.top_max = fmax(sim.top_max, sim.p_top_max);

    /* what the compare interrupt at OFF_SAMPLE_TICK does: latch the next duty */
    next = sim.duty_cmd;
    if (!sim.pin_af) {
        if (next != 0 && sim.duty_active == 0) {
            sim.pin_af = 1;
        } else {
            next = 0;
        }
    }
    p.duty = sim.dirty ? 0 : sim.duty_active;
    sim.dirty = !sim.pin_af;
    sim.duty_active = next;

    sim.t = t0 + PERIOD_S;
    app_step(&p);
}
