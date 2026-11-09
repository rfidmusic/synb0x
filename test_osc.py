"""The oscillator (Osc tab, 3.1.uo; 3.1.v1: modulation only) under Unicorn, through the real filter_process.

Real firmware runs for: the pad record lookup (FUN_08093e9c), the stock sine table the oscillator reads, the cutoff and
Res curves. Stubbed: the modulated-parameter read (returns test values; the pad's Pitch at voice + 0x288 is 0).
The oscillator is never heard (3.1.v1): it is measured through OSC -> Level at 100 % on a steady input (the voice
comes out as input x (1 + oscillator)). Checked: pitch (cents) against the note, Octave, Tune and Fine; each wave's
shape and level; Wave as a selector; pulse width; Level linear; not in the audio path (Osc on, no route: the sample
passes unchanged; a stored OSC/MOD setting of either value modulates the same); where it runs (sample voices of Sample
pads only, not granular / clip, not on a silent buffer); no DSP when it's off or nothing routes from it; OSC -> Level
(per frame) and OSC -> Filter; routes onto Tune / Wave / Level; the phase restarting at a note start; CPU per block;
in the stock voice routine a silent sample stays silent with the oscillator on.
NOT checked: how it sounds, the Osc tab on the screen, presets (hardware).
"""
import math
import struct
import sys

import numpy as np
from unicorn import UC_HOOK_BLOCK
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

src = open("test_filter.py").read()
ns = {"__name__": "test_osc"}
exec(compile(src[:src.index("# --- the Filter knob is cutoff")], "test_filter.py", "exec"), ns)
e, values = ns["e"], ns["values"]
PARAMS, PAD, BUF, LBUF, RBUF = ns["PARAMS"], ns["PAD"], ns["BUF"], ns["LBUF"], ns["RBUF"]
APP_PADS, ARR = ns["APP_PADS"], ns["ARR"]
FS, N = 48000.0, 256
VOICE = 0x24074000
OBJ = VOICE + 0xA8
AMP = OBJ - 0x7C                                     # a sample voice's amp envelope stage
P_FILTER, P_LEVEL, P_FMORPH = 200, 0x04, 0x1E9
OSC = dict(on=0x1F0, mode=0x1F1, wave=0x1F2, level=0x1F3, oct=0x1DC, tune=0x1DD, fine=0x1DE, pw=0x1DF, track=0x1E0)
SRC_VEL, SRC_OSC = 0x0D, 3
fails = 0
# instructions executed, per basic block (hooked before anything runs: Unicorn keeps translated code without it)
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
cache, count = {}, [0]


def hook(uc, addr, size, _):
    c = cache.get((addr, size))
    if c is None:
        c = cache[(addr, size)] = len(list(md.disasm(bytes(uc.mem_read(addr, size)), addr)))
    count[0] += c


e.uc.hook_add(UC_HOOK_BLOCK, hook)


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


PROBE = (SRC_OSC, P_LEVEL, 2, 1000)                  # OSC -> Level 100 % (slot 2): how the oscillator is measured


def record(padmode=0, routes=(), model=0, old=False, probe=True, **osc):
    """the pad record, as the defaults lay it out: ..., AD pair, Filter Type, the eight oscillator settings, Osc Track,
    Atk / Dec Slope (3.1.v7: no LFO Mode). old: a record from before 3.1.uo (ends at Filter Type). probe: with OSC ->
    Level 100 % (if Osc is on)"""
    o = dict(on=0, mode=0, wave=0, level=700, oct=3, tune=500, fine=0, pw=0, track=1)
    o.update(osc)
    if probe and o["on"]:
        routes = list(routes) + [PROBE]
    ent = [(0x8B, padmode), (0xF1, 0), (0xDB, 0), (P_FMORPH, 0), (0x1E1, 0), (0x1E2, 0), (0x1E3, 300), (0x1E4, 0),
           (0x1EB, 300), (0x1E6, 0), (0x1EC, 0), (0x1ED, 300), (0x1EF, model)]
    if not old:
        ent += [(OSC[k], o[k]) for k in ("on", "mode", "wave", "level", "oct", "tune", "fine", "pw", "track")]
        ent += [(0x1C0, 500), (0x1C1, 270)]
    store = APP_PADS + 1 * 0xF0 + 2 * 0x30
    e.uc.mem_write(ARR, b"".join(struct.pack("<HHi", i, 0, v) for i, v in ent))
    e.w32(store + 4, ARR)
    e.uc.mem_write(store + 10, struct.pack("<H", len(ent)))
    rarr = ARR + 0x400
    e.uc.mem_write(rarr, b"".join(struct.pack("<hHHHHH", amt, 0, s, d, slot, 0) for s, d, slot, amt in routes))
    e.w32(store + 0x10, rarr if routes else 0)
    e.uc.mem_write(store + 0x14, struct.pack("<H", len(routes)))


