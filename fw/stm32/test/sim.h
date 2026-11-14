/* Host simulation of the board: thermal plant, heater, ADC front end, PWM pipeline and a
 * USB-PD charger behind a HUSB238 model. Implements src/hal.h. */
#ifndef SIM_H
#define SIM_H

#include <stdint.h>
#include "plant.h"
#include "../src/hal.h"

#define SIM_MAX_OFFERS  8
#define SIM_SUBSTEPS    100             /* plant steps per PWM period (0.4 ms) */

typedef struct {
    int mv, ma;
} sim_offer_t;

typedef struct {
    /* ---------------- configuration, set between sim_defaults() and sim_start() */
    double r20;                 /* heater resistance at 20 C */
    double t_start;             /* plate temperature at boot */
    double r_series;            /* shunt + switch, in series with the heater */
    double r_cable;             /* source + cable resistance */
    double isense_zero_v;       /* current amplifier output at zero current */
    double adc_noise_lsb;       /* rms, per conversion */
    int    n_offers;
    sim_offer_t offers[SIM_MAX_OFFERS];
    double pd_ready_s;          /* when the PD chip has its own contract and lists the offers */
    int    pd_absent;           /* no answer on I2C; VBUS is fixed_vbus */
    double fixed_vbus;
    int    reject_mv;           /* the source refuses requests for this voltage */
    int    ntc2_fitted;
    /* fault injection; times in s, negative = never */
    double t_ntc_open;
    double ntc_stuck_c;         /* NTC1 reads this temperature all the time (NAN: follows the plate) */
    double t_ntc_offset, ntc_offset_k;      /* NTC1 reads this much too high from then on */
    double t_switch_short;      /* current flows regardless of the gate */
    double t_load, load_h;      /* extra heat transfer on the top face, W/m2K */
    double t_heater_r, heater_r_factor;     /* heater resistance multiplied (partial short) */
    double t_heater_open;
    double t_src_drop, src_drop_s;          /* source falls back to 5 V for this long */
    double t_ext, p_ext_w;                  /* external heat into the top face (hot object) */

    /* ---------------- state */
    plant_t plant;
    double  t;                  /* s, start of the current period */
    uint32_t rng;
    /* PWM pipeline (mcu/board.c: TIM1 compare interrupt) */
    uint16_t duty_cmd, duty_active;
    int     pin_af, dirty;
    int     led, vset_low;
    /* source + PD chip */
    double  v_src, v_target;
    int     contract_mv, contract_ma;
    double  t_trans_end;        /* a voltage transition is under way until then */
    int     pd_listed, auto_done;
    uint8_t reg_sel, pd_response;
    int     req_mv;             /* pending request, 0 = none */
    double  t_req_apply;
    int     dropped;

    /* ---------------- records */
    double  top_max;            /* highest top copper temperature so far */
    double  t99;                /* first time the top copper reached 99 C, <0 = not yet */
    double  t_last_gate_heat;   /* last time the gate had the heater on */
    double  t_req_5v;           /* first demand for 5 V (I2C or VSET), <0 = none */
    double  oc_time;            /* total time the heater drew more than the contract current */
    double  i_max;              /* highest heater current */
    double  trans_heat_time;    /* heater current during a voltage transition */
    int     n_requests;         /* PD requests sent over I2C */
    int     hard_resets;
    int     led_edges;
    int     log_lines;
    char    last_log[128];
    /* per period, for the caller's statistics */
    double  p_top_min, p_top_max, p_top_mean, p_energy_j;
} sim_t;

extern sim_t sim;

void sim_defaults(void);
void sim_set_offers(const sim_offer_t *offers, int n);
void sim_start(void);           /* power-up: plant, source, app_init() */
void sim_period(void);          /* one PWM period of the world, then app_step() */

/* NTC circuit (B-parameter model): temperature -> divider ratio 0..1 */
double sim_ntc_ratio(double t_c);

#endif /* SIM_H */
