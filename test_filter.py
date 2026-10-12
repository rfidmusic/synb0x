"""Pad crunch, state-variable filter (Morph LP - notch - HP, modulatable) and filter envelope under Unicorn.

Real firmware runs for: the stock cutoff and resonance curves, the audio-buffer accessors, both voice call-site thunks.
Stubbed: the modulated-parameter read (returns test values).
Reference: a Python model of the same SVF, envelope and crunch, so these checks pin the arithmetic, not the sound.
NOT checked: how it sounds, CPU load with many voices, and the real voice start / note-off (hardware).
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R6, UC_ARM_REG_S0

from emu import Emu

e = Emu("out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+comp+fx2+munchi+cave/BLACKBOX.bin", "out/cave.elf")

OBJ, PARAMS, PAD, BUF, LBUF, RBUF, AMP = 0x24060000, 0x24061000, 0x24062000, 0x24063000, 0x24064000, 0x24066000, 0x24068000
N = 64
FS = 48000.0
P_FTYPE, P_FATTACK, P_FDECAY, P_FSUSTAIN, _UNUSED, P_FDEPTH = range(0x1E1, 0x1E7)
P_FRELEASE = 0x1EB                                  # 0x1e5 is a hidden stock Keys switch
P_FMORPH = 0x1E9
LP, NOTCH, HP = 0, 500, 1000                        # Morph knob positions
values = {}


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def param():
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", values.get(e.arg(0), 0.0)))[0])


e.stub(0x0806FB30, param)
e.w32(OBJ + 0x84, PARAMS)


def curve(addr, x):
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", x))[0])
    e.call(addr)
    return struct.unpack("<f", struct.pack("<I", e.uc.reg_read(UC_ARM_REG_S0)))[0]


APP_PADS, ARR = 0x24020088 + 0x1840, 0x24073000
PAD_ROW, PAD_COL = 1, 2


def set_pad(interp=0, row=PAD_ROW, col=PAD_COL, sat=0, ftype=LP, attack=0, decay=300, sustain=0, release=300, depth=0,
            with_fenv=True, routes=()):
    """The app's record of the pad (what the screen shows and presets save)."""
    store = APP_PADS + row * 0xF0 + col * 0x30
    arr = ARR + (row * 4 + col) * 0x80
    ent = [(0x8B, 0), (0xF1, interp), (0xDB, sat)]
    if with_fenv:
        ent += [(P_FMORPH, ftype), (P_FTYPE, 0), (P_FATTACK, attack), (P_FDECAY, decay), (P_FSUSTAIN, sustain), (P_FRELEASE, release),
                (P_FDEPTH, depth)]
    e.uc.mem_write(arr, b"".join(struct.pack("<HHi", i, 0, v) for i, v in ent))
    e.w32(store + 4, arr)
    e.uc.mem_write(store + 10, struct.pack("<H", len(ent)))
    rarr = arr + 0x400                            # modulation routes: {s16 amount, -, u16 source, u16 dest, u16 slot}
    e.uc.mem_write(rarr, b"".join(struct.pack("<hHHHHH", amt, 0, src, dest, slot, 0) for src, dest, slot, amt in routes))
    e.w32(store + 0x10, rarr if routes else 0)
    e.uc.mem_write(store + 0x14, struct.pack("<H", len(routes)))


def setup(knob, res=0.0, **pad):
    values[PARAMS + 8] = knob
    values[PARAMS + 0x44] = res
    e.w32(PAD + 0x18, PAD_ROW << 8 | PAD_COL)    # engine pad id: bank << 16 | row << 8 | col
    set_pad(**pad)


def amp(stage):
    e.uc.mem_write(AMP, bytes([stage]))


def run(left, right=None, pad=PAD, silent=False, obj=OBJ):
    e.uc.mem_write(LBUF, struct.pack(f"<{len(left)}f", *left))
    if right is not None:
        e.uc.mem_write(RBUF, struct.pack(f"<{len(right)}f", *right))
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", len(left), len(left), LBUF, RBUF if right is not None else 0, int(silent), int(right is not None)))
    e.call("filter_process", obj, BUF, pad, AMP)
    l = list(struct.unpack(f"<{len(left)}f", e.uc.mem_read(LBUF, 4 * len(left))))
    r = list(struct.unpack(f"<{len(right)}f", e.uc.mem_read(RBUF, 4 * len(right)))) if right is not None else None
    return l, r


def note_on(obj=OBJ):
    """What the stock voice start does to the filter object (FUN_08076704): +0x40..+0x5f zeroed (and more)."""
    e.uc.mem_write(obj + 0x40, bytes(0x20))
    amp(1)


def reset():
    e.uc.mem_write(OBJ + 4, b"\xa5" * 0x30)          # stale stock coefficients: the patch must initialise itself
    note_on()


