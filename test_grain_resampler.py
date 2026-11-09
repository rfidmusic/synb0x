"""3.1.v1's stereo grain / clip resampler (3.1.v4: and the grain window in ITCM) (resamp_grain_l / resamp_clip_l / resamp_r) against stock 3.1.9, Unicorn.

Real firmware runs for, in both images: the grain renderer 0x08057db8 (with its grain respawn FUN_08057ab0 and the
C library's rand()), the clip / slicer resampling step FUN_080662e4, the buffer accessors the grain renderer uses.
Stubbed the same in both: the sample cache reads (the grain renderer's: left and right different signals; the clip
step's: the sample object's stereo flag, length, fetch, scratch size, its buffers' channel pointers).
Checked: for random rates (below and above 1, not 1: rate 1 is stock's copy path), Grain Size, Scatter, Pan Rnd, grain
counts, block lengths, starting fractions and positions near the sample's end (the early stop): both output channels,
the grains' state (position, fraction) and the clip step's position / fraction bit-identical to stock.
"""
import math
import random
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_SP

from emu import STACK, Emu

MOD = "out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+clock+delay+grain+cache+cave/BLACKBOX.bin"
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


GP, GPOS, GV, GS, GFS, GVT = 0x30110000, 0x30111000, 0x30112000, 0x30113000, 0x30113100, 0x30113200
GG = 0x30114000
GBA, GBB, GBO = 0x30115000, 0x30115100, 0x30115200
GAL, GAR, GBL, GBR, GOL, GOR = 0x30120000, 0x30121000, 0x30122000, 0x30123000, 0x30124000, 0x30125000
GSRC = 0x30130000
STUB_READ, STUB_LEN, STUB_RATE = 0x30100000, 0x30100010, 0x30100020
SRC_LEN = 48000 * 2
SIG_L = [0.3 * math.sin(i * 0.031) + 0.1 * math.sin(i * 0.4) for i in range(SRC_LEN)]
SIG_R = [0.25 * math.cos(i * 0.017) - 0.05 * math.sin(i * 0.73) for i in range(SRC_LEN)]
# the clip step's buffers
CIN, COUT, CS, CL, CR, OL, OR_, CPOS, CFR, CRES = (0x30140000, 0x30140100, 0x30140200, 0x30150000, 0x30154000,
                                                    0x30158000, 0x3015C000, 0x30140300, 0x30140304, 0x30140308)


def make(image):
    e = Emu(image, "out/cave.elf")
    e.uc.mem_map(0x30100000, 0x100000)
    if image == MOD:                                  # 3.1.v4: the grain window in ITCM, copied at boot
        e.uc.mem_map(0x00000000, 0x10000)
        e.call("grain_tab_init")
    e.uc.mem_write(GSRC, struct.pack(f"<{SRC_LEN}f", *SIG_L) + struct.pack(f"<{SRC_LEN}f", *SIG_R))

    def cache_read():                                 # (stream, r1, pos lo, pos hi, [sp] h, [sp+4] L, [sp+8] R, n)
        sp = e.uc.reg_read(UC_ARM_REG_SP)
        pos = e.arg(2) % (SRC_LEN - 4096)
        dl, dr, n = e.r32(sp + 4) & 0xFFFFFFFF, e.r32(sp + 8) & 0xFFFFFFFF, max(e.r32(sp + 12), 0)
        for d, base in ((dl, GSRC), (dr, GSRC + 4 * SRC_LEN)):
            if d:
                e.uc.mem_write(d, bytes(e.uc.mem_read(base + 4 * pos, 4 * n)))
        e.ret(1)
    e.stubs[STUB_READ] = cache_read
    e.stub(STUB_LEN, lambda: None, value=SRC_LEN)
    e.stub(STUB_RATE, lambda: None, value=48000)
    e.w32(GS + 0x20, GFS)
    e.w32(GS + 0x24, 0)
    e.w32(GFS, GVT)
    for off, a in ((8, STUB_READ), (0x14, STUB_LEN), (0x18, STUB_RATE)):
        e.w32(GVT + off, a | 1)
    return e


def gbuf(e, at, frames, l, r):
    e.uc.mem_write(at, struct.pack("<IIIIBB", frames, frames, l, r, 0, 1))


