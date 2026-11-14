#include "plant.h"
#include <math.h>

/* geometry (gen/geom.py) and material data (calc/thermal.py) */
#define HALF_MM     35.0            /* heater zone is 2 * HALF square */
#define T_PCB_MM    1.6
#define CU_UM       35.0
#define LEG_H_MM    12.0            /* clearance under the board */
#define K_FR4_Z     0.30            /* W/mK */
#define EPS_TOP     0.90            /* solder mask */
#define EPS_BOT     0.15            /* bare HASL */
#define RHO_C_FR4   (1850.0 * 1100.0)
#define RHO_C_CU    (8960.0 * 385.0)
#define G_LEG       1.3e-3          /* W/K per FR-4 leg */
#define G_LINK      1.7e-3          /* W/K per link */
#define SIGMA       5.670e-8
#define GRAV        9.81

/* rough air properties vs temperature (C): k [W/mK], nu [m2/s]; Pr = 0.70 */
static void air(double t_c, double *k, double *nu)
{
    double t = t_c + 273.15;
    double mu = 1.716e-5 * pow(t / 273.15, 1.5) * (273.15 + 110.4) / (t + 110.4);
    double rho = 101325.0 / (287.05 * t);

    *k = 0.0241 * pow(t / 273.15, 0.81);
    *nu = mu / rho;
}

static double h_conv(double t_s, double l_char, int facing_up)
{
    double tf = (t_s + PLANT_T_AMB) / 2;
    double k, nu, beta, ra, nu_n;

    air(tf, &k, &nu);
    beta = 1 / (tf + 273.15);
    ra = GRAV * beta * (t_s - PLANT_T_AMB) * l_char * l_char * l_char / (nu * nu) * 0.70;
    if (facing_up) {
        nu_n = ra < 1e7 ? 0.54 * pow(ra, 0.25) : 0.15 * pow(ra, 1.0 / 3.0);
    } else {
        nu_n = 0.27 * pow(ra, 0.25);
    }
    return nu_n * k / l_char;
}

static double h_rad(double t_s, double eps)
{
    double ts = t_s + 273.15, ta = PLANT_T_AMB + 273.15;

    return eps * SIGMA * (ts * ts * ts * ts - ta * ta * ta * ta) / (t_s - PLANT_T_AMB);
}

/* surface coefficients W/m2K: top and underside */
void plant_coeffs(double t_plate, double *h_top, double *h_bot)
{
    double lc = (2 * HALF_MM / 1000) / 4;       /* area / perimeter of the square plate */
    double k_air, nu, hc;

    *h_top = h_conv(t_plate, lc, 1) + h_rad(t_plate, EPS_TOP);
    air((t_plate + PLANT_T_AMB) / 2, &k_air, &nu);
    hc = h_conv(t_plate, lc, 0);
    *h_bot = fmax(k_air / (LEG_H_MM / 1000), hc) + h_rad(t_plate, EPS_BOT);
}

void plant_init(plant_t *pl, double r20, double t0)
{
    int i;

    pl->r20 = r20;
    pl->area = (2 * HALF_MM / 1000) * (2 * HALF_MM / 1000);
    pl->dz = T_PCB_MM * 1e-3 / PLANT_N;
    pl->c_slice = RHO_C_FR4 * pl->dz;
    pl->c_top = RHO_C_CU * CU_UM * 1e-6 * 0.62 + 1300.0 * 1400.0 * 25e-6;
    pl->c_bot = RHO_C_CU * CU_UM * 1e-6;
    pl->w_top = 0.7;
    pl->tau_s = 0.8;
    pl->h_extra_top = 0.0;
    pl->leak = (4 * G_LEG + 2 * G_LINK) / pl->area;
    for (i = 0; i < PLANT_N + 2; i++) {
        pl->T[i] = t0;
    }
    pl->t_sensor = t0;
}

double plant_r_heater(const plant_t *pl)
{
    return pl->r20 * (1 + PLANT_ALPHA_CU * (pl->T[0] - 20.0));
}

double plant_heat_capacity(const plant_t *pl)
{
    return pl->area * (pl->c_top + PLANT_N * pl->c_slice + pl->c_bot);
}

void plant_step(plant_t *pl, double p_watt, double dt)
{
    double *T = pl->T;
    double q[PLANT_N + 2];
    double h_top, h_bot, g, mix;
    int n = PLANT_N, i;

    plant_coeffs(fmax(T[0], PLANT_T_AMB + 1.0), &h_top, &h_bot);
    g = K_FR4_Z / pl->dz;
    q[0] = p_watt / pl->area - (h_top + pl->h_extra_top) * (T[0] - PLANT_T_AMB) - 2 * g * (T[0] - T[1]);
    q[1] = 2 * g * (T[0] - T[1]) - g * (T[1] - T[2]);
    for (i = 2; i < n; i++) {
        q[i] = g * (T[i - 1] - T[i]) - g * (T[i] - T[i + 1]);
    }
    q[n] = g * (T[n - 1] - T[n]) - 2 * g * (T[n] - T[n + 1]);
    q[n + 1] = 2 * g * (T[n] - T[n + 1]) - (h_bot + pl->leak) * (T[n + 1] - PLANT_T_AMB);
    T[0] += q[0] / pl->c_top * dt;
    for (i = 1; i <= n; i++) {
        T[i] += q[i] / pl->c_slice * dt;
    }
    T[n + 1] += q[n + 1] / pl->c_bot * dt;
    mix = pl->w_top * T[0] + (1 - pl->w_top) * T[n + 1];
    pl->t_sensor += (mix - pl->t_sensor) / pl->tau_s * dt;
}