def level(obj=OBJ):
    return struct.unpack("<f", e.uc.mem_read(obj + 0x48, 4))[0]


def sine(hz, n=N, start=0, amp=0.5):
    return [amp * math.sin(2 * math.pi * hz * (start + i) / 48000) for i in range(n)]


def rms(x):
    return math.sqrt(sum(v * v for v in x) / len(x))


def soft(x, t):
    u = x / t
    if u > 1.5:
        return t
    if u < -1.5:
        return -t
    return t * u * (1 - 0.148148 * u * u)


def exp2f_fast(x):
    if x < -30:
        return 0.0
    i = int(x) - (x < 0 and x != int(x))
    f = x - i
    return (1 + f * (0.6565 + f * 0.3435)) * 2.0 ** i


def sin_q(x):
    x2 = x * x
    return x * (1 - x2 / 6 * (1 - x2 / 20 * (1 - x2 / 42)))


def weights(m):
    """Morph 0..1 -> (LP, BP, HP) weights, as filter.c: a plain crossfade, exact ends"""
    m = 0.0 if m <= 0.0001 else 1.0 if m >= 0.9999 else m
    return (1.0 - m, 0.0, m)


def model_svf(x, g, r, s, ftype, limit):
    w = weights(ftype / 1000) if isinstance(ftype, int) else ftype
    h = 1 / (1 + r * g + g * g)
    s1, s2 = s
    out = []
    for v in x:
        hpv = (v - r * s1 - g * s1 - s2) * h
        bp = g * hpv + s1
        s1 = soft(g * hpv + bp, limit) if limit else g * hpv + bp
        lp = g * bp + s2
        s2 = g * bp + lp
        out.append(w[0] * lp + w[1] * r * bp + w[2] * hpv)
    return out, [s1, s2]


def g_of(p):
    hz = min(max(curve(0x08060640, min(max(p, 0.0), 1.0)), 10.0), 0.45 * 48000)
    x = math.pi * hz / 48000
    return x * (15 - x * x) / (15 - 6 * x * x)


def r_of(res):
    return 1 / min(max(curve(0x080606C0, res), 0.1), 40.0)


def drive_of(res):
    d = min(max((res - 0.5) * 2, 0.0), 1.0)
    return d * d