def granular(e, seed):
    """a granular voice's grains on the real grain renderer: the output and grain state per block"""
    rng = random.Random(seed)
    e.uc.mem_write(GP, bytes(0x600))
    e.uc.mem_write(GV, bytes(0x600))
    e.uc.mem_write(GG, bytes(0x40 * 8))
    count = rng.choice((1, 3, 8))
    for off, v in ((0x58C, count), (0x590, rng.randrange(300, 9600)), (0x594, rng.choice((0, 480, 2400, 9600))),
                   (0x598, 0)):
        e.w32(GP + off, v)
    e.uc.mem_write(GP + 0x59C, struct.pack("<f", rng.choice((0.0, 0.5, 1.0))))
    e.w32(GV + 0xC, GS)
    e.w32(GV + 0x10, rng.randrange(1000, SRC_LEN // 2))
    e.uc.mem_write(GV + 0x140, struct.pack("<f", rng.choice((rng.uniform(0.25, 0.99), rng.uniform(1.01, 3.0), 1.0))))
    e.w32(GPOS, e.r32(GV + 0x10))
    e.w32(GPOS + 4, 0)
    for g in range(8):
        e.uc.mem_write(GG + 0x40 * g + 2, struct.pack("<H", g))
        e.uc.mem_write(STACK, struct.pack("<II", 0, GG + 0x40 * g))
        e.call(0x08057AB0, GP, GPOS, GV, 0)
    gbuf(e, GBA, 1024, GAL, GAR)
    gbuf(e, GBB, 1024, GBL, GBR)
    res = []
    for b in range(12):
        frames = rng.choice((256, 256, 64, 17))
        gbuf(e, GBO, frames, GOL, GOR)
        e.uc.mem_write(GOL, bytes(4 * 256))
        e.uc.mem_write(GOR, bytes(4 * 256))
        for g in range(8):
            e.uc.mem_write(STACK, struct.pack("<III", GBA, GBB, GBO))
            e.call(0x08057DB8, GP, GPOS, GV, GG + 0x40 * g)
        res.append(bytes(e.uc.mem_read(GOL, 4 * 256)) + bytes(e.uc.mem_read(GOR, 4 * 256))
                   + bytes(e.uc.mem_read(GG, 0x40 * 8)))
        e.w32(GPOS, (e.r32(GPOS) + frames) & 0xFFFFFFFF)
    return res


def clip_setup(e):
    st = {"len": 1 << 20}
    e.stub(0x080636F0, lambda: None, value=None)
    e.stubs[0x080636F0] = lambda: e.ret(st["len"])
    e.stubs[0x0804D8E8] = lambda: e.ret(4096)         # scratch frames
    e.stubs[0x08063790] = lambda: e.ret(1)            # stereo

    def ptrs():
        a, b = (CL, CR) if e.arg(0) == CIN else (OL, OR_)
        e.w32(e.arg(1), a)
        e.w32(e.arg(2), b)
        e.ret()
    e.stubs[0x0804DA0C] = ptrs

    def fetch():                                       # FUN_08063608(sample, left, right, count, position)
        l, r, n = e.arg(1), e.arg(2), max(0, min(e.arg(3), 4096))
        p = e.r32(e.uc.reg_read(UC_ARM_REG_SP)) % (SRC_LEN - 4096)
        e.uc.mem_write(l, bytes(e.uc.mem_read(GSRC + 4 * p, 4 * n)))
        e.uc.mem_write(r, bytes(e.uc.mem_read(GSRC + 4 * SRC_LEN + 4 * p, 4 * n)))
        e.ret(1)
    e.stubs[0x08063608] = fetch
    return st


def f32(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def clip(e, st, rate, frames, frac, pos, length):
    """FUN_080662e4(s0 rate, r0 voice, r1, r2 position, r3, [sp] frames, &pos, &frac, in, out, &result)"""
    from unicorn.arm_const import UC_ARM_REG_S0
    st["len"] = length
    e.w32(CS + 0x24, 0x30140400)
    e.uc.mem_write(OL, bytes(4 * 4096))
    e.uc.mem_write(OR_, bytes(4 * 4096))
    e.w32(CPOS, 12345)
    e.w32(CFR, f32(frac))
    e.uc.mem_write(STACK, struct.pack("<IIIIII", frames, CPOS, CFR, CIN, COUT, CRES))
    e.uc.reg_write(UC_ARM_REG_S0, f32(rate))
    r = e.call(0x080662E4, CS, 0, pos, 0)
    return (r, bytes(e.uc.mem_read(OL, 4 * 4096)) + bytes(e.uc.mem_read(OR_, 4 * 4096))
            + bytes(e.uc.mem_read(CPOS, 8)))


APP_PADS, ENTRIES = 0x24020088 + 0x1840, 0x24070000


def fidelity(e, v):
    """the granular pad's (row 0, col 0: the test pad's id) Fidelity setting (id 0xf1) in its settings store"""
    e.w32(APP_PADS + 4, ENTRIES)
    e.uc.mem_write(APP_PADS + 10, struct.pack("<H", 1))
    e.uc.mem_write(ENTRIES, struct.pack("<HHi", 0xF1, 0, v))
    e.w32(0x2405FF70, 0)                              # (the settings-index cache: rebuilt)


S, M = make("firmware/BLACKBOX-3.1.9.bin"), make(MOD)
fidelity(M, 1)                                        # HighQ: the stock cubic (3.1.v5: restructured, the same)
same = sum(granular(S, s) == granular(M, s) for s in range(40))
check(f"grain renderer, HighQ: both channels and every grain's state bit-identical to stock ({same} / 40 voices, 12 "
      f"blocks each)", same == 40, same)
# (3.1.v5) Normal (and every other Fidelity): linear. Grain positions, fractions and lengths stay stock's; the sound
# is close to the cubic's but not the same.
fidelity(M, 0)
state_same = out_diff = close = pitched = 0
for s in range(40):
    a, b = granular(S, s), granular(M, s)
    rate1 = struct.unpack("<f", bytes(M.uc.mem_read(GV + 0x140, 4)))[0] == 1.0   # (rate 1: copied, no interpolation)
    sa = [x[2048:] for x in a]; sb = [x[2048:] for x in b]
    state_same += sa == sb
    fa = struct.unpack(f"<{512 * len(a)}f", b"".join(x[:2048] for x in a))
    fb = struct.unpack(f"<{512 * len(b)}f", b"".join(x[:2048] for x in b))
    rms = (sum(v * v for v in fa) / len(fa)) ** 0.5 or 1.0
    err = (sum((x - y) ** 2 for x, y in zip(fa, fb)) / len(fa)) ** 0.5
    audible = max(abs(v) for v in fa) > 1e-3          # (a few voices' grains barely start: near-silent, alike)
    pitched += not rate1 and audible
    out_diff += (fa != fb) if not rate1 and audible else 0
    close += err < 0.05 * rms and (not rate1 or fa == fb)
check(f"grain renderer, Normal (linear): every grain's position / fraction / length as stock ({state_same} / 40)",
      state_same == 40, state_same)
check(f"... the output linear, not the cubic, on audible pitched voices ({out_diff} / {pitched} differ; rate 1 is "
      f"copied as stock), and close to it (error < 5 % of the level: {close} / 40)", out_diff == pitched and close == 40,
      (out_diff, pitched, close))
fidelity(M, 1)

SS, MS = clip_setup(S), clip_setup(M)
rng = random.Random(7)
same = 0
for k in range(300):
    rate = rng.choice((rng.uniform(0.1, 0.99), rng.uniform(1.01, 4.0), 1.0))
    frames = rng.choice((256, 128, 1, 3, rng.randrange(1, 257)))
    frac = rng.choice((0.0, rng.random()))
    pos = rng.randrange(0, 20000)
    length = rng.choice((1 << 20, pos + rng.randrange(0, 300)))    # near the end: the resampler stops early
    a, b = clip(S, SS, rate, frames, frac, pos, length), clip(M, MS, rate, frames, frac, pos, length)
    same += a == b
check(f"clip / slicer step: both channels, position and fraction bit-identical to stock ({same} / 300, rates "
      f"0.1 .. 4, frames 1 .. 256, near the sample's end)", same == 300, same)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