def note_on(note=60, filt=1.0, res=0.5, vel=1.0):
    e.uc.mem_write(OBJ + 4, b"\xa5" * 0x30)
    e.uc.mem_write(OBJ + 0x40, bytes(0x20))          # voice start
    e.w32(OBJ + 0x84, PARAMS)
    e.w32(PAD + 0x18, 1 << 8 | 2)
    e.uc.mem_write(AMP, bytes([1]))
    e.uc.mem_write(VOICE + 0x90, struct.pack("<f", (note - 60) / 60))   # KEY
    e.uc.mem_write(VOICE + 0x88, struct.pack("<f", vel))                  # VEL
    values[PARAMS + 8], values[PARAMS + 0x44] = filt, res
    values[VOICE + 0x288] = 0.0                                           # pad Pitch


DC = 0.5


def blocks(count, x=None, silent=False, amp=AMP):
    """the voice's output; with no input given, the oscillator as OSC -> Level shows it (steady input DC: y / DC - 1)"""
    probe = x is None
    out = []
    for b in range(count):
        blk = np.full(N, DC) if probe else x[b * N:(b + 1) * N]
        e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *blk))
        e.uc.mem_write(RBUF, struct.pack(f"<{N}f", *blk))
        e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, RBUF, int(silent), 1))
        e.call("filter_process", OBJ, BUF, PAD, amp)
        out += struct.unpack(f"<{N}f", e.uc.mem_read(LBUF, 4 * N))
    return np.array(out) / DC - 1.0 if probe else np.array(out)


