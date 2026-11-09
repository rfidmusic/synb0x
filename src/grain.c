/*
 * The grain window in the core's ITCM. The stock grain renderer (FUN_08057db8, its mix loop @0x08057ee2) looks up each
 * grain's window per sample in an 8192-entry float table in flash (0x080d26ac, 32 KB: twice the data cache); a short
 * grain steps through it many entries at a time, so almost every sample is a cache miss. The ITCM (0x00000000, 64 KB,
 * zero wait states, never cached) is unused by the firmware past its first 1 KB: the table is copied to 0x8000 at
 * boot and the renderer's literal (0x08057fd8) points there. The same values: bit for bit the same sound.
 */
#include <stdint.h>

#define WIN_FLASH ((const uint32_t *)0x080d26acu)
#define WIN_ITCM  ((uint32_t *)0x00008000u)
#define WIN_N     8192

void cache_hint_init(void);                          /* cache.c (3.1.v6): its ITCM table, cleared */

/* At boot (clock.c's clock_config, before the RTOS starts). */
void grain_tab_init(void)
{
    cache_hint_init();
    const volatile uint32_t *s = WIN_FLASH;
    volatile uint32_t *d = WIN_ITCM;
    for (int i = 0; i < WIN_N; i++)
        d[i] = s[i];
    __asm volatile("dsb\n\tisb" ::: "memory");
}
