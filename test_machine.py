"""Fidelity machine modes (SP1200, SP-12, S950, MPC60) under Unicorn.

Real firmware runs for: the stock sample-voice reader FUN_08055f0c end to end (fetch into scratch, reverse, kernel
choice, buffer helpers), entered through voice_read_entry, plus both stock kernels for the non-machine settings.
Stubbed: the sample source (FUN_08063634 fetch, FUN_080636f0 length, FUN_08063790 mono).
Reference: a Python model of the drop-sample reader.
NOT checked: how it sounds, slicer / clip pads (separate path, not hooked yet), CPU on the chip (instructions counted).
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_S0, UC_ARM_REG_S1, UC_ARM_REG_SP

from emu import STACK, Emu

e = Emu("out/solo+slice+filter+fenv+filttab+cpu+od+comp+fx2+munchi+cave/BLACKBOX.bin", "out/cave.elf")
PAD, SRC, SCR, OUT, SCRD, OUTD, ARR = 0x24060000, 0x24061000, 0x24062000, 0x24062100, 0x24064000, 0x24068000, 0x24073000
APP_PADS = 0x24020088 + 0x1840
N = 64
LEN = 3000000
stream = [0.0] * LEN


def fstr(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def fetch():
    dst, n, pos = e.arg(1), e.arg(2), e.arg(3)
    vals = [stream[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]
    e.uc.mem_write(dst, struct.pack(f"<{n}f", *vals))


e.stub(0x08063634, fetch)
e.stub(0x080636F0, value=LEN)
e.stub(0x08063790, value=0)


def set_interp(v):
    store = APP_PADS + 1 * 0xF0 + 2 * 0x30
    e.uc.mem_write(ARR, struct.pack("<HHI", 0xF1, 0, v))
    e.w32(store + 4, ARR)
    e.uc.mem_write(store + 10, struct.pack("<H", 1))
    e.w32(PAD + 0x18, 1 << 8 | 2)
    e.w32(PAD + 0x578, 0)


def bufobj(addr, data, cap):
    e.uc.mem_write(addr, struct.pack("<IIIIBB", cap, cap, data, 0, 0, 0))


def read_block(P, rate, n=N):
    """one call into the reader for output frames [0, n) starting at absolute position P"""
    bufobj(SCR, SCRD, 4096)
    bufobj(OUT, OUTD, 4096)
    ip = math.floor(P)
    e.uc.reg_write(UC_ARM_REG_S0, fstr(P - ip))
    e.uc.reg_write(UC_ARM_REG_S1, fstr(rate))
    e.w32(STACK, n)          # param_7: frames
    e.w32(STACK + 4, 0)      # param_8: dst offset
    e.w32(STACK + 8, SCR)    # param_9: scratch
    e.w32(STACK + 12, OUT)   # param_10: out
    e.call("voice_read", PAD, SRC, ip, 0, count=5_000_000)
    return list(struct.unpack(f"<{n}f", e.uc.mem_read(OUTD, 4 * n)))


def play(P, rate, blocks):
    out = []
    for _ in range(blocks):
        out += read_block(P, rate)
        P += rate * N
    return out


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


FIR = {26040: [0.00302, 0.24563, 0.5027, 0.24563, 0.00302], 40000: [-0.03947, 0.16746, 0.74402, 0.16746, -0.03947]}


def model(P, rate, n, grid):
    """drop-sample: the source read only on the machine's grid (5-tap FIR at the grid point), position from P"""
    g = 48000 / grid
    h = FIR[grid]
    out = []
    pos = P
    for i in range(n):
        k = math.floor(pos / g + 1e-9)
        j = round(k * g)
        out.append(sum(h[t] * stream[j - 2 + t] for t in range(5)))
        pos += rate
    return out


# a source with energy up high: 3 kHz + 9.5 kHz
for i in range(LEN):
    stream[i] = 0.4 * math.sin(2 * math.pi * 3000 * i / 48000) + 0.3 * math.sin(2 * math.pi * 9500 * i / 48000)


def mismatches(got, ref):
    """frames that differ; on an exact grid tie float and double may pick neighbouring grid points"""
    return [i for i in range(len(got)) if abs(got[i] - ref[i]) > 1e-4]

