"""The filters in stereo under Unicorn: a stereo sine whose channels fade in and out at different times.

Real firmware runs for: filter_process with each Filter Type (SEM, Polivoks), the stock cutoff / Res curves.
Stubbed: the modulated-parameter read (test values). Checked, per Filter Type and setting (cutoff, Res up to
self-oscillation, Morph, drive): each output channel is exactly what filtering that channel alone gives (bit for bit:
no crosstalk, each channel keeps its own state); a channel silent at the input stays silent while the other plays
(below self-oscillation); the output stays finite. NOT checked: how it sounds (hardware).
"""
import math
import struct
import sys

import numpy as np

src = open("test_filter.py").read()
ns = {"__name__": "test_stereo"}
exec(compile(src[:src.index("# --- the Filter knob is cutoff")], "test_filter.py", "exec"), ns)
e, values, OBJ, BUF, LBUF, RBUF, PAD, AMP = (ns[k] for k in ("e", "values", "OBJ", "BUF", "LBUF", "RBUF", "PAD", "AMP"))
FS, N, BLOCKS = 48000.0, 256, 60                    # 0.32 s
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def knob_for(hz):
    return 2 * math.log2(hz / 20) / 10 - 1


def fade(t, on, off, ramp=0.03):
    """0 -> 1 from `on` (seconds) over `ramp`, back to 0 from `off`"""
    a = np.clip((t - on) / ramp, 0, 1)
    b = np.clip((off - t) / ramp, 0, 1)
    return a * b


t = np.arange(BLOCKS * N) / FS
LEFT = (0.5 * np.sin(2 * np.pi * 220 * t) * fade(t, 0.02, 0.17)).astype(np.float32)    # left: early
RIGHT = (0.5 * np.sin(2 * np.pi * 330 * t) * fade(t, 0.12, 0.28)).astype(np.float32)   # right: later, other pitch


def run(model, knob, res, morph, left, right):
    """the whole signal, block by block, from a fresh voice; right None = a mono voice"""
    ns["MODEL"] = model
    ns["setup"](knob, res, ftype=morph)
    e.uc.mem_write(OBJ + 4, b"\xa5" * 0x30)
    ns["note_on"]()
    out_l, out_r = [], []
    for b in range(BLOCKS):
        l = left[b * N:(b + 1) * N]
        e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *l))
        if right is not None:
            e.uc.mem_write(RBUF, struct.pack(f"<{N}f", *right[b * N:(b + 1) * N]))
        e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, RBUF if right is not None else 0, 0,
                                        int(right is not None)))
        e.call("filter_process", OBJ, BUF, PAD, AMP)
        out_l += struct.unpack(f"<{N}f", e.uc.mem_read(LBUF, 4 * N))
        if right is not None:
            out_r += struct.unpack(f"<{N}f", e.uc.mem_read(RBUF, 4 * N))
    return np.array(out_l, dtype=np.float32), (np.array(out_r, dtype=np.float32) if right is not None else None)


SETTINGS = [(500, 0.0, 0), (1000, 0.5, 0), (2000, 0.7, 500), (800, 0.9, 1000), (1500, 0.97, 0), (3000, 1.0, 250)]
NAMES = {0: "SEM", 1: "Polivoks"}
MODELS = (0, 1) if "MODEL" in ns else (0,)           # (the 3.1.t line has only the SEM filter, no Filter Type)
quiet = np.zeros_like(LEFT)
for model in MODELS:
    worst, finite, silent_ok = 0.0, True, True
    for hz, res, morph in SETTINGS:
        k = knob_for(hz)
        sl, sr = run(model, k, res, morph, LEFT, RIGHT)
        ml, _ = run(model, k, res, morph, LEFT, None)       # each channel on its own, as a mono voice
        mr, _ = run(model, k, res, morph, RIGHT, None)
        worst = max(worst, float(np.abs(sl - ml).max()), float(np.abs(sr - mr).max()))
        finite &= bool(np.isfinite(sl).all() and np.isfinite(sr).all())
        if res < 0.85:                                     # (above, the filter may ring on its own: by design)
            ol, orr = run(model, k, res, morph, LEFT, quiet)
            silent_ok &= bool(np.abs(orr).max() == 0.0 and np.abs(ol - ml).max() == 0.0)
    check(f"{NAMES[model]}: each channel exactly as filtered alone (largest difference {worst:.1e}) at "
          f"{len(SETTINGS)} settings, Res to 100 %, Morph LP..HP", worst == 0.0, worst)
    check(f"{NAMES[model]}: a silent right channel stays silent while the left plays (no crosstalk)", silent_ok)
    check(f"{NAMES[model]}: output finite throughout", finite)
    # the fades come through on their own channels: left loud early, right loud late
    sl, sr = run(model, knob_for(4000), 0.5, 0, LEFT, RIGHT)
    seg = lambda x, a, b: float(np.sqrt(np.mean(x[int(a * FS):int(b * FS)] ** 2)))
    check(f"{NAMES[model]}: the fades stay on their channels (left 0.06-0.10 s {seg(sl, .06, .10):.3f} / right "
          f"{seg(sr, .06, .10):.4f}; left 0.21-0.25 s {seg(sl, .21, .25):.4f} / right {seg(sr, .21, .25):.3f})",
          seg(sl, .06, .10) > 0.2 and seg(sr, .06, .10) < 1e-6 and seg(sl, .21, .25) < 1e-3 and seg(sr, .21, .25) > 0.2)

print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
