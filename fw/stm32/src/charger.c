#include "charger.h"
#include "est.h"

/* HUSB238 registers */
#define REG_PD_STATUS1      0x01
#define REG_SRC_PDO_5V      0x02
#define REG_SRC_PDO         0x08
#define REG_GO_COMMAND      0x09
#define PDO_DETECTED        0x80
#define PDO_CURRENT_MASK    0x0F
#define STATUS1_RESPONSE(v) (((v) >> 3) & 7u)
#define RESPONSE_SUCCESS    1
#define GO_REQUEST          0x01
#define GO_GET_SRC_CAP      0x04
#define SEL_5V              0x10

#define R20_MIN_X           (HEATER_R20_NOM_MOHM * (100u - HEATER_R20_ACCEPT_PCT) / 10u)
#define R20_MAX_X           (HEATER_R20_NOM_MOHM * (100u + HEATER_R20_ACCEPT_PCT) / 10u)

static const struct {
    uint16_t mv;
    uint8_t  reg;           /* SRC_PDO_xV register */
    uint8_t  sel;           /* SRC_PDO selection value */
} cand[CH_NV] = {
    { 20000, 0x07, 0xA0 },
    { 15000, 0x05, 0x80 },
    { 12000, 0x04, 0x30 },
    {  9000, 0x03, 0x20 },
};

/* current codes 0..15, in 50 mA */
static const uint8_t code_50ma[16] = {
    10, 14, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100
};

uint16_t charger_candidate_mv(int idx)
{
    return cand[idx].mv;
}

void charger_init(charger_t *c)
{
    *c = (charger_t){ .st = CH_WAIT, .max_mv = 0xFFFF };
}

void charger_restart(charger_t *c)
{
    c->st = CH_WAIT;
    c->timer = 0;
    c->tries = 0;
    c->sel_mv = 0;
    c->limit_ma = 0;
}

int charger_step_down(charger_t *c, uint32_t r_x)
{
    if (!c->pd_ok || c->sel_mv == 0) {
        return 0;
    }
    if (r_x != 0 && r_x < c->r20_x) {
        c->r20_x = r_x;
    }
    c->max_mv = (uint16_t)(c->sel_mv - 1);
    c->sel_mv = 0;
    c->limit_ma = 0;
    c->st = CH_PICK;
    return 1;
}

void charger_force_5v(void)
{
    hal_vset_low(1);
    if (hal_pd_write(REG_SRC_PDO, SEL_5V) == 0) {
        (void)hal_pd_write(REG_GO_COMMAND, GO_REQUEST);
    }
}

int charger_pick(const uint16_t offer_ma[CH_NV], uint32_t r20_x, uint16_t max_mv, int from)
{
    int i;

    if (r20_x == 0) {
        return -1;
    }
    for (i = from; i < CH_NV; i++) {
        /* cold current with margin, mA: V / R20 * margin */
        uint32_t need_ma = (uint32_t)cand[i].mv * (100u * PD_CURRENT_MARGIN_PCT) / r20_x;

        if (cand[i].mv <= max_mv && offer_ma[i] != 0 && offer_ma[i] >= need_ma) {
            return i;
        }
    }
    return -1;
}

/* 1: offers read; 0: the chip answers but lists nothing yet; -1: no answer */
static int read_offers(charger_t *c)
{
    uint8_t v;
    int i, any;

    if (hal_pd_read(REG_SRC_PDO_5V, &v) != 0) {
        return -1;
    }
    any = (v & PDO_DETECTED) != 0;
    for (i = 0; i < CH_NV; i++) {
        if (hal_pd_read(cand[i].reg, &v) != 0) {
            return -1;
        }
        c->offer_ma[i] = 0;
        if (v & PDO_DETECTED) {
            c->offer_ma[i] = (uint16_t)(code_50ma[v & PDO_CURRENT_MASK] * 50u);
            any = 1;
        }
    }
    return any;
}

static int at_voltage(int32_t vbus_mv, uint16_t target_mv)
{
    int32_t tol = target_mv * PD_VSENSE_TOL_PCT / 100;
    int32_t d = vbus_mv - target_mv;

    return d <= tol && d >= -tol;
}