class Model:
    """One voice of the patched filter: per-32-frame cutoff steps, knob glide, Res / drive smoothed per block."""
    def __init__(self, knob, res, ftype, depth=0.0):
        self.pos = (knob + 1) / 2
        self.base, self.r, self.d = self.pos, r_of(res), drive_of(res)
        self.res, self.ftype, self.depth = res, ftype, depth
        self.states = [[0.0, 0.0], [0.0, 0.0]]
        self.first = True

    def block(self, x, levels=None, sub=32):
        if not self.first:
            self.r += 0.33333 * (r_of(self.res) - self.r)
            self.d += 0.33333 * (drive_of(self.res) - self.d)
        self.first = False
        if self.d > 0.001:
            x = [soft(v * (1 + 3 * self.d), 1.0) for v in x]
        glide = 1 - exp2f_fast(-0.585 * sub / 256)
        out = []
        for k in range(0, len(x), sub):
            self.base += glide * (self.pos - self.base)
            g = g_of(self.base + self.depth * (levels[k // sub] if levels else 0.0))
            y, self.states[0] = model_svf(x[k:k + sub], g, 1.84776, self.states[0], self.ftype, None)
            y, self.states[1] = model_svf(y, g, self.r, self.states[1], self.ftype, 4 - 3 * self.d if self.d > 0.001 else None)
            out += y
        return out


def model_block_w(m, x, w):
    """one 32-frame step of Model with explicit weights (for a moving Morph)"""
    if m.first:
        m.first = False
    m.base += (1 - exp2f_fast(-0.585 * 32 / 256)) * (m.pos - m.base)
    g = g_of(m.base)
    y, m.states[0] = model_svf(x, g, 1.84776, m.states[0], w, None)
    y, m.states[1] = model_svf(y, g, m.r, m.states[1], w, 4 - 3 * m.d if m.d > 0.001 else None)
    return y


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


# --- the Filter knob is cutoff: far left 20 Hz, far right 20.5 kHz (the stock curve's 0..1)
check("stock curve: knob far left = 20 Hz, centre = 640 Hz, far right = 20480 Hz",
      abs(curve(0x08060640, 0.0) - 20) < 0.5 and abs(curve(0x08060640, 0.5) - 640) < 1 and abs(curve(0x08060640, 1.0) - 20480) < 1)

# --- bypass
reset()
setup(1.0)
x = sine(1000)
l, _ = run(x)
check("LP, Filter fully right, no depth: buffer untouched", all(abs(a - b) < 1e-7 for a, b in zip(l, x)))
reset()
setup(-1.0, ftype=HP)
l, _ = run(x)
check("HP, Filter fully left, no depth: buffer untouched", all(abs(a - b) < 1e-7 for a, b in zip(l, x)))
reset()
setup(1.0, ftype=NOTCH)
l, _ = run(x)
check("a notch (Morph 50%) is never skipped, even with Filter fully right", any(abs(a - b) > 1e-4 for a, b in zip(l, x)))
reset()
setup(0.2)
l, _ = run(x, silent=True)
check("silent buffer: untouched, as stock", all(abs(a - b) < 1e-7 for a, b in zip(l, x)))
reset()
setup(0.0, with_fenv=False)
l, _ = run(sine(5000))
check("pad record without the new settings (defaults: LP): Filter at centre (640 Hz) low-passes", rms(l) < 0.3 * rms(sine(5000)))

# --- each type matches the stmlib SVF model, block after block (knob glide spread over the 32-frame steps)
sig = [math.sin(i * 0.37) * 0.3 + math.sin(i * 0.05) * 0.4 for i in range(3 * N)]
for ftype, name in ((LP, "low-pass"), (HP, "high-pass"), (NOTCH, "notch")):
    reset()
    setup(-0.2, res=0.3, ftype=ftype)
    m, err = Model(-0.2, 0.3, ftype), 0.0
    for b in range(3):
        l, _ = run(sig[b * N:(b + 1) * N])
        ref = m.block(sig[b * N:(b + 1) * N])
        err = max(err, max(abs(p - q) for p, q in zip(l, ref)))
    check(f"{name} output equals the model over three blocks", err < 1e-4, err)
reset()
setup(0.4, res=0.9, ftype=HP)
m, err, loud = Model(0.4, 0.9, HP), 0.0, [v * 2.0 for v in sig]
for b in range(3):
    l, _ = run(loud[b * N:(b + 1) * N])
    err = max(err, max(abs(p - q) for p, q in zip(l, m.block(loud[b * N:(b + 1) * N]))))
check(f"high-pass with drive (Res 0.9 -> drive {drive_of(0.9):.2f}) equals the model", err < 1e-4, err)

# knob turned mid-note: glides like the stock smoothing instead of jumping
reset()
setup(-0.6)
m = Model(-0.6, 0.0, LP)
for b in range(2):
    run(sig[b * N:(b + 1) * N])
    m.block(sig[b * N:(b + 1) * N])
values[PARAMS + 8] = 0.6
m.pos = 0.8
l, _ = run(sig[2 * N:3 * N])
ref = m.block(sig[2 * N:3 * N])
check("Filter knob moved: cutoff glides (equals the model)", max(abs(p - q) for p, q in zip(l, ref)) < 1e-4)


# --- low-pass, high-pass and notch behave
def response(knob, res, hz_test, ftype=LP, blocks=8):
    reset()
    setup(knob, res, ftype=ftype)
    out = []
    for b in range(blocks):
        l, _ = run(sine(hz_test, start=b * N))
        out += l
    return rms(out[N * 4:]) / rms(sine(hz_test, n=N * 4))


def knob_for(hz):
    return 2 * math.log2(hz / 20) / 10 - 1


k = knob_for(1000)
lp_low, lp_high = response(k, 0.5, 100), response(k, 0.5, 12000)       # Res 0.5 = the stock default (Q 1.35)
check("LP at 1 kHz passes 100 Hz and cuts 12 kHz", lp_low > 0.9 and lp_high < 0.1, (lp_low, lp_high))
hp_low, hp_high = response(k, 0.5, 100, HP), response(k, 0.5, 12000, HP)
check("HP at 1 kHz cuts 100 Hz and passes 12 kHz", hp_low < 0.1 and hp_high > 0.9, (hp_low, hp_high))
n_mid, n_low, n_high = response(k, 0.5, 1000, NOTCH), response(k, 0.5, 100, NOTCH), response(k, 0.5, 10000, NOTCH)
check(f"notch at 1 kHz: cuts 1 kHz (x{n_mid:.3f}), 100 Hz and 10 kHz at the crossfade's -12 dB", n_mid < 0.05 and 0.2 < n_low < 0.3 and 0.2 < n_high < 0.3,
      (n_mid, n_low, n_high))
w = [weights(m / 1000) for m in range(0, 1001, 50)]
check("Morph weights are a plain crossfade (LP + HP = 1)", all(abs(a + c - 1) < 1e-6 for a, _, c in w), w)
sweep = [response(k, 0.5, 300, m) for m in (0, 250, 500, 750, 1000)]
check("Morph sweep at 300 Hz (below the cutoff): LP passes it, HP cuts it, in between it moves steadily",
      sweep[0] > 0.9 and sweep[-1] < 0.05 and all(b < a + 0.05 for a, b in zip(sweep, sweep[1:])), [round(v, 3) for v in sweep])
one, two = response(k, 0.5, 2000), response(k, 0.5, 4000)
check(f"24 dB/oct: one octave above cutoff {20 * math.log10(one):.0f} dB, two octaves {20 * math.log10(two):.0f} dB", two < 0.02 and two / one < 0.09, (one, two))
flat, peak = response(k, 0.0, 1000), response(k, 0.5, 1000)
check(f"resonance raises the level at the cutoff: x{peak / flat:.1f} at the default Res", peak > 3 * flat, (flat, peak))
reset()
setup(-0.3, 1.0)
worst = 0.0
for b in range(400):
    l, _ = run([((i * 7919 + b * 104729) % 2001 - 1000) / 1000.0 for i in range(N)])
    worst = max(worst, max(abs(v) for v in l))
check(f"maximum resonance on full-scale noise stays bounded (peak {worst:.1f})", worst < 4 and not math.isnan(worst), worst)
reset()
setup(-1.0, 0.0)
l, _ = run([0.5] * N)
check("knob fully left: still finite and closed", all(abs(v) < 0.6 for v in l))

# --- stereo: both channels filtered, independently
reset()
setup(knob_for(500), 0.2)
lo, hi = sine(100), sine(12000)
l, r = run(lo, hi)
reset()
setup(knob_for(500), 0.2)
l2, _ = run(lo)
check("stereo: left matches the mono run, right is filtered on its own", max(abs(a - b) for a, b in zip(l, l2)) < 1e-6 and rms(r) < rms(hi))


# --- the envelope
def seconds(v):
    return 60 * (v / 1000) ** 3


def env_run(blocks, n=256, silent=True):
    out = []
    for _ in range(blocks):
        run([0.0] * n, silent=silent)
        out.append(level())
    return out


reset()
setup(1.0, attack=300, decay=300, sustain=400, release=300, depth=0)
t_a = seconds(300)                                # 1.62 s
blocks_a = t_a * FS / 256
lv = env_run(int(blocks_a) - 1)
check(f"attack: rises linearly ({t_a:.2f} s: level after {len(lv)} blocks {lv[-1]:.3f})",
      abs(lv[-1] - len(lv) / blocks_a) < 0.01 and all(b > a for a, b in zip(lv, lv[1:])), lv[-1])
lv = env_run(3)
check("attack reaches 1, then decay starts", max(lv) > 0.99 and lv[-1] < 1.0, lv)
lv = env_run(int(seconds(300) * FS / 256) + 5)
check(f"decay settles on Sustain 0.4 within {seconds(300):.2f} s", abs(lv[-1] - 0.4) < 0.01, lv[-1])
lv = env_run(50)
check("sustain holds", all(abs(v - 0.4) < 1e-4 for v in lv), lv[-1])
setup(1.0, attack=300, decay=300, sustain=700, release=300)
lv = env_run(1)
check("sustain follows the Sustain knob", abs(lv[-1] - 0.7) < 1e-4, lv[-1])
amp(4)                                            # note-off: the amp envelope is in release
lv = env_run(int(seconds(300) * FS / 256))
check(f"release: from the held level to ~0 in {seconds(300):.2f} s", lv[-1] < 0.7 * 0.012 and lv[0] < 0.7, (lv[0], lv[-1]))
lv = env_run(100)
check("release ends at 0", lv[-1] == 0.0, lv[-1])

reset()
setup(1.0, attack=0, decay=0, sustain=1000, release=0)
lv = env_run(1, n=64)
check("Attack 0 / Decay 0: full level on the first step", lv[0] == 1.0, lv)
amp(4)
lv = env_run(1, n=64)
check("Release 0: off on the first step after the gate", lv[0] == 0.0, lv)

reset()
setup(1.0, attack=1000, decay=1000, sustain=0, release=1000)
lv = env_run(int(60 * FS / 256 / 2))
check("Attack 100: 60 s (half way after 30 s)", abs(lv[-1] - 0.5) < 0.01, lv[-1])

reset()
setup(1.0, attack=500, decay=300, sustain=500, release=200)
lv = env_run(20)
amp(4)
held = level()
lv = env_run(1)
check("gate off during attack: releases from where it was, no jump", lv[0] <= held and lv[0] > 0.5 * held, (held, lv[0]))

reset()
setup(1.0, attack=200, decay=200, sustain=500, release=500)
env_run(200)                                      # in sustain
amp(4)
env_run(10)
low = level()
amp(1)                                            # legato retrigger: amp attack again, no voice start
lv = env_run(1)
check("retrigger without a voice start: attacks again from the current level", lv[0] > low, (low, lv[0]))
note_on()
check("voice start zeroes the envelope (stock reset of +0x40..+0x5f)", level() == 0.0)
amp(5)
reset()
amp(0)
lv = env_run(5)
check("amp envelope idle: the envelope stays at 0", all(v == 0.0 for v in lv), lv)

reset()
setup(1.0, attack=0, decay=0, sustain=1000, release=0)
env_run(1)
amp(4)
env_run(2)
amp(2)                                            # gate again, amp envelope already past its attack
lv = env_run(1)
check("finished envelope restarts on a later gate", lv[0] == 1.0, lv)
for n in (1, 255, 256, 513, 2048):
    reset()
    setup(knob_for(800), attack=300, depth=200)
    l, _ = run(sine(500, n=n))
    check(f"{n}-frame block: finite output, envelope advanced by {n} frames",
          all(math.isfinite(v) for v in l) and abs(level() - n / (seconds(300) * FS)) < 1e-4, level())

reset()
setup(1.0, attack=300)
amp(1)
run([0.0] * 256, silent=True)
check("silent blocks still advance the envelope (FENV keeps moving)", level() > 0.0, level())

# --- depth moves the cutoff
reset()
setup(-1.0, 0.5, attack=0, decay=0, sustain=1000, release=0, depth=500)    # knob far left (20 Hz) + half the travel
amp(1)
out = []
for b in range(8):
    l, _ = run(sine(400, start=b * N))
    out += l
opened = rms(out[N * 4:]) / rms(sine(400, n=N * 4))
reset()
setup(-1.0, 0.5, attack=0, decay=0, sustain=1000, release=0, depth=0)
out = []
for b in range(8):
    l, _ = run(sine(400, start=b * N))
    out += l
closed = rms(out[N * 4:]) / rms(sine(400, n=N * 4))
check(f"Depth +50 at full envelope opens a closed LP to 640 Hz (400 Hz: x{closed:.3f} -> x{opened:.2f})",
      closed < 0.01 and opened > 0.7, (closed, opened))
reset()
setup(-0.2, attack=0, decay=0, sustain=1000, release=0, depth=-300, ftype=LP)
amp(1)
m = Model(-0.2, 0.0, LP, depth=-0.3)
err = 0.0
for b in range(3):
    l, _ = run(sig[b * N:(b + 1) * N])
    err = max(err, max(abs(p - q) for p, q in zip(l, m.block(sig[b * N:(b + 1) * N], levels=[1.0, 1.0]))))
check("negative Depth closes the filter by Depth x envelope (equals the model)", err < 1e-4, err)
reset()
setup(-0.4, attack=300, decay=300, sustain=500, release=300, depth=700, ftype=NOTCH)
amp(1)
m = Model(-0.4, 0.0, NOTCH, depth=0.7)
err = 0.0
for b in range(4):
    lv0 = level()
    l, _ = run(sig[b * N:(b + 1) * N] if b < 3 else sig[:N])
    # the model takes the envelope's per-step levels from the firmware's own rise (checked above)
    step = 32 / (seconds(300) * FS)
    ref = m.block(sig[b * N:(b + 1) * N] if b < 3 else sig[:N], levels=[lv0 + step, lv0 + 2 * step])
    err = max(err, max(abs(p - q) for p, q in zip(l, ref)))
check("a moving envelope steps the cutoff every 32 frames (equals the model)", err < 1e-4, err)

# --- Morph: blends in between, modulation routes move it
for m in (250, 750, 120, 900):
    reset()
    setup(-0.2, res=0.4, ftype=m)
    mod, err = Model(-0.2, 0.4, m), 0.0
    for b_ in range(3):
        l, _ = run(sig[b_ * N:(b_ + 1) * N])
        err = max(err, max(abs(p - q) for p, q in zip(l, mod.block(sig[b_ * N:(b_ + 1) * N]))))
    check(f"Morph {m / 10:.0f}%: LP / HP mix (equals the model)", err < 1e-4, err)

OBJ_AMP_A = OBJ - 0x7C                            # sample voice: amp stage byte at voice + 0x2c = obj - 0x7c


def run_voice(left, obj=OBJ, amp_at=OBJ_AMP_A, pad=PAD):
    e.uc.mem_write(amp_at, b"\x01")
    e.uc.mem_write(LBUF, struct.pack(f"<{len(left)}f", *left))
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", len(left), len(left), LBUF, 0, 0, 0))
    e.call("filter_process", obj, BUF, pad, amp_at)
    return list(struct.unpack(f"<{len(left)}f", e.uc.mem_read(LBUF, 4 * len(left))))


VOICE_A = OBJ - 0xA8
for src, field, val, amt, name in ((4, 0x524, 1.0, 500, "LFO"), (0xE, 0x90, 0.5, 1000, "KEY"), (0xD, 0x88, -0.5, -1000, "VEL")):
    reset()
    e.uc.mem_write(VOICE_A + field, struct.pack("<f", val))
    setup(-0.2, res=0.4, ftype=LP, routes=[(src, P_FMORPH, 0, amt)])
    mod, err = Model(-0.2, 0.4, 500), 0.0                 # 0 + amount x value = 0.5: the notch
    for b_ in range(3):
        l = run_voice(sig[b_ * N:(b_ + 1) * N])
        err = max(err, max(abs(p - q) for p, q in zip(l, mod.block(sig[b_ * N:(b_ + 1) * N]))))
    check(f"{name} -> Morph ({amt / 10:+.0f}% x {val}): sample voice morphs from LP to the notch (equals the model)", err < 1e-4, err)
reset()
e.uc.mem_write(VOICE_A + 0x524, struct.pack("<f", 1.0))
setup(-0.2, res=0.4, ftype=NOTCH, routes=[(4, P_FMORPH, 0, 1000)])
mod, err = Model(-0.2, 0.4, 1000), 0.0
for b_ in range(2):
    l = run_voice(sig[b_ * N:(b_ + 1) * N])
    err = max(err, max(abs(p - q) for p, q in zip(l, mod.block(sig[b_ * N:(b_ + 1) * N]))))
check("Morph + modulation clamps at HP (50% + 100% x 1)", err < 1e-4, err)
reset()
setup(1.0, ftype=LP, routes=[(4, P_FMORPH, 0, 1000)])
e.uc.mem_write(VOICE_A + 0x524, struct.pack("<f", 0.0))
l = run_voice(sine(1000))
check("a route to Morph keeps the filter running even at LP fully open (the source may move it)",
      any(abs(a - b) > 1e-6 for a, b in zip(l, sine(1000))))
reset()
setup(-0.2, res=0.4, ftype=LP, attack=0, decay=0, sustain=1000, release=0, routes=[(1, P_FMORPH, 0, 500)])
mod, err = Model(-0.2, 0.4, LP), 0.0
for b_ in range(3):
    l = run_voice(sig[b_ * N:(b_ + 1) * N])
    ref = []
    for k in range(2):                                    # FENV level 1 from the first step: Morph 0 + 0.5 x 1
        ref += model_block_w(mod, sig[b_ * N + 32 * k: b_ * N + 32 * (k + 1)], weights(0.5))
    err = max(err, max(abs(p - q) for p, q in zip(l, ref)))
check("FENV -> Morph: follows the envelope per 32-frame step (equals the model)", err < 1e-4, err)
CPAD = 0x24070000
for v in (0, 1):
    cobj = CPAD + 0x3AC + v * 0x410
    e.w32(cobj + 0x84, PARAMS)
    e.uc.mem_write(cobj + 4, b"\xa5" * 0x30)
    e.uc.mem_write(cobj + 0x40, bytes(0x20))
    e.uc.mem_write(cobj - 0x14C + 0x54, struct.pack("<f", 0.5))      # KEY of this voice
    e.w32(CPAD + 0x18, 3 << 8 | 0)
    set_pad(row=3, col=0, ftype=LP, routes=[(0xE, P_FMORPH, 1, 1000)])
    values[PARAMS + 8], values[PARAMS + 0x44] = -0.2, 0.4
    mod, err = Model(-0.2, 0.4, 500), 0.0
    for b_ in range(2):
        l = run_voice(sig[b_ * N:(b_ + 1) * N], obj=cobj, amp_at=cobj + 0x110, pad=CPAD)
        err = max(err, max(abs(p - q) for p, q in zip(l, mod.block(sig[b_ * N:(b_ + 1) * N]))))
    check(f"clip / slicer voice {v + 1}: KEY -> Morph read from its own block", err < 1e-4, err)

# --- no clicks: a clean 110 Hz tone through moving controls; the 3rd difference shows any step the tone cannot have
def click_run(blocks, control, amp_at=lambda b: 3):
    OBJA = OBJ - 0x7C
    note_on()
    out = []
    for b_ in range(blocks):
        control(b_)
        e.uc.mem_write(OBJA, bytes([amp_at(b_)]))
        x = [0.4 * math.sin(2 * math.pi * 110 * (b_ * 256 + i) / FS) for i in range(256)]
        e.uc.mem_write(LBUF, struct.pack("<256f", *x))
        e.uc.mem_write(BUF, struct.pack("<IIIIBB", 256, 256, LBUF, 0, 0, 0))
        e.call("filter_process", OBJ, BUF, PAD, OBJA)
        out += struct.unpack("<256f", e.uc.mem_read(LBUF, 1024))
    d = [out[i] - 3 * out[i - 1] + 3 * out[i - 2] - out[i - 3] for i in range(4 * 256, len(out))]
    return max(abs(v) for v in d)


def ctl_open(b_):
    values[PARAMS + 8], values[PARAMS + 0x44] = (1.0 if (b_ // 8) % 2 else 0.3), 0.5


setup(0.3, 0.5)
worst = click_run(64, ctl_open)
check(f"no click turning Filter to fully open (filter stops) and back (worst step {worst:.4f})", worst < 0.003, worst)


def ctl_morph(b_):
    values[PARAMS + 8], values[PARAMS + 0x44] = 0.0, 0.5
    set_pad(ftype=int(500 + 500 * math.sin(b_ / 5)))


setup(0.0, 0.5)
worst = click_run(60, ctl_morph)
check(f"no click sweeping Morph LP -> notch -> HP (worst step {worst:.4f})", worst < 0.003, worst)


def ctl_edges(b_):
    values[PARAMS + 8], values[PARAMS + 0x44] = 0.0, 0.5
    set_pad(ftype=[0, 30, 0, 970, 1000, 970][b_ % 6])


worst = click_run(60, ctl_edges)
check(f"no click stepping Morph across its LP and HP ends (worst step {worst:.4f})", worst < 0.003, worst)


def ctl_lfo(b_):
    values[PARAMS + 8], values[PARAMS + 0x44] = 0.0, 0.5
    e.uc.mem_write(OBJ - 0xA8 + 0x524, struct.pack("<f", math.sin(2 * math.pi * 4.0 * b_ * 256 / FS)))


setup(0.0, 0.5, ftype=NOTCH, routes=[(4, P_FMORPH, 0, 1000)])
worst = click_run(60, ctl_lfo)
check(f"no click with a 4 Hz LFO on Morph at full depth (worst step {worst:.4f})", worst < 0.003, worst)

# --- a 3.1.9-syn preset: Type HP / BP becomes Morph 100 / 50 (the notch: Morph has no BP) in the record, once
for old, want_morph, name in ((1, 1000, "HP"), (2, 500, "BP"), (0, 0, "LP")):
    reset()
    store = APP_PADS + PAD_ROW * 0xF0 + PAD_COL * 0x30
    arr = ARR + (PAD_ROW * 4 + PAD_COL) * 0x80
    ents = [(0x8B, 0), (0xDB, 0), (P_FTYPE, old), (P_FMORPH, 0), (P_FDEPTH, 0)]
    e.uc.mem_write(arr, b"".join(struct.pack("<HHi", i, 0, v) for i, v in ents))
    e.w32(store + 4, arr)
    e.uc.mem_write(store + 10, struct.pack("<H", len(ents)))
    e.w32(store + 0x10, 0)
    e.uc.mem_write(store + 0x14, struct.pack("<H", 0))
    values[PARAMS + 8], values[PARAMS + 0x44] = -0.2, 0.4
    e.w32(PAD + 0x18, PAD_ROW << 8 | PAD_COL)
    run(sig[:N])
    rec = {struct.unpack_from("<H", e.uc.mem_read(arr + 8 * i, 2))[0]: e.r32(arr + 8 * i + 4) for i in range(len(ents))}
    check(f"3.1.9-syn preset with Type {name}: record now Morph {want_morph / 10:.0f}%, Type LP",
          rec[P_FMORPH] == want_morph and rec[P_FTYPE] == 0, rec)
    e.w32(arr + 8 * 3 + 4, 300)                    # the user then turns Morph
    run(sig[:N])
    check(f"  ... and a later Morph edit is kept (no second conversion)", e.r32(arr + 8 * 3 + 4) == 300 and e.r32(arr + 8 * 2 + 4) == 0)

# --- crunch
reset()
setup(1.0, interp=7 + 1)                       # 12k, filter skipped
x = sine(997, n=N)
l, _ = run(x)
runs, k = [], 0
while k < N:
    j = k
    while j < N and l[j] == l[k]:
        j += 1
    runs.append(j - k)
    k = j
check("12k: output holds each value for 4 samples (48k / 12k)", all(v == 4 for v in runs[1:-1]), runs)
check("12k: held values are 12-bit (multiples of 1/2048)", all(abs(v * 2048 - round(v * 2048)) < 1e-3 for v in l))
reset()
setup(1.0, interp=7 + 1)
l, _ = run(sine(997), pad=0)
check("no pad passed: no crunch, filter skipped (defaults)", all(abs(p - q) < 1e-7 for p, q in zip(l, sine(997))))
for v, name in ((0, "Normal"), (1, "HighQ"), (14, "a value past the list")):
    reset()
    setup(1.0, interp=v)
    l, _ = run(sine(997))
    check(f"Interp {name}: no crunch", all(abs(p - q) < 1e-7 for p, q in zip(l, sine(997))))
reset()
setup(knob_for(2000), 0.0, interp=7 + 3)        # 8k into the low-pass
l, _ = run(sine(997))
check("crunch and filter together: crunched, then low-passed (no longer stair-stepped)", len(set(l)) > N // 2)
reset()
setup(-0.6, 0.3)
run(sine(997))
check("state from an older build (magic SVF1) is reinitialised, not reused", e.r32(OBJ + 4) == 0x53564632)

# --- cached settings positions follow the record when it changes
def record(entries, row=PAD_ROW, col=PAD_COL, at=None):
    store = APP_PADS + row * 0xF0 + col * 0x30
    arr = at or ARR + (row * 4 + col) * 0x80
    e.uc.mem_write(arr, b"".join(struct.pack("<HHi", i, 0, v) for i, v in entries))
    e.w32(store + 4, arr)
    e.uc.mem_write(store + 10, struct.pack("<H", len(entries)))


def is_crunched(l):
    return len(set(l)) <= N // 4 + 1


reset()
values[PARAMS + 8] = 1.0
e.w32(PAD + 0x18, PAD_ROW << 8 | PAD_COL)
base = [(0x8B, 0), (0xDB, 0), (P_FMORPH, LP), (P_FDEPTH, 0)]
record(base + [(0xF1, 0)])
run(sine(997))
l, _ = run(sine(997))
check("cache: Interp Normal, filter skipped", not is_crunched(l))
record(base + [(0xF1, 7 + 1)])                     # same layout, value changed (edit on the screen)
l, _ = run(sine(997))
check("cache: a changed value is read on the next block (12k crunch)", is_crunched(l))
record([(0xF1, 7 + 1)] + base)                     # same count, entries moved
l, _ = run(sine(997))
check("cache: entries moved: found again", is_crunched(l))
record(base + [(0xF1, 0), (0x99, 0)], at=0x24076000)   # another record (pad type changed): rescanned
l, _ = run(sine(997))
check("cache: a different record: rescanned (Normal again)", not is_crunched(l))
record([(0x8B, 0), (0xDB, 0)])                     # the new settings gone: defaults
values[PARAMS + 8] = 0.0
l, _ = run(sine(5000))
check("cache: settings missing from the record: defaults (LP at 640 Hz)", rms(l) < 0.3 * rms(sine(5000)))
record(base + [(0xF1, 2)])                         # SP1200: a machine mode
e.call("pad_machine_mode", PAD)
m1 = e.uc.reg_read(__import__("unicorn").arm_const.UC_ARM_REG_R0)
record([(0xF1, 0)] + base)
e.call("pad_machine_mode", PAD)
m0 = e.uc.reg_read(__import__("unicorn").arm_const.UC_ARM_REG_R0)
check("Fidelity cache (overdrive / reader): follows a value change and a moved entry", (m1, m0) == (1, 0), (m1, m0))

# --- call sites: both pass the pad from r6 and the voice's amp envelope stage
reset()
setup(1.0, interp=7 + 1, attack=300)
VOICE = OBJ - 0xA8                              # class A: filter object = voice + 0xa8, amp envelope stage = voice + 0x2c
e.uc.mem_write(VOICE + 0x2C, bytes([1]))
e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *sine(997)))
e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, 0, 0, 0))
e.uc.reg_write(UC_ARM_REG_R6, PAD)
e.call("filter_voice_a", OBJ, BUF)
l = struct.unpack(f"<{N}f", e.uc.mem_read(LBUF, 4 * N))
check("sample-pad call site passes its pad (r6): crunch applies", len(set(l)) <= N // 4 + 1)
check("sample-pad call site passes the voice's amp stage: the envelope started", level() > 0.0, level())

CPAD = 0x24070000                               # class B: voice blocks at pad + 0x260 + v * 0x410
for v in (0, 1):
    obj = CPAD + 0x3AC + v * 0x410
    e.w32(obj + 0x84, PARAMS)
    e.uc.mem_write(obj + 0x40, bytes(0x20))
    e.uc.mem_write(obj + 0x110, bytes([1]))     # block + 0x25c: amp envelope stage
    e.w32(CPAD + 0x18, 3 << 8 | 0)
    set_pad(interp=7 + 1, row=3, col=0, attack=300)
    e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *sine(997)))
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, 0, 0, 0))
    e.uc.reg_write(UC_ARM_REG_R6, CPAD)
    values[PARAMS + 8] = 1.0
    e.call("filter_voice_b", obj, BUF)
    l = struct.unpack(f"<{N}f", e.uc.mem_read(LBUF, 4 * N))
    check(f"clip / slicer voice {v + 1}: its pad's settings apply (crunch), amp stage read (envelope started)",
          len(set(l)) <= N // 4 + 1 and level(obj) > 0.0, (len(set(l)), level(obj)))

print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