def pitch(y):
    """rising zero crossings of a sine, interpolated: the mean period"""
    seg = y[len(y) // 4:]
    i = np.nonzero((seg[:-1] < 0) & (seg[1:] >= 0))[0]
    t = i + seg[i] / (seg[i] - seg[i + 1])
    return FS * (len(t) - 1) / (t[-1] - t[0])


def peak_hz(y):
    seg = y[len(y) // 4:]
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    k = int(np.argmax(sp[1:])) + 1
    a, b, c = (math.log(sp[k + d] + 1e-30) for d in (-1, 0, 1))
    return (k + 0.5 * (a - c) / (a - 2 * b + c)) * FS / len(seg)


def knob_for(hz):
    return 2 * math.log2(hz / 20) / 10 - 1


def cents(f, want):
    return 1200 * math.log2(f / want)


C4 = 261.6256
# --- pitch
rows = []
for note, oct_, tune, fine, want_st in ((60, 3, 500, 0, 0), (69, 3, 500, 0, 0), (48, 3, 500, 0, 0), (60, 0, 500, 0, 0),
                                        (60, 6, 500, 0, 0), (60, 3, 0, 0, -6), (60, 3, 1000, 0, 6), (60, 3, 750, 0, 3),
                                        (60, 3, 500, 1000, 0.5), (60, 3, 500, -1000, -0.5), (84, 4, 500, 0, 0)):
    record(on=1, wave=0, level=1000, oct=oct_, tune=tune, fine=fine)
    note_on(note)
    f = pitch(blocks(48))
    want = C4 * 2 ** ((note - 60 + (oct_ - 3) * 12 + want_st) / 12)
    rows.append((note, oct_ - 3, (tune - 500) * 0.012, fine * 0.05, round(f, 2), round(cents(f, want), 2)))
check(f"pitch follows note, Octave (-3..+3), Tune (+-6 st) and Fine (+-50 c) within {max(abs(r[-1]) for r in rows):.2f} "
      "cents", all(abs(r[-1]) < 1.0 for r in rows), rows)

# --- Osc Track Off: C4 whatever the note, the pad's Pitch and glide; Octave / Tune / Fine still apply
rows = []
for note, oct_, tune, fine, want_st in ((60, 3, 500, 0, 0), (84, 3, 500, 0, 0), (36, 3, 500, 0, 0), (72, 4, 750, 1000, 15.5)):
    record(on=1, wave=0, level=1000, oct=oct_, tune=tune, fine=fine, track=0)
    note_on(note)
    values[VOICE + 0x288] = 0.5                      # pad Pitch +6 semitones: ignored too
    e.uc.mem_write(OBJ + 0x58, struct.pack("<f", -3.0))   # glide 3 semitones below: ignored too
    f = pitch(blocks(48))
    rows.append((note, round(f, 2), round(cents(f, C4 * 2 ** (want_st / 12)), 2)))
values[VOICE + 0x288] = 0.0
check(f"Osc Track Off: fixed C4 for every note, Pitch and glide ignored, Octave / Tune / Fine applied (within "
      f"{max(abs(r[-1]) for r in rows):.2f} cents)", all(abs(r[-1]) < 1.0 for r in rows), rows)
record(on=1, wave=0, level=1000, track=1)
note_on(60)
values[VOICE + 0x288] = 0.5
f = pitch(blocks(48))
values[VOICE + 0x288] = 0.0
check(f"Osc Track On: follows the pad's Pitch (+6 semitones: {f:.1f} Hz)", abs(cents(f, C4 * 2 ** 0.5)) < 1.0, f)

# --- waves (filter fully open: skipped; the oscillator alone)
record(on=1, wave=0, level=1000)
note_on(57)                                          # A3, 220 Hz
y = blocks(32)[N:]
sp = np.abs(np.fft.rfft(y * np.hanning(len(y))))
k = int(np.argmax(sp))
h = max(20 * math.log10(sp[k * m - 3:k * m + 4].max() / sp[k]) for m in (2, 3, 4, 5))
check(f"sine: peak {np.abs(y).max():.3f} (Level 100 % = 1), strongest harmonic {h:.0f} dB",
      abs(np.abs(y).max() - 1.0) < 0.012 and h < -60, (np.abs(y).max(), h))
rms = {"sine": np.sqrt(np.mean(y ** 2))}
record(on=1, wave=1, level=1000)
note_on(57)
y = blocks(32)[N:]
SQ = 0.70711                                        # as loud as the sine
check(f"square: +-{SQ:.3f}, half the cycle each way (mean {y.mean():+.3f})", abs(np.percentile(y, 95) - SQ) < 0.06 and
      abs(np.percentile(y, 5) + SQ) < 0.06 and abs(y.mean()) < 0.04, (np.percentile(y, 95), np.percentile(y, 5), y.mean()))
rms["square"] = np.sqrt(np.mean(y ** 2))
record(on=1, wave=2, level=1000)
note_on(57)
y = blocks(32)[N:]
TRI = 1.22474
hist = np.histogram(y, bins=10, range=(-TRI, TRI))[0]
check(f"triangle: +-{TRI:.3f}, every level equally often (a straight ramp)", abs(np.abs(y).max() - TRI) < 0.016 and
      hist.min() > 0.7 * hist.mean(), hist)
rms["triangle"] = np.sqrt(np.mean(y ** 2))
record(on=1, wave=3, level=1000)
note_on(45)                                          # 110 Hz
y = blocks(32)[N:]
SAW = 1.22474
d1 = np.diff(y)
rising = float(np.mean(d1 > 0))
hist = np.histogram(y, bins=10, range=(-SAW, SAW))[0]
check(f"saw: +-{SAW:.3f} (98 % of samples within), rising {rising * 100:.0f} % of the time with one drop per cycle, every "
      "level equally often", abs(np.percentile(np.abs(y), 98) - SAW) < 0.06 and rising > 0.96 and
      hist.min() > 0.7 * hist.mean(), (np.percentile(np.abs(y), 98), rising, hist))
rms["saw"] = np.sqrt(np.mean(y ** 2))
# Pulse W bends every wave; Square off the centre is a pulse
for pw, duty in ((0, 0.5), (-1000, 0.05), (1000, 0.95), (-555, 0.25)):
    record(on=1, wave=1, level=1000, pw=pw)
    note_on(45)                                      # 110 Hz: long cycles, the edges' band-limiting barely shows
    y = blocks(32)[N:]
    high = float(np.mean(y > 0.0 + y.mean()))
    check(f"square, Pulse W {pw / 10:+.1f}: {high * 100:.1f} % of the cycle high (want {duty * 100:.0f} %), no DC "
          f"({y.mean():+.4f})", abs(high - duty) < 0.01 and abs(y.mean()) < 0.04, (high, y.mean()))
for w, name in ((0, "sine"), (2, "triangle"), (3, "saw")):
    for pw in (-800, 800):
        record(on=1, wave=w, level=1000, pw=pw)
        note_on(45)
        y = blocks(32)[N:]
        record(on=1, wave=w, level=1000)
        note_on(45)
        y0 = blocks(32)[N:]
        lvl = 20 * np.log10(np.sqrt(np.mean((y - y.mean()) ** 2)) / np.sqrt(np.mean(y0 ** 2)))
        check(f"{name}, Pulse W {pw / 10:+.0f}: bent (differs from the plain wave by up to {np.abs(y - y0).max():.2f}), "
              f"no DC ({y.mean():+.4f}), level {lvl:+.1f} dB of the plain wave (a bent wave loses its DC part)",
              np.abs(y - y0).max() > 0.2 and abs(y.mean()) < 0.012 and -6.0 < lvl < 0.5 and np.isfinite(y).all(),
              (np.abs(y - y0).max(), y.mean(), lvl))
db = {k: 20 * np.log10(v / rms["sine"]) for k, v in rms.items()}
check("every wave as loud as the sine (RMS within 0.3 dB): " + ", ".join(f"{k} {v:+.2f} dB" for k, v in db.items()),
      all(abs(v) < 0.3 for v in db.values()), db)
def wave_out(w, **kw):
    record(on=1, wave=w, level=1000, **kw)
    note_on(45)
    return blocks(16)[N:]


old_map = [(old, new) for old, new in ((4, 0), (166, 0), (167, 1), (333, 1), (499, 1), (500, 2), (667, 2), (832, 2),
                                       (833, 1), (1000, 1))]                    # (its pulse: Square)
same = all(np.array_equal(wave_out(old), wave_out(new)) for old, new in old_map)
check("Wave is a selector (Sine, Square, Triangle, Saw); an older build's 0..1000 Wave plays the nearest wave",
      same, old_map)
record(on=1, wave=0, level=350)
note_on(57)
pk = np.abs(blocks(16)[N:]).max()
check(f"Level 35 %: linear (a modulation depth), sine peak 0.35 ({pk:.4f})", abs(pk - 0.35) < 0.004, pk)
record(on=1, wave=0, level=700)
note_on(57)
pk = np.abs(blocks(16)[N:]).max()
check(f"Level 70 % (the default): sine peak {pk:.3f}", abs(pk - 0.7) < 0.008, pk)

# --- not in the audio path (3.1.v1): on, every wave, either stored OSC/MOD value, no route -> the sample unchanged

# --- where it runs
x = 0.3 * np.sin(2 * np.pi * 330 * np.arange(16 * N) / FS)
record(on=0)
note_on(57)
ref = blocks(8, x)
for label, kw, amp_ in (("Osc off", dict(on=0), AMP), ("granular pad (mode 3)", dict(on=1, padmode=3), AMP),
                        ("clip pad", dict(on=1, padmode=1), AMP), ("a clip / slicer voice", dict(on=1), OBJ + 0x110),
                        ("Osc on, no route (stored OSC)", dict(on=1, mode=0, probe=False), AMP),
                        ("Osc on, no route (stored MOD)", dict(on=1, mode=1, probe=False), AMP),
                        ("Osc on, square, Level 100 %, no route", dict(on=1, wave=1, level=1000, probe=False), AMP),
                        ("a record from before 3.1.uo", dict(old=True), AMP)):
    record(**kw)
    note_on(57)
    if amp_ != AMP:
        e.uc.mem_write(amp_, bytes([1]))
    y = blocks(8, x, amp=amp_)
    check(f"{label}: the sample passes as without an oscillator", np.abs(y - ref).max() == 0.0, np.abs(y - ref).max())
record(on=1, wave=0, level=1000)
note_on(57)
y = blocks(4, np.zeros(4 * N), silent=True)
check("silent buffer (no sample playing): the oscillator doesn't run, buffer untouched", np.abs(y).max() == 0.0)

# --- no DSP when off: instructions per block


def cost(**kw):
    record(**kw)
    note_on(57, filt=knob_for(2000), res=0.5)
    blocks(4, x)
    count[0] = 0
    blocks(4, x[:4 * N])
    return count[0] / 4


base = cost(on=0)
off_cost = {"Osc off": cost(on=0, wave=500), "no route": cost(on=1, probe=False), "old record": cost(old=True)}
check(f"Osc off / on with no route / a pre-3.1.uo record: {off_cost['Osc off']:.0f} / {off_cost['no route']:.0f} / "
      f"{off_cost['old record']:.0f} instructions per block "
      f"vs {base:.0f} (no oscillator DSP: only its settings and routes read, under 1 per frame)",
      all(v - base < N for v in off_cost.values()), (base, off_cost))
on_cost = {name: cost(on=1, wave=w) for name, w in (("sine", 0), ("square", 1), ("triangle", 2), ("saw", 3))}
print("     oscillator cost per stereo voice per block, OSC -> Level (instructions, on top of the filter): " +
      ", ".join(f"{k} {v - base:,.0f}" for k, v in on_cost.items()))
check("oscillator on, OSC -> Level: every wave under 60 instructions per frame (one wave at a time)",
      all((v - base) / N < 60 for k, v in on_cost.items()),
      on_cost)

# --- MOD: OSC -> Level (per frame) and OSC -> Filter
record(on=1, mode=1, wave=0, level=1000, routes=[(SRC_OSC, P_LEVEL, 0, 1000)], probe=False)
note_on(57)
xm = 0.3 * np.ones(8 * N)
y = blocks(8, xm)[N:]
osc_ref = np.sin(2 * np.pi * 220 * np.arange(len(y)) / FS)
lev = y / 0.3 - 1.0
f_am = pitch(lev)
check(f"MOD -> Level 100 %: the voice times (1 + oscillator) per frame (AM at {f_am:.1f} Hz), oscillator not heard",
      abs(cents(f_am, 220)) < 2 and abs(np.abs(lev).max() - 1.0) < 0.01, (f_am, np.abs(lev).max()))
record(on=0)
note_on(57, filt=knob_for(1000), res=0.7)
y0 = blocks(16, x)
record(on=1, mode=1, wave=0, level=1000, routes=[(SRC_OSC, P_FILTER, 0, 300)], probe=False)
note_on(57, filt=knob_for(1000), res=0.7)
y1 = blocks(16, x)
check(f"MOD -> Filter: the cutoff moves with the oscillator (difference {np.abs(y1 - y0).max():.3f}), finite",
      np.abs(y1 - y0).max() > 0.01 and np.isfinite(y1).all() and np.abs(y1).max() < 4, np.abs(y1 - y0).max())

# --- every slot used (Morph, Pulse W, Level, Tune x 3 from VEL), OSC -> Filter last: still applied (18 routes kept)
full = [(SRC_VEL, d, s, 10) for d in (P_FMORPH, OSC["pw"], OSC["level"], OSC["tune"]) for s in range(3)]
record(on=0, routes=full)
note_on(57, filt=knob_for(1000), res=0.7)
y0 = blocks(16, x)
record(on=1, mode=1, wave=0, level=1000, routes=full + [(SRC_OSC, P_LEVEL, s, 300) for s in range(3)] +
       [(SRC_OSC, P_FILTER, s, 100) for s in range(3)], probe=False)
note_on(57, filt=knob_for(1000), res=0.7)
y1 = blocks(16, x)
check(f"18 routes (every slot of Morph, Pulse W, Level, Tune, OSC -> Level, OSC -> Filter): the last ones still apply "
      f"(difference {np.abs(y1 - y0).max():.3f})", np.abs(y1 - y0).max() > 0.01 and np.isfinite(y1).all(), np.abs(y1 - y0).max())

# --- routes onto the oscillator's own knobs
record(on=1, wave=0, level=1000, routes=[(SRC_VEL, OSC["tune"], 0, 500)])    # VEL 1.0 x 50 % -> Tune +6 st
note_on(57, vel=1.0)
f = pitch(blocks(48))
check(f"VEL -> Tune (+50 % at full velocity = +6 semitones): {f:.1f} Hz", abs(cents(f, 220 * 2 ** 0.5)) < 1.0, f)
record(on=1, wave=0, level=1000, routes=[(SRC_VEL, OSC["level"], 0, -500)])  # VEL 1.0 x -50 % -> Level 50 %
note_on(57, vel=1.0)
pk = np.abs(blocks(16)[N:]).max()
check(f"VEL -> Level (-50 %): Level 50 %, sine peak 0.5 ({pk:.4f})", abs(pk - 0.5) < 0.006, pk)

# --- Pulse W is a modulation destination; Wave is not
def duty_of(**kw):
    record(on=1, wave=1, level=1000, **kw)
    note_on(45, vel=1.0)
    y = blocks(32)[N:]
    return float(np.mean(y > 0.0))


d1 = duty_of(routes=[(SRC_VEL, OSC["pw"], 0, 500)])                       # VEL 1.0 x 50 %: +22.5 %
d2 = duty_of(pw=1000, routes=[(SRC_VEL, OSC["pw"], s, 1000) for s in range(3)])   # 95 % + more: past the top
d3 = duty_of(pw=-1000, routes=[(SRC_VEL, OSC["pw"], s, -1000) for s in range(3)])  # 5 % - more: past the bottom
check(f"VEL -> Pulse W: +50 % -> {d1 * 100:.1f} % high (want 72.5 %); stacked past the ends: {d2 * 100:.1f} % / "
      f"{d3 * 100:.1f} % (3 .. 97 %)", abs(d1 - 0.725) < 0.01 and abs(d2 - 0.97) < 0.01 and abs(d3 - 0.03) < 0.01,
      (d1, d2, d3))
check("a route to Wave changes nothing (Wave is not a modulation destination)",
      np.array_equal(wave_out(0), wave_out(0, routes=[(SRC_VEL, OSC["wave"], 0, 1000)])))

# --- the stored OSC/MOD setting is ignored: a preset saved with OSC modulates exactly as one saved with MOD
rt = [(SRC_OSC, P_FILTER, 0, 300), (SRC_OSC, P_LEVEL, 0, 1000)]
record(on=1, mode=0, wave=0, level=500, routes=rt, probe=False)
note_on(57, filt=knob_for(1000), res=0.7)
y0 = blocks(16, x)
record(on=1, mode=1, wave=0, level=500, routes=rt, probe=False)
note_on(57, filt=knob_for(1000), res=0.7)
y1 = blocks(16, x)
check("a stored OSC/MOD of OSC (a preset from before) modulates Filter and Level exactly as MOD",
      np.abs(y1 - y0).max() == 0.0 and np.abs(y0 - ref[:len(y0)] if len(ref) >= len(y0) else y0).max() > 0.01,
      np.abs(y1 - y0).max())

# --- a new note starts the cycle from 0
record(on=1, wave=0, level=1000)
note_on(57)
a = blocks(1)
blocks(3)
note_on(57)
b = blocks(1)
check("note start: the oscillator's cycle starts again (first block identical)", np.abs(a - b).max() == 0.0,
      np.abs(a - b).max())

# --- the voice's own chain (the stock closing routine FUN_08055bb8, run for real): the oscillator on and routed, a
# silent sample: nothing comes out (3.1.v1: the oscillator is never heard)
ENV, ENVP = VOICE + 0x28, 0x2407F000                 # amp envelope object, its settings (+0x18 = Sustain level)
e.stub(0x08063790, value=1)                          # the sample's channel count query: stereo
e.stub(0x0804DA6C)                                   # the bus mix after it: not needed here
e.uc.mem_write(PAD + 0x100, bytes(0x500))            # pad flags the routine reads (+0x108, +0x114, +0x550, +0x574)
e.uc.mem_write(PAD + 0x5A8, struct.pack("<f", 1.0))  # pad gain
record(on=1, wave=1, level=1000, routes=[(SRC_OSC, P_FILTER, 0, 300)])
note_on(57)
values[VOICE + 0x150] = 1.0
e.uc.mem_write(ENVP, bytes(0x40))
e.uc.mem_write(ENVP + 0x18, struct.pack("<f", 1.0))
e.uc.mem_write(ENV, bytes(0x40))
e.uc.mem_write(ENV + 4, bytes([3]))
e.w32(ENV + 8, ENVP)
e.uc.mem_write(ENV + 0x1C, struct.pack("<f", 1.0))
for ramp in (0x94, 0x64, 0x74):
    e.uc.mem_write(VOICE + ramp, struct.pack("<ffff", 1.0, 0.0, 1.0, 0.0))
out = []
for b in range(6):
    e.uc.mem_write(LBUF, bytes(4 * N))
    e.uc.mem_write(RBUF, bytes(4 * N))
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, RBUF, 0, 1))
    e.call(0x08055BB8, PAD, VOICE, BUF, BUF)
    out += struct.unpack(f"<{N}f", e.uc.mem_read(LBUF, 4 * N))
values[VOICE + 0x150] = 0.0
check(f"stock voice routine, silent sample, oscillator on (square, Level 100 %, OSC -> Filter and Level): silent "
      f"(peak {np.abs(out).max():.1e})", np.abs(out).max() == 0.0, np.abs(out).max())
check("the stock filter call after the envelope is gone (0x08055c60: two nops)", e.r16(0x08055C60) == 0xBF00 and e.r16(0x08055C62) == 0xBF00)

print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
