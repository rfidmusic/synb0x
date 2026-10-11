"""Pad edit screen: Filt tab after Main with Filter, Res, Type and the filter envelope; Filter and Res leave Main
(see src/filt_tab.c). Apply together with `fenv` and `cave`."""
import os
import struct

from thumb import ROOT, bl, symbols, word

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))


def hook(at, stock, name):
    return (at, bl(at, stock), bl(at, sym[name]))


def b16(at, target, cond=None):
    """16-bit Thumb branch: conditional (T1, cond 0 = eq, 1 = ne) or unconditional (T2)."""
    off = (target - (at + 4)) // 2
    if cond is None:
        assert -1024 <= off < 1024
        return struct.pack("<H", 0xE000 | (off & 0x7FF))
    assert -128 <= off < 128
    return struct.pack("<H", 0xD000 | cond << 8 | (off & 0xFF))


def bw(at, target):
    """32-bit Thumb B.W (T4)."""
    off = target - (at + 4)
    assert -(1 << 24) <= off < (1 << 24) and off % 2 == 0
    s = (off >> 24) & 1
    i1, i2 = (off >> 23) & 1, (off >> 22) & 1
    j1, j2 = (1 - i1) ^ s, (1 - i2) ^ s
    return struct.pack("<HH", 0xF000 | (s << 10) | ((off >> 12) & 0x3FF), 0x9000 | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7FF))


EQ, NE = 0, 1
NOP = bytes.fromhex("00bf")
H = bytes.fromhex


def grid_check(at, old, reg, list_target):
    """cbz rN,grid; subs rN,#2; cmp rN,#1; bhi list  ->  bl filt_is_list_rN; beq list; nop"""
    new = bl(at, sym[f"filt_is_list_r{reg}"]) + b16(at + 4, list_target, EQ) + NOP
    return (at, H(old), new)


MAIN_OLD = struct.pack("<8H", 0x04, 0xC8, 0x5C, 0x11, 0x3C, 0x3E, 0x3F, 0x40)
# Level, Pitch, Pan, Saturation / A D S R (Pan and Saturation also stay on Conf). No blanks: after every value change
# the grid (FUN_080a87b6) jumps from the bottom row back to the top when slots 2 and 3 hold no knob (and from the top
# row to the bottom when slots 0 and 1 hold none), which made the amp envelope row unreachable with Level, Pitch, -, -.
MAIN_NEW = struct.pack("<8H", 0x04, 0x5C, 0x62, 0xDB, 0x3C, 0x3E, 0x3F, 0x40)
MAIN_TABLES = (0x080EFC18, 0x080EFAB0, 0x080EF948, 0x080EF7E0, 0x080EF510,      # Sample, Multisample, Clip, Slicer, Granular
               0x080EF3A8, 0x080EF240, 0x080EF0D8, 0x080EEF70)                  # the same four modes, empty-pad record

PATCHES = [
    # tab bar construction: the stock per-bar loop body -> filt_tabs(bar = r9, slot4 = [sp, #16], index = fp), then the
    # stock end of the bar loop at 0x080b9122
    (0x080B919E, H("094b03f10a07084b03f11406049c05258de7"),
     H("4846" "0499" "5a46") + bl(0x080B91A4, sym["filt_tabs"]) + b16(0x080B91A8, 0x080B9122) + NOP * 3),
    # tab button press: id - 0x12f <= 4 -> <= 5
    (0x080B9496, H("042b"), H("052b")),
    # page lists: tab 5 of a pad = the Filt page (pad screen, and the three other callers that pass a tab)
    hook(0x080B8956, 0x08098D40, "filt_page"),
    hook(0x080A7314, 0x08098D40, "filt_page"),
    hook(0x080AB94A, 0x08098D40, "filt_page"),
    hook(0x080C523A, 0x08098D40, "filt_page"),
    # grid or list: Filt shows the knob grid like Main
    grid_check(0x080B8878, "12b1023a012a05d8", 2, 0x080B888C),                 # FUN_080b886c: refresh
    grid_check(0x080B91EE, "13b1023b012b33d8", 3, 0x080B925E),                 # FUN_080b91cc: encoder turn
    grid_check(0x080B933C, "12b1023a012a54d8", 2, 0x080B93EE),                 # FUN_080b929a
    # FUN_080b929a, second test (grid path): cmp r2,#0; beq g; subs; cmp; bls g; b l -> bl; bne g; b l; nop; nop
    (0x080B9356, H("002a45d0023a012a42d942e0"),
     bl(0x080B9356, sym["filt_is_list_r2"]) + b16(0x080B935A, 0x080B93E6, NE) + b16(0x080B935C, 0x080B93E8) + NOP * 2),
    # FUN_080b8898 (visibility): cmp r2,#2; beq g; cmp r2,#3; beq g -> bl; bne g; nop  (tab 0 takes the same path)
    (0x080B88A6, H("022a1fd0032a20d0"),
     bl(0x080B88A6, sym["filt_is_list_r2"]) + b16(0x080B88AA, 0x080B88EA, NE) + NOP),
    # re-entry clamp: the whole function -> filt_clamp (same arguments, returns to the caller)
    (0x080991A8, H("938803f4"), bw(0x080991A8, sym["filt_clamp"])),
    # the Filter knob's number reads 0..100 % (display only; the value stays -1000..1000)
    hook(0x080A957E, 0x080A9120, "filt_knob_text"),
    hook(0x080A965E, 0x080A9120, "filt_knob_text"),
    hook(0x080A9704, 0x080A9120, "filt_knob_text"),
    # modulation targets: the stock 28-id list (0x080f12bc) -> 29 ids with Morph, at both literals and both counts
    (0x080B8924, word(0x080F12BC), word(sym["filt_mod_targets"])),
    (0x080B8BF8, word(0x080F12BC), word(sym["filt_mod_targets"])),
    (0x080B88D6, bytes.fromhex("03f13801"), bytes.fromhex("03f13a01")),   # add.w r1, r3, #56 -> #58 (list end)
    (0x080B896A, bytes.fromhex("1c22"), bytes.fromhex("1d22")),           # movs r2, #28 -> #29 (list rows)
    (0x080B8980, bytes.fromhex("1c22"), bytes.fromhex("1d22")),           # movs r2, #28 -> #29 (knob grid)
    # Main tab: Filter and Res move to Filt; Level, Pitch, Pan, Saturation on top, the amp envelope stays on the bottom row
    *[(a, MAIN_OLD, MAIN_NEW) for a in MAIN_TABLES],
]
