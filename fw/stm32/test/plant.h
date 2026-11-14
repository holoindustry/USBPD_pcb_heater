/* 1-D through-thickness thermal model of the heater plate (host tests only).
 * Port of class Plant / coeffs() in poc_fable/calc/thermal.py, with h_conv / h_rad / air
 * from calc/thermal_budget.py. */
#ifndef PLANT_H
#define PLANT_H

#define PLANT_N         8           /* FR-4 slices */
#define PLANT_T_AMB     25.0
#define PLANT_ALPHA_CU  0.00393     /* 1/K */
#define PLANT_DT        0.002       /* step of the Python reference (s) */

typedef struct {
    double r20;                     /* heater resistance at 20 C, ohm */
    double area;                    /* m2 */
    double dz, c_slice, c_top, c_bot;
    double w_top, tau_s;            /* sensor: mix of top copper / underside, lag (s) */
    double h_extra_top;             /* additional load on the top face, W/m2K */
    double leak;                    /* legs + links, W/m2K equivalent */
    double T[PLANT_N + 2];          /* top copper, FR-4 slices, underside plane */
    double t_sensor;
} plant_t;

void   plant_init(plant_t *pl, double r20, double t0);
void   plant_step(plant_t *pl, double p_watt, double dt);
double plant_r_heater(const plant_t *pl);
double plant_heat_capacity(const plant_t *pl);
void   plant_coeffs(double t_plate, double *h_top, double *h_bot);

static inline double plant_t_top(const plant_t *pl) { return pl->T[0]; }
static inline double plant_t_bottom(const plant_t *pl) { return pl->T[PLANT_N + 1]; }

#endif /* PLANT_H */
