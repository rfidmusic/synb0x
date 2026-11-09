"""Sample cache page lookups past 256 s by an exact index (see src/cache.c). Needs `grain` + `clock` (the ITCM
table is cleared at boot by clock_config through grain_tab_init)."""
import os
import struct

from thumb import ROOT, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def bw(at, target):
    off = (target & ~1) - (at + 4)
    s = (off >> 24) & 1
    i1, i2 = (off >> 23) & 1, (off >> 22) & 1
    j1, j2 = (1 - i1) ^ s, (1 - i2) ^ s
    return struct.pack("<HH", 0xF000 | (s << 10) | ((off >> 12) & 0x3FF), 0x9000 | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7FF))


from thumb import bl

PATCHES = [
    # the loader's slot allocators: logged for the index
    (0x080720A6, bl(0x080720A6, 0x080713BC), bl(0x080720A6, sym["cache_slots_take"])),
] + [(a, bl(a, 0x08071D64), bl(a, sym["cache_slot_take"])) for a in
     (0x08071F10, 0x08071F32, 0x08071F54, 0x08071F76, 0x080721D8, 0x080723AA)] + [
    (0x08074AD6, bytes.fromhex("0bf58041"), bw(0x08074AD6, sym["cache_read_find"])),    # add.w r1, fp, #0x4000
    (0x080745E2, bytes.fromhex("4ff4b871"), bw(0x080745E2, sym["cache_ahead_find"])),   # mov.w r1, #0x170
]
