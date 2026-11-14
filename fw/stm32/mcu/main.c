/*
 * USB-C PCB hot plate, STM32C011F4P6. All behaviour is in src/ (shared with the host
 * tests); this file only connects it to the hardware.
 */
#include "board.h"
#include "src/app.h"

int main(void)
{
    static const char hex[] = "0123456789abcdef";
    char banner[] = "# pcb heater, reset cause 0x00\r\n";
    hal_period_t p;
    uint32_t cause;

    board_init();
    cause = board_reset_cause();
    banner[sizeof banner - 5] = hex[(cause >> 4) & 15u];
    banner[sizeof banner - 4] = hex[cause & 15u];
    hal_log(banner, sizeof banner - 1);

    app_init();
    board_start();

    for (;;) {
        if (board_get_period(&p)) {
            app_step(&p);
            /* fed only from here: a stalled timer, ADC or main loop ends in a reset */
            board_watchdog_kick();
        }
    }
}
