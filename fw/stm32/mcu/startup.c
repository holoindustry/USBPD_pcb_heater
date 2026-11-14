/*
 * Vector table and reset code for STM32C011 (Cortex-M0+).
 */
#include <stdint.h>
#include "stm32c0xx.h"

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;

int main(void);
void Reset_Handler(void);
void Default_Handler(void);

void SysTick_Handler(void);
void TIM1_CC_IRQHandler(void);

/* Anything unexpected (hard fault, stray interrupt): gate low, then wait for the
 * watchdog to restart the board. */
void Default_Handler(void)
{
    __disable_irq();
    GPIOA->BRR = 1u << 8;
    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE8) | GPIO_MODER_MODE8_0;
    for (;;) {
    }
}

void Reset_Handler(void)
{
    uint32_t *src = &_sidata, *dst = &_sdata;

    while (dst < &_edata) {
        *dst++ = *src++;
    }
    for (dst = &_sbss; dst < &_ebss; dst++) {
        *dst = 0;
    }
    main();
    Default_Handler();
}

#define D   Default_Handler

__attribute__((section(".isr_vector"), used))
static void (*const vectors[16 + 32])(void) = {
    (void (*)(void))&_estack,
    Reset_Handler,
    D,                              /* NMI */
    D,                              /* HardFault */
    0, 0, 0, 0, 0, 0, 0,
    D,                              /* SVCall */
    0, 0,
    D,                              /* PendSV */
    SysTick_Handler,
    /* external interrupts 0..31 */
    D, D, D, D, D, D, D, D,         /* 0 WWDG .. 7 EXTI4_15 */
    D, D, D, D, D, D,               /* 8 .. 13 TIM1_BRK_UP_TRG_COM */
    TIM1_CC_IRQHandler,             /* 14 */
    D,
    D, D, D, D, D, D, D, D,         /* 16 TIM3 .. 23 I2C1 */
    D, D, D, D, D, D, D, D,         /* 24 .. 31 */
};

_Static_assert(TIM1_CC_IRQn == 14, "vector table position of TIM1_CC");
