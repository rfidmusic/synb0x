"""CPU stress test with the oscillator (3.1.ul) under Unicorn: add voices until one audio block's cycle budget runs out.

Every pad a Sample pad in Poly X (16 voices each, 256 slots), every voice with the oscillator ON and every modulation
slot used, each from a random source:
  routes this firmware applies itself (run for real in filter_process): Morph, Pulse W, Osc Level, Tune (3 slots each,
  random sources: VEL, KEY, LFO, pitch bend, mod wheel, MIDI volume, MIDI pan, FENV, AD) and, in MOD mode, OSC -> Filter
  and OSC -> Level (3 slots each, source OSC; in OSC mode those slots get random sources, evaluated by stock code)
  routes the stock code evaluates (ESTIMATED, see EST): the other 23 destinations x 3 slots.
Random per voice: OSC or MOD, Wave (one of four), Octave, Tune, Fine, Pulse W, Filter Type
(SEM / Polivoks), Fidelity (Normal, HighQ, crunches, machine modes), Filter, Res (up to self-oscillation),
Morph, filter envelope, AD, LFO Mode, Saturation, pitch (the sample reader always resamples).
Runs for real, from the build in out/: per voice the LFO / AD update, the sample reader's kernel, filter_process (Fidelity,
glide, envelopes, the oscillator, the filter, Morph / oscillator routes), the stock gain ramp and bus mix; per pad
Saturation (od_process); master the Munchi granular delay (the compressor models and Room are not in this build).
NOT run: the stock route evaluation and voice bookkeeping (EST), the stock mixer / sequencer / Plate reverb / delay /
codec, the screen task. Cycles = instructions + 13 x divisions; real cycles also depend on memory waits (SDRAM
samples): read the on-screen CPU meter for the device's real load.
usage: stress_osc.py [seed] [random voices] [off]
"""
import collections
import math
import random
import struct
import sys

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from emu import STACK
from unicorn import UC_HOOK_BLOCK
from unicorn.arm_const import UC_ARM_REG_S0, UC_ARM_REG_S1

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 1
SAMPLES = int(sys.argv[2]) if len(sys.argv) > 2 else 48
OSC_OFF = len(sys.argv) > 3 and sys.argv[3] == "off"      # the same voices with the oscillator off, for comparison
FRAMES = 256                                          # one voice block: 5.33 ms at 48 kHz
STOCK_DESTS = 23                                      # the stock modulation destinations (filt_tab.c's list, unique)
EST = {f"stock route evaluation, {STOCK_DESTS} destinations x 3 slots at ~40 each": STOCK_DESTS * 3 * 40,
       "stock voice bookkeeping (envelope stage, pitch, pan law)": 600}
CLOCKS = (480e6, 400e6)                               # STM32H743: 480 MHz (rev V), 400 MHz (rev Y)
VOICES_MAX = 256                                      # 16 pads x 16 voice slots (Poly X)


def load(test, until):
    src = open(test).read()
    ns = {"__name__": "stress"}
    exec(compile(src[:src.index(until)], test, "exec"), ns)
    return ns


md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


class Counter:
    """instructions and divisions executed, counted per basic block (hooked before anything runs)"""
    def __init__(self, e):
        self.e, self.blocks, self.n, self.div = e, {}, 0, 0
        e.uc.hook_add(UC_HOOK_BLOCK, self.hook)

    def hook(self, uc, addr, size, _):
        b = self.blocks.get((addr, size))
        if b is None:
            ins = list(md.disasm(bytes(uc.mem_read(addr, size)), addr))
            b = self.blocks[(addr, size)] = (len(ins), sum(i.mnemonic.startswith(("vdiv", "vsqrt")) for i in ins))
        self.n += b[0]
        self.div += b[1]

    def measure(self, fn):
        self.n = self.div = 0
        fn()
        return self.n, self.div


def cycles(n, d):
    return n + 13 * d


