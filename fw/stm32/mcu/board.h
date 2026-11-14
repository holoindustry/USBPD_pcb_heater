/* MCU layer: STM32C011F4P6 peripherals, register level. Implements src/hal.h. */
#ifndef BOARD_H
#define BOARD_H

#include <stdint.h>
#include "src/hal.h"

/* Clock, GPIO, watchdog, SysTick, UART, I2C pins, ADC. The gate is held low. */
void board_init(void);

/* Start the PWM timer; from now on a period record arrives every 40 ms. */
void board_start(void);

/* Copies the latest period record to *p and returns 1 if there is a new one. */
int board_get_period(hal_period_t *p);

void board_watchdog_kick(void);

/* Reset cause bits (RCC_CSR2 >> 24) as found at start-up. */
uint32_t board_reset_cause(void);

uint32_t board_millis(void);
void board_delay_ms(uint32_t ms);

#endif /* BOARD_H */