uint16_t charger_step(charger_t *c, const sense_t *s)
{
    uint16_t pulse = 0;
    uint8_t v;
    int i;

    switch (c->st) {
    case CH_WAIT:
        if (++c->timer >= PD_BOOT_WAIT) {
            c->st = CH_READ;
        }
        break;

    case CH_READ:
        i = read_offers(c);
        if (i > 0) {
            c->pd_ok = 1;
            c->timer = 0;
            if ((c->offer_ma[0] | c->offer_ma[1] | c->offer_ma[2] | c->offer_ma[3]) == 0) {
                c->st = CH_NO_POWER;            /* 5 V only: do not even probe */
            } else {
                c->st = c->r20_x != 0 ? CH_PICK : CH_PROBE;
            }
        } else if (++c->tries < PD_READ_TRIES) {
            if (i == 0) {
                (void)hal_pd_write(REG_GO_COMMAND, GO_GET_SRC_CAP);
            }
            c->timer = PD_BOOT_WAIT - PD_RETRY_WAIT;
            c->st = CH_WAIT;
        } else {
            /* no PD information: take VBUS as it is */
            c->pd_ok = 0;
            if (s->vbus_mv >= VBUS_MIN_NO_PD_MV) {
                c->sel_mv = (uint16_t)s->vbus_mv;
                c->limit_ma = 0;
                c->st = CH_DONE;
            } else {
                c->st = CH_NO_POWER;
            }
        }
        break;

    case CH_PROBE:
        if (s->r_valid) {
            /* a wrong R20 would mean a wrong current forecast: accept only what a heater
             * of this board can be */
            c->r20_x = est_r20(s->r_x, s->t_ntc_mc);
            c->st = c->r20_x >= R20_MIN_X && c->r20_x <= R20_MAX_X ? CH_PICK : CH_PROBE_FAILED;
        } else if (c->timer >= PROBE_TIMEOUT) {
            c->st = CH_PROBE_FAILED;
        } else if (c->timer % PROBE_SPACING == 0) {
            pulse = MEAS_PULSE_DUTY;
        }
        c->timer++;
        break;

    case CH_PICK:
        i = charger_pick(c->offer_ma, c->r20_x, c->max_mv, 0);
        if (i < 0) {
            c->st = CH_NO_POWER;
        } else if (at_voltage(s->vbus_mv, cand[i].mv)) {
            c->sel_mv = cand[i].mv;             /* the contract is already there */
            c->limit_ma = c->offer_ma[i];
            c->st = CH_DONE;
        } else {
            c->idx = (uint8_t)i;
            c->timer = 0;
            c->st = CH_QUIET;
        }
        break;

    case CH_QUIET:
        if (++c->timer >= PD_QUIET_PERIODS) {
            c->timer = 0;
            c->stable = 0;
            if (hal_pd_write(REG_SRC_PDO, cand[c->idx].sel) == 0
                && hal_pd_write(REG_GO_COMMAND, GO_REQUEST) == 0) {
                c->st = CH_CONFIRM;
            } else {
                c->offer_ma[c->idx] = 0;
                c->st = CH_PICK;
            }
        }
        break;

    case CH_CONFIRM:
        c->stable = at_voltage(s->vbus_mv, cand[c->idx].mv) ? (uint8_t)(c->stable + 1) : 0;
        if (c->stable >= PD_STABLE_PERIODS && hal_pd_read(REG_PD_STATUS1, &v) == 0
            && STATUS1_RESPONSE(v) == RESPONSE_SUCCESS) {
            c->sel_mv = cand[c->idx].mv;
            c->limit_ma = c->offer_ma[c->idx];
            c->st = CH_DONE;
        } else if (++c->timer >= PD_CONFIRM_TIMEOUT) {
            c->offer_ma[c->idx] = 0;            /* failed: try the next lower one */
            c->st = CH_PICK;
        }
        break;

    default:                                    /* CH_DONE, CH_NO_POWER, CH_PROBE_FAILED */
        break;
    }
    return pulse;
}
