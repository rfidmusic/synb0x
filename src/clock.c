/*
 * 480 MHz on rev V silicon (3.1.vh, TEST). Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock clocks (SystemClock_Config FUN_08043e84): HSE 6.144 MHz / 3 x 390 = 798.72 MHz VCO, P / 2 = 399.36 MHz core,
 * regulator VOS1 with overdrive off, 2 flash wait states, AXI / AHB 199.68 MHz; PLL1Q / 4 = 199.68 MHz is the FMC
 * (SDRAM) kernel clock, SDCLK / 2 = 99.84 MHz, refresh count 0x603. Audio (SAI), SD card, SPI, QSPI run from PLL2, the
 * screen from PLL3, USB from HSI48: none of them moves.
 * Rev V (DBGMCU IDCODE REV_ID 0x2003) is rated 480 MHz at VOS0 (overdrive on). On rev V only:
 *   before the PLL is set up: overdrive on (SYSCFG_PWRCR ODEN, wait for VOSRDY), PLL1 N 468 -> VCO 958.46 MHz (rev V's
 *   wide VCO goes to 960), core 479.23 MHz, PLL1 Q 5 -> FMC 191.69 MHz, SDCLK 95.85 MHz (4 % slower than stock: every
 *   SDRAM timing, set in clock cycles, gets longer);
 *   the clock switch: 4 flash wait states (ST's setting for AXI 240 MHz);
 *   the SDRAM refresh count scaled to the slower SDCLK (0x603 -> 1477: the same 15.6 us per row).
 * Any other revision (rev Y is rated 400 MHz) runs exactly as stock. HAL works out SystemCoreClock, the FreeRTOS tick
 * and the UART / I2C rates from the clocks it set, after this.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)
#define REG(a)   (*(volatile uint32_t *)(a))
#define DBGMCU_IDCODE REG(0x5c001000u)
#define RCC_PLL1DIVR  REG(0x58024430u)
#define RCC_APB4ENR   REG(0x580244f4u)
#define SYSCFG_PWRCR  REG(0x5800042cu)
#define PWR_D3CR      REG(0x58024818u)
#define VOSRDY        (1u << 13)
#define REV_V         0x2003u
#define FAST_N        468u
#define FAST_Q        5u

typedef int (*osc_fn)(void *osc);
typedef int (*clk_fn)(void *clk, uint32_t latency);
typedef void (*refresh_fn)(void *sdram, uint32_t count);
#define fw_osc_config  ((osc_fn)FN(0x0807d37c))       /* HAL_RCC_OscConfig */
#define fw_clk_config  ((clk_fn)FN(0x0807db5c))       /* HAL_RCC_ClockConfig */
#define fw_sdram_rate  ((refresh_fn)FN(0x08045dd8))   /* the SDRAM's refresh / start sequence */

/* the core runs at 479 MHz: PLL1 N is 468 */
int clock_480(void)
{
    return (RCC_PLL1DIVR & 0x1ffu) + 1u == FAST_N;
}

/* Replaces bl HAL_RCC_OscConfig @0x08043f20; osc: PLL1 N at +0x30, Q at +0x38 (stock 390, 4) */
int clock_osc(uint8_t *osc)
{
    if ((DBGMCU_IDCODE >> 16) == REV_V) {
        RCC_APB4ENR |= 2u;                          /* SYSCFG clock */
        (void)RCC_APB4ENR;
        SYSCFG_PWRCR |= 1u;                         /* overdrive: VOS1 -> VOS0 */
        while (!(PWR_D3CR & VOSRDY))
            ;
        *(uint32_t *)(osc + 0x30) = FAST_N;
        *(uint32_t *)(osc + 0x38) = FAST_Q;
    }
    return fw_osc_config(osc);
}

void grain_tab_init(void);                          /* grain.c */

/* Replaces bl HAL_RCC_ClockConfig(clk, FLASH_LATENCY_2) @0x08043f52; also the boot point for the grain window copy
   (3.1.v4, grain.c: once per boot, before the RTOS) */
int clock_config(void *clk, uint32_t latency)
{
    int r = fw_clk_config(clk, clock_480() ? 4u : latency);
    grain_tab_init();
    return r;
}

/* Replaces bl FUN_08045dd8(sdram, 0x603) @0x08045ec0 */
void clock_sdram(void *sdram, uint32_t count)
{
    fw_sdram_rate(sdram, clock_480() ? 1477u : count);
}
