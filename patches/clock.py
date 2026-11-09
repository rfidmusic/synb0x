"""480 MHz on rev V silicon (see src/clock.c). TEST. Apply together with `cave`."""
import os

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


PATCHES = [
    hook(0x08043F20, 0x0807D37C, "clock_osc"),        # HAL_RCC_OscConfig: overdrive, PLL1 N 468, Q 5 (rev V)
    hook(0x08043F52, 0x0807DB5C, "clock_config"),     # HAL_RCC_ClockConfig: 4 flash wait states at 480 MHz
    hook(0x08045EC0, 0x08045DD8, "clock_sdram"),      # SDRAM refresh count for the slower SDCLK
]
