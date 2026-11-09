"""The grain window in ITCM (see src/grain.c): the grain renderer's literal for the window table -> its ITCM copy.
Needs `clock` (its clock_config makes the copy at boot)."""
from thumb import word

PATCHES = [
    (0x08057FD8, word(0x080D26AC), word(0x00008000)),   # FUN_08057db8's literal (ldr r5, [pc, #0x100] @0x08057ed6)
]