# --- stock settings: bit-identical to the unpatched firmware's reader
stock = Emu("firmware/BLACKBOX-3.1.9.bin", "out/cave.elf")
stock.uc.mem_map(0x24100000, 0x10000)
for addr, fn in ((0x08063634, None), (0x080636F0, LEN), (0x08063790, 0)):
    pass
stock.stub(0x080636F0, value=LEN)
stock.stub(0x08063790, value=0)


def stock_fetch():
    dst, n, pos = stock.arg(1), stock.arg(2), stock.arg(3)
    stock.uc.mem_write(dst, struct.pack(f"<{n}f", *[stream[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))


stock.stub(0x08063634, stock_fetch)


def stock_play(P, rate, blocks, hq):
    out = []
    stock.w32(PAD + 0x578, hq)
    for _ in range(blocks):
        stock.uc.mem_write(SCR, struct.pack("<IIIIBB", 4096, 4096, SCRD, 0, 0, 0))
        stock.uc.mem_write(OUT, struct.pack("<IIIIBB", 4096, 4096, OUTD, 0, 0, 0))
        ip = math.floor(P)
        stock.uc.reg_write(UC_ARM_REG_S0, fstr(P - ip))
        stock.uc.reg_write(UC_ARM_REG_S1, fstr(rate))
        for k, v in enumerate((N, 0, SCR, OUT)):
            stock.w32(STACK + 4 * k, v)
        stock.call(0x08055F0C, PAD, SRC, ip, 0, count=5_000_000)
        out += struct.unpack(f"<{N}f", stock.uc.mem_read(OUTD, 4 * N))
        P += rate * N
    return out


for v, hq, name in ((0, 0, "Normal"), (1, 0, "HighQ (engine copy reads Normal, as after a pad reset)"), (7 + 1, 0, "12k crunch")):
    set_interp(v)
    for rate in (0.7, -1.3):
        a = play(1000.25 if rate > 0 else 80000.5, rate, 4)
        b = stock_play(1000.25 if rate > 0 else 80000.5, rate, 4, hq)
        check(f"Fidelity {name}, rate {rate}: identical to the stock reader", a == b, max(abs(x - y) for x, y in zip(a, b)))
set_interp(1)
e.w32(PAD + 0x578, 1)
check("engine Interp HighQ still picks the stock HighQ kernel", play(1000.25, 0.7, 2) == stock_play(1000.25, 0.7, 2, 1))
e.w32(PAD + 0x578, 0)

# --- SP1200: drop-sample on the 26.04 kHz grid, pitch down an octave and up a fifth
set_interp(2)
for rate in (0.5, 1.4983, 0.8909):
    P = 5000.3
    got = play(P, rate, 6)
    ref = model(P, rate, 6 * N, 26040)
    err = max(abs(x - y) for x, y in zip(got, ref))
    check(f"SP1200 at rate {rate}: reads the source only on its 26.04 kHz grid, continuous across blocks (max err {err:.2e})", err < 1e-4, err)

for P in (2500000.37, 2879999.5):
    got = play(P, 0.6, 6)
    bad = mismatches(got, model(P, 0.6, 6 * N, 26040))
    check(f"SP1200 deep into a 60 s sample (position {P:.0f}): grid still exact ({len(bad)} of {len(got)} frames off)", len(bad) <= 1, bad[:5])
got = play(5000.0, 1.0, 6)
ref = model(5000.0, 1.0, 6 * N, 26040)
err = max(abs(x - y) for x, y in zip(got, ref))
check(f"SP1200 at the original pitch (stock would bypass the kernel): still read on the grid (max err {err:.2e})", err < 1e-4, err)
set_interp(0)
check("Normal at the original pitch: stock straight copy, untouched", play(5000.0, 1.0, 2) == stock_play(5000.0, 1.0, 2, 0))
set_interp(2)
got = play(5000.3, 0.5, 6)
runs, k = [], 0
while k < len(got):
    j = k
    while j < len(got) and got[j] == got[k]:
        j += 1
    runs.append(j - k)
    k = j
avg = sum(runs[1:-1]) / len(runs[1:-1])
check(f"SP1200 an octave down: each stored sample held ~2 grid ticks (avg run {avg:.2f} frames, expect 2 x 48000/26040 = 3.69)", abs(avg - 2 * 48000 / 26040) < 0.15, avg)


set_interp(1)
clean = play(20000.0, 0.5, 8)
set_interp(2)
crunch = play(20000.0, 0.5, 8)
diff = [a - b for a, b in zip(crunch, clean)]
ratio = math.sqrt(sum(d * d for d in diff) / sum(c * c for c in clean))
check(f"SP1200 an octave down differs from clean playback by {20 * math.log10(ratio):.1f} dB (drop-sample grit)", ratio > 0.05, ratio)

# --- reverse playback keeps a consistent grid
got = play(60000.0, -0.75, 6)
check("SP1200 reverse: finite, follows the source backwards", all(math.isfinite(v) for v in got) and max(abs(v) for v in got) > 0.3)
runs_ok = len(set(got)) < len(got) * 0.9
check("SP1200 reverse: still drop-sample (repeated values)", runs_ok)

# --- S950 interpolates between grid samples, MPC60 grid 40k
set_interp(4)
got = play(5000.3, 0.5, 4)
check("S950 an octave down: smooth (no repeated steps from the reader)", len(set(got)) > len(got) * 0.9)
set_interp(5)
got = play(5000.3, 0.8, 4)
ref = model(5000.3, 0.8, 4 * N, 40000)
err = max(abs(x - y) for x, y in zip(got, ref))
check(f"MPC60: grid 40 kHz (max err {err:.2e})", err < 1e-4, err)

set_interp(6)
got = play(5000.3, 0.6, 3)
err = max(abs(x - y) for x, y in zip(got, model(5000.3, 0.6, 3 * N, 26040)))
check(f"SP Raw: the same drop-sample reader as SP1200 (max err {err:.2e})", err < 1e-4, err)

# --- stereo samples: the other fetch path, both channels on the same grid
SCRR, OUTR = 0x24066000, 0x2406A000
stream_r = [0.25 * math.sin(2 * math.pi * 5000 * i / 48000) for i in range(200000)] + [0.0] * (LEN - 200000)


def fetch2():
    l, r, n, pos = e.arg(1), e.arg(2), e.arg(3), e.r32(e.uc.reg_read(UC_ARM_REG_SP))
    e.uc.mem_write(l, struct.pack(f"<{n}f", *[stream[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))
    e.uc.mem_write(r, struct.pack(f"<{n}f", *[stream_r[p] if 0 <= p < LEN else 0.0 for p in range(pos, pos + n)]))


e.stub(0x08063608, fetch2)
e.stub(0x08063790, value=1)
set_interp(2)
P, rate = 7000.6, 0.75
outl, outr = [], []
for b in range(4):
    e.uc.mem_write(SCR, struct.pack("<IIIIBB", 4096, 4096, SCRD, SCRR, 0, 1))
    e.uc.mem_write(OUT, struct.pack("<IIIIBB", 4096, 4096, OUTD, OUTR, 0, 1))
    ip = math.floor(P)
    e.uc.reg_write(UC_ARM_REG_S0, fstr(P - ip))
    e.uc.reg_write(UC_ARM_REG_S1, fstr(rate))
    for k, v in enumerate((N, 0, SCR, OUT)):
        e.w32(STACK + 4 * k, v)
    e.call("voice_read", PAD, SRC, ip, 0, count=5_000_000)
    outl += struct.unpack(f"<{N}f", e.uc.mem_read(OUTD, 4 * N))
    outr += struct.unpack(f"<{N}f", e.uc.mem_read(OUTR, 4 * N))
    P += rate * N
ref_l = model(7000.6, rate, 4 * N, 26040)
saved = stream[:]
stream[:] = stream_r
ref_r = model(7000.6, rate, 4 * N, 26040)
stream[:] = saved
el = max(abs(x - y) for x, y in zip(outl, ref_l)); er = max(abs(x - y) for x, y in zip(outr, ref_r))
err = max(el, er)
check(f"SP1200 stereo sample: both channels drop-sampled on the same grid (max err {err:.2e})", err < 1e-4, err)
e.stub(0x08063790, value=0)

# --- cost
from unicorn import UC_HOOK_CODE
cnt = [0]
h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: cnt.__setitem__(0, cnt[0] + 1))
for v, name in ((0, "Normal (stock)"), (2, "SP1200"), (4, "S950")):
    set_interp(v)
    play(5000.3, 0.8, 1)
    cnt[0] = 0
    play(5000.3, 0.8, 1)
    print(f"     reader cost, {name}: {cnt[0]} instructions per 64-frame mono block (incl. fetch stub)")
e.uc.hook_del(h)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
