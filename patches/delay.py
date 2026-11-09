"""Delay-line reader without per-sample divisions (see src/delay.c): every call of FUN_0806ab70 goes to delay_read."""
import os

from thumb import ROOT, bl, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))
STOCK = 0x0806AB70

PATCHES = [(at, bl(at, STOCK), bl(at, sym["delay_read"])) for at in (
    0x08054B98, 0x08054BA6, 0x08054C86, 0x08054D2A,   # the Delay effect (FUN_080548c8)
    0x0806B730, 0x0806B73A, 0x0806B8B8, 0x0806B8C2,   # FUN_0806b6b4 / FUN_0806b87c
)]
