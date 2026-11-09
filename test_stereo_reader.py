"""3.1.v1's shared reader (read_normal_l / _r, and read_hq_l / _r once present) against stock 3.1.9, under Unicorn.

Real firmware runs for: the sample reader FUN_08055f0c in both images (stock: two kernel calls for a stereo sample;
this build: one stereo loop), the stock kernels, the reverse helper. Stubbed the same in both: the sample object's
calls (stereo or mono, length, the fetch into the scratch buffer, the prefetch hint) and the buffer accessors.
Checked: for random rates (forward and reverse, below and above 1), fractions, positions, block lengths 1 .. 256 and
offsets, Normal and HighQ, stereo and mono: the left and right output bit-identical to stock.
"""
import math
import random
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_S0, UC_ARM_REG_S1

from emu import STACK, Emu

MOD = "out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+cave/BLACKBOX.bin"
PAD, SAMPLE, SCR, OUT = 0x24070000, 0x24071000, 0x24072000, 0x24073000
SL, SR, OL, OR_ = 0x24074000, 0x24076000, 0x24078000, 0x2407A000
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def f32(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def make(image):
    e = Emu(image, "out/cave.elf")
    st = {"stereo": 1}
    e.stub(0x0804D8E8, value=2048)                       # scratch frames
    e.stub(0x080636F0, value=1 << 22)                    # sample length
    e.stub(0x08063790, lambda: e.uc.reg_write(0, 0) if False else None)
    e.stubs.pop(0x08063790, None)
    e.stub(0x08063790, lambda: None, value=None)

    def stereo():
        e.ret(st["stereo"])
    e.stubs[0x08063790] = stereo

    def ptrs2(a, b):
        def run():
            e.w32(e.arg(1), a)
            e.w32(e.arg(2), b)
            e.ret()
        return run
    e.stubs[0x0804DA0C] = ptrs2(SL, SR)                  # the scratch buffer's channels
    e.stubs[0x0804D9C0] = ptrs2(OL, OR_)                 # the output buffer's channels
    e.stub(0x0804D934, value=SL)                         # (mono) scratch / output
    sig = lambda p: [0.4 * math.sin(0.0137 * (p + i)) + 0.3 * math.sin(0.191 * (p + i) + 1.0) for i in range(2048)]

    def fetch2():                                        # FUN_08063608(sample, left, right, count, position)
        l, r, n = e.arg(1), e.arg(2), e.arg(3)
        p = e.r32(e.uc.reg_read(__import__("unicorn").arm_const.UC_ARM_REG_SP))
        n = max(0, min(n, 2048))
        x = sig(p)
        e.uc.mem_write(l, struct.pack(f"<{n}f", *x[:n]))
        e.uc.mem_write(r, struct.pack(f"<{n}f", *[-0.7 * v + 0.01 for v in x[:n]]))
        e.ret(1)
    e.stubs[0x08063608] = fetch2

    def fetch1():                                        # FUN_08063634(sample, dst, count, position, 0)
        d, n, p = e.arg(1), e.arg(2), e.arg(3)
        n = max(0, min(n, 2048))
        e.uc.mem_write(d, struct.pack(f"<{n}f", *sig(p)[:n]))
        e.ret(1)
    e.stubs[0x08063634] = fetch1
    e.stub(0x0806375C)                                   # reverse prefetch hint
    return e, st


S, Ms = make("firmware/BLACKBOX-3.1.9.bin"), make(MOD)
rng = random.Random(5)
results = {}
for trial in range(240):
    hq = trial % 2
    stereo = 1 if trial % 6 else 0
    rate = rng.choice((rng.uniform(0.25, 0.99), rng.uniform(1.01, 3.9), -rng.uniform(0.3, 2.5), 0.5, 2.0))
    frac, pos, n, off = rng.random(), rng.randrange(8, 100000), rng.choice((1, 2, 3, 7, 64, 128, 256)), rng.randrange(0, 4)
    outs = []
    for e, st in (S, Ms):
        st["stereo"] = stereo
        e.uc.mem_write(PAD + 0x578, struct.pack("<I", hq))
        e.uc.mem_write(OL, bytes(4 * 300))
        e.uc.mem_write(OR_, bytes(4 * 300))
        e.uc.mem_write(SL, bytes(4 * 600))
        e.uc.reg_write(UC_ARM_REG_S0, f32(frac))
        e.uc.reg_write(UC_ARM_REG_S1, f32(rate))
        e.uc.mem_write(STACK, struct.pack("<IIII", n, off, SCR, OUT))
        e.call(0x08055F0C, PAD, SAMPLE, pos, 0)
        outs.append(bytes(e.uc.mem_read(OL, 4 * 300)) + bytes(e.uc.mem_read(OR_, 4 * 300)) + bytes(e.uc.mem_read(SL, 4 * 300)))
    key = ("HighQ" if hq else "Normal", "stereo" if stereo else "mono")
    good, total = results.get(key, (0, 0))
    results[key] = (good + (outs[0] == outs[1]), total + 1)
for (kernel, ch), (good, total) in sorted(results.items()):
    check(f"{kernel}, {ch}: {good} of {total} random reads bit-identical to stock (rates forward / reverse, any length)",
          good == total, (good, total))
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