# --- per voice, in test_filter's harness
F = load("test_filter.py", "# --- the Filter knob is cutoff")
e = F["e"]
cnt = Counter(e)
SOURCES = [0x0D, 0x0E, 0x04, 0x19, 0x1A, 0x1C, 0x1D, 1, 2]      # all but MIDI CC (0x8000)
SRC_OSC = 3
VOICE = 0x24074000                                    # a sample voice: LFO at +0x4e8, filter object at +0xa8
VOBJ, LFO = VOICE + 0xA8, VOICE + 0x4E8
SRC, DST, NEWPOS, FRAC = 0x24078000, 0x2407B000, 0x2407C000, 0x2407C010
BUS = 0x2407C800
REC, RREC = 0x24070000, 0x24070400                    # the pad record's entries and routes
P_FILTER, P_LEVEL, P_FMORPH = 200, 0x04, 0x1E9
P_PW, P_OLEVEL, P_TUNE = 0x1DF, 0x1F3, 0x1DD


def record(rng, interp, sat, morph, fenv, ad, model, osc, routes):
    """the pad's record as the defaults lay it out (..., AD pair, LFO Mode, Filter Type, oscillator, Osc Track)"""
    ent = [(0x8B, 0), (0xF1, interp), (0xDB, sat), (P_FMORPH, morph), (0x1E1, 0), (0x1E2, fenv[0]), (0x1E3, fenv[1]),
           (0x1E4, fenv[2]), (0x1EB, fenv[3]), (0x1E6, fenv[4]), (0x1EC, ad[0]), (0x1ED, ad[1]), (0x1EE, ad[2]),
           (0x1EF, model)]
    ent += list(zip((0x1F0, 0x1F1, 0x1F2, 0x1F3, 0x1DC, 0x1DD, 0x1DE, 0x1DF, 0x1E0), osc))
    store = F["APP_PADS"] + F["PAD_ROW"] * 0xF0 + F["PAD_COL"] * 0x30
    e.uc.mem_write(REC, b"".join(struct.pack("<HHi", i, 0, v) for i, v in ent))
    e.w32(store + 4, REC)
    e.uc.mem_write(store + 10, struct.pack("<H", len(ent)))
    e.uc.mem_write(RREC, b"".join(struct.pack("<hHHHHH", amt, 0, s, d, slot, 0) for s, d, slot, amt in routes))
    e.w32(store + 0x10, RREC)
    e.uc.mem_write(store + 0x14, struct.pack("<H", len(routes)))


def amount(rng):
    return rng.choice((-1000, -500, 300, 700, 1000))


