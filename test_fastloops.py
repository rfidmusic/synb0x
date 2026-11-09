"""The stock buffer loops replaced four at a time (fast_scale / fast_copy / fast_fill / fast_mixadd, CPU) against
stock 3.1.9, under Unicorn: the stock wrappers FUN_0805fd14 (scale in place), FUN_0805f5c0 (copy), FUN_0805f614 (fill)
and FUN_080617c0 (bus mix y += x) in both images, every length 0 .. 37 and some long ones, overlapping copies too.
Checked: the memory they write (and the bytes around it) bit-identical.
"""
import random
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_S0

from emu import Emu

MOD = "out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+cave/BLACKBOX.bin"
A, B = 0x24070000, 0x24072000
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


stock, mine = Emu("firmware/BLACKBOX-3.1.9.bin", "out/cave.elf"), Emu(MOD, "out/cave.elf")
rng = random.Random(9)
lengths = list(range(0, 38)) + [63, 64, 65, 255, 256, 257]
src = [rng.uniform(-2, 2) for _ in range(600)]
dst = [rng.uniform(-2, 2) for _ in range(600)]


def run(e, fn, regs, g=None):
    e.uc.mem_write(A, struct.pack("<600f", *src))
    e.uc.mem_write(B, struct.pack("<600f", *dst))
    if g is not None:
        e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", g))[0])
    e.call(fn, *regs)
    return bytes(e.uc.mem_read(A, 2400)) + bytes(e.uc.mem_read(B, 2400))


for name, fn, mk in (("scale in place (FUN_0805fd14)", 0x0805FD14, lambda n: ((A + 8, n), 0.37)),
                     ("copy (FUN_0805f5c0)", 0x0805F5C0, lambda n: ((A + 8, n, B + 4), None)),
                     ("fill (FUN_0805f614)", 0x0805F614, lambda n: ((B + 4, n), -0.5)),
                     ("bus mix (FUN_080617c0)", 0x080617C0, lambda n: ((A + 8, n, B + 4), None))):
    bad = [n for n in lengths if run(stock, fn, *mk(n)) != run(mine, fn, *mk(n))]
    check(f"{name}: bit-identical to stock for every length tried", not bad, bad)
# the copy's argument order, from its wrapper: check it on the stock code first, then the overlap cases
import itertools
bad = []
for n, (s_off, d_off) in itertools.product((1, 5, 9, 33, 64, 101), [(8, 8)] + [(64, 64 + 4 * k) for k in range(1, 14)] +
                                           [(64 + 4 * k, 64) for k in range(1, 14)]):
    regs = (A + s_off, n, A + d_off)
    if run(stock, 0x0805F5C0, regs) != run(mine, 0x0805F5C0, regs):
        bad.append((n, s_off, d_off))
check("copy with source and destination overlapping (either way, by 1 .. 13 values) and in place: bit-identical (3.1.v4: 8 at a time)", not bad, bad)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