def voice_cost(rng):
    interp = rng.choice(range(14))                    # Normal, HighQ, SP1200 .. SP Raw, 16k .. 2k
    model = rng.choice((0, 1))
    mod = rng.choice((0, 1))
    osc = (0 if OSC_OFF else 1, mod, rng.randrange(4), rng.randrange(200, 1001), rng.randrange(7), rng.randrange(1001),
           rng.randrange(-1000, 1001), rng.randrange(-1000, 1001), rng.choice((0, 1)))
    routes = []
    for dest in (P_FMORPH, P_PW, P_OLEVEL, P_TUNE):
        routes += [(src, dest, slot, amount(rng)) for slot, src in enumerate(rng.sample(SOURCES, 3))]
    for dest in (P_FILTER, P_LEVEL):                  # MOD: from OSC; OSC mode: random sources (stock evaluates them)
        routes += [((SRC_OSC if mod else rng.choice(SOURCES)), dest, slot, amount(rng) // 3) for slot in range(3)]
    rng.shuffle(routes)
    res = rng.choice((0.0, 0.5, 0.7, 0.9, 0.95, 1.0, rng.random()))
    knob = rng.uniform(-0.9, 0.95)
    record(rng, interp, rng.randrange(0, 1001), rng.choice((0, 250, 500, 750, 1000, rng.randrange(1001))),
           (rng.randrange(0, 600), rng.randrange(0, 800), rng.randrange(0, 1001), rng.randrange(0, 800),
            rng.randrange(-1000, 1001)), (rng.randrange(0, 600), rng.randrange(0, 800), rng.choice((0, 1))), model, osc,
           routes)
    F["values"][F["PARAMS"] + 8], F["values"][F["PARAMS"] + 0x44] = knob, res
    e.w32(F["PAD"] + 0x18, F["PAD_ROW"] << 8 | F["PAD_COL"])
    rate = rng.uniform(0.5, 2.0)
    e.uc.mem_write(VOBJ + 0x40, bytes(0x20))          # voice start
    e.uc.mem_write(VOBJ + 4, b"\xa5" * 0x30)
    e.w32(VOBJ + 0x84, F["PARAMS"])
    e.uc.mem_write(VOBJ - 0x7C, bytes([1]))
    for k, v in ((0x88, rng.random()), (0x90, rng.uniform(-0.5, 0.5)), (0x524, rng.uniform(-1, 1))):
        e.uc.mem_write(VOICE + k, struct.pack("<f", v))   # VEL, KEY, LFO values
    n_src = int(FRAMES * rate) + 16
    e.uc.mem_write(SRC, struct.pack(f"<{n_src}f", *[0.3 * math.sin(i * 0.05) + 0.2 * rng.uniform(-1, 1) for i in range(n_src)]))
    PARK = 0x2405FFF4
    e.w32(PARK, F["PAD"])
    e.w32(PARK + 4, 1000)
    e.uc.mem_write(PARK + 8, struct.pack("<f", rate))

    def read():
        e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", rate))[0])
        e.w32(FRAC, 0)
        e.uc.mem_write(STACK, struct.pack("<III", FRAC, DST, FRAMES))
        e.call("read_hq", SRC, n_src, 4, NEWPOS)

    parts = collections.Counter()

    def part(name, fn):
        n0, d0 = cnt.n, cnt.div
        fn()
        parts[name] += cnt.n - n0 + 13 * (cnt.div - d0)

    def block(b):
        x = [0.4 * math.sin(2 * math.pi * 110 * (b * FRAMES + i) / 48000) for i in range(FRAMES)]
        e.uc.mem_write(F["LBUF"], struct.pack(f"<{FRAMES}f", *x))
        e.uc.mem_write(F["RBUF"], struct.pack(f"<{FRAMES}f", *x))
        e.uc.mem_write(F["BUF"], struct.pack("<IIIIBB", FRAMES, FRAMES, F["LBUF"], F["RBUF"], 0, 1))
        part("LFO + AD update", lambda: e.call("lfo_update_a", LFO, FRAMES))
        part("sample reader (resampling, 2 ch)", lambda: (read(), read()))
        part("filter_process (Fidelity, envelopes, oscillator, filter, routes)",
             lambda: e.call("filter_process", VOBJ, F["BUF"], F["PAD"], VOBJ - 0x7C))
        e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", 0.8))[0])
        e.uc.reg_write(UC_ARM_REG_S1, struct.unpack("<I", struct.pack("<f", 0.7))[0])
        part("stock gain ramp (amp x pan)", lambda: e.call(0x0805FC38, F["LBUF"], F["RBUF"], FRAMES))
        part("stock bus mix (2 ch)", lambda: (e.call(0x080617C0, F["LBUF"], FRAMES, BUS),
                                              e.call(0x080617C0, F["RBUF"], FRAMES, BUS + 0x400)))
        out = struct.unpack(f"<{FRAMES}f", e.uc.mem_read(F["LBUF"], 4 * FRAMES))
        return all(v == v and abs(v) < 100 for v in out)

    for b in range(6):
        block(b)
    e.uc.mem_write(VOBJ - 0x7C, bytes([2]))           # decay: envelopes moving
    ok, n, d = True, 0, 0
    parts.clear()
    for b in range(6, 10):
        cnt.n = cnt.div = 0
        ok &= block(b)
        n += cnt.n
        d += cnt.div
    PARTS.append({k: v / 4 for k, v in parts.items()})
    return cycles(n, d) / 4 + sum(EST.values()), ok, dict(model=model, mod=mod, wave=osc[2], interp=interp)


PARTS = []
rng = random.Random(SEED)
voices = [voice_cost(rng) for _ in range(SAMPLES)]

# --- per pad: Saturation (test_od's harness)
O = load("test_od.py", "def sine(")
co = Counter(O["e"])
pad_c = 0
for drive in (0.25, 0.5, 1.0):
    O["setup"](drive)
    x = [0.5 * math.sin(i * 0.03) for i in range(FRAMES)]
    O["run"](x, x)
    pad_c = max(pad_c, cycles(*co.measure(lambda: O["run"](x, x))))

# --- master: Munchi granular delay (test_munchi's harness)
M = load("test_munchi.py", "\nrun.t = 0")
cm = Counter(M["e"])
noise = lambda i: (0.3 * math.sin(i * 0.013) + 0.1 * random.Random(i).uniform(-1, 1),) * 2
M["store"](type=1, wand=800, random=600, fb=500, freeze=0, clock=0, width=1000, duck=0)
for b in range(40):
    M["block"]([noise(b * 128 + i) for i in range(128)])
master_c = 2 * max(cycles(*cm.measure(lambda: M["block"]([noise(i) for i in range(128)]))) for _ in range(4))

vc = sorted(v for v, _, _ in voices)
mean_v = sum(vc) / len(vc)
by = lambda key, val: [v for v, _, c in voices if c[key] == val]
print(f"build: {e.cstr(e.sym['mod_version'])}   seed {SEED}, {SAMPLES} random voices, all with the oscillator on and "
      f"every modulation slot routed" + ("   (OSCILLATOR OFF: comparison)" if OSC_OFF else ""))
print("\nper voice, one 256-frame block (stereo):")
for name, v in (("min", vc[0]), ("median", vc[len(vc) // 2]), ("mean", mean_v), ("max", vc[-1])):
    print(f"  {name:7} {v:9,.0f} cycles  ({v / 2.56e6 * 100:.2f} % of a 480 MHz block)")
for key, vals in (("mod", ((0, "OSC mode"), (1, "MOD mode (OSC -> Filter, Level)"))),
                  ("model", ((0, "SEM filter"), (1, "Polivoks filter")))):
    for val, label in vals:
        g = by(key, val)
        if g:
            print(f"    {label:34} mean {sum(g) / len(g):9,.0f}  max {max(g):9,.0f}  ({len(g)} voices)")
print(f"  of which estimated (stock code not run): {sum(EST.values()):,} ({'; '.join(EST)})")
for k in PARTS[0]:
    vals = sorted(p[k] for p in PARTS)
    print(f"    {k:66} mean {sum(vals) / len(vals):8,.0f}   max {vals[-1]:8,.0f}")
print(f"  every voice finite and bounded: {'yes' if all(ok for _, ok, _ in voices) else 'NO'}")
print(f"per pad, Saturation: {pad_c:,} cycles;  master, Munchi: {master_c:,} cycles")

print("\nvoices before 100 % (16 Sample pads in Poly X = up to 256 voices, Saturation on every pad, random voices):")
for clock in CLOCKS:
    budget = clock * FRAMES / 48000
    rr = random.Random(SEED + 7)
    total, v, pads, marks = master_c, 0, set(), {}
    while v < VOICES_MAX:
        cost = voices[rr.randrange(len(voices))][0]
        add = cost + (pad_c if v % 16 not in pads else 0)
        if total + add > budget:
            break
        total += add
        pads.add(v % 16)
        v += 1
        for frac in (0.5, 0.8):
            if total > frac * budget and frac not in marks:
                marks[frac] = v
    worst = int((budget - master_c - 16 * pad_c) // vc[-1])
    mean_fit = int((budget - master_c - 16 * pad_c) // mean_v)
    print(f"  {clock / 1e6:.0f} MHz ({budget / 1e6:.2f} M cycles per block): {v} voices (random mix; 50 % load at "
          f"{marks.get(0.5, '-')}, 80 % at {marks.get(0.8, '-')});  all average voices {mean_fit}, all worst-case {worst}")
