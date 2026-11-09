"""CPU per voice: stock 3.1.9 against this build, under Unicorn, both running their own real code for the same voices.

Per sample-pad voice and 256-frame block, in each firmware: the LFO update (stock FUN_0806f108; here lfo_update_a, with
the AD envelope), the sample reader's Normal kernel (stock FUN_080619d0; here read_normal), and the voice's closing
routine FUN_08055bb8 (Level, Pan, amp envelope, the filter, the mix into the pad bus; here the filter, with Fidelity
and the oscillator, runs first). The same random voices (cutoff, Res, Level, Pan, amp envelope stage and Sustain,
pitch) go through both; this build adds its own settings per scenario (Filter Type, oscillator, routes, Fidelity).
NOT counted, in either: the stock parameter reads (FUN_0806fb30, stubbed: in the firmware they also evaluate each
parameter's modulation), master effects, mixer, sequencer, screen. Cycles = instructions + 13 x divisions.
usage: cpu_vs_stock.py [voices per scenario]
"""
import math
import random
import struct
import sys

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from unicorn import UC_HOOK_BLOCK
from unicorn.arm_const import UC_ARM_REG_S0

from emu import STACK, Emu

STOCK = "firmware/BLACKBOX-3.1.9.bin"
MOD = "out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+cave/BLACKBOX.bin"
ELF = "out/cave.elf"
SAMPLES = int(sys.argv[1]) if len(sys.argv) > 1 else 24
N, FS = 256, 48000.0
VOICE = 0x24074000                                    # sample voice: filter object + 0xa8, amp envelope + 0x28
OBJ, ENV, LFO = VOICE + 0xA8, VOICE + 0x28, VOICE + 0x4E8
PARAMS, PAD = 0x24061000, 0x24062000
BUF, LBUF, RBUF = 0x24063000, 0x24064000, 0x24066000
BUS, BL, BR = 0x24063100, 0x24068000, 0x24068800
ENVP, COEF = 0x2407E000, 0x2407E100
SRC, DST, NEWPOS, FRAC = 0x24078000, 0x2407B000, 0x2407C000, 0x2407C010
APP_PADS, ARR = 0x24020088 + 0x1840, 0x24073000
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
SOURCES = [0x0D, 0x0E, 0x04, 0x19, 0x1A, 0x1C, 0x1D, 1, 2]


class Bench:
    def __init__(self, image, mod):
        self.e = e = Emu(image, ELF)
        self.mod, self.vals, self.blocks, self.n, self.div = mod, {}, {}, 0, 0
        e.uc.hook_add(UC_HOOK_BLOCK, self.hook)        # before anything runs (Unicorn caches translated code)
        e.stub(0x0806FB30, self.param)
        e.stub(0x08063790, value=1)                    # the sample's channel count: stereo
        e.stub(0x080636F0, value=1 << 24)              # its length (asked in Release, for the voice's end): long
        self.lfo_real = True
        try:
            e.uc.mem_write(LFO, bytes(0x40))
            e.call("lfo_update_a" if mod else 0x0806F108, LFO, N)
        except Exception:
            self.lfo_real = False
            e.stub(0x0806F108)

    def hook(self, uc, addr, size, _):
        b = self.blocks.get((addr, size))
        if b is None:
            ins = list(md.disasm(bytes(uc.mem_read(addr, size)), addr))
            b = self.blocks[(addr, size)] = (len(ins), sum(i.mnemonic.startswith(("vdiv", "vsqrt")) for i in ins))
        self.n += b[0]
        self.div += b[1]

    def param(self):
        v = self.vals.get(self.e.arg(0), 0.0)
        self.e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", v))[0])

    def record(self, v, sc):
        """this build's pad record (sample pad, row 1 col 2): Fidelity, Filter Type, oscillator, routes"""
        e = self.e
        osc = sc.get("osc")
        ent = [(0x8B, 0), (0xF1, sc.get("interp", 0)), (0xDB, 0), (0x1E9, v["morph"]), (0x1E1, 0), (0x1E2, 0),
               (0x1E3, 300), (0x1E4, 0), (0x1EB, 300), (0x1E6, 0), (0x1EC, 0), (0x1ED, 300), (0x1EE, 0),
               (0x1EF, sc.get("model", 0))]
        ent += list(zip((0x1F0, 0x1F1, 0x1F2, 0x1F3, 0x1DC, 0x1DD, 0x1DE, 0x1DF, 0x1E0),
                        osc or (0, 0, 0, 700, 3, 500, 0, 0, 1)))
        store = APP_PADS + 1 * 0xF0 + 2 * 0x30
        e.uc.mem_write(ARR, b"".join(struct.pack("<HHi", i, 0, x) for i, x in ent))
        e.w32(store + 4, ARR)
        e.uc.mem_write(store + 10, struct.pack("<H", len(ent)))
        routes = sc.get("routes", [])
        e.uc.mem_write(ARR + 0x400, b"".join(struct.pack("<hHHHHH", a, 0, s, d, sl, 0) for s, d, sl, a in routes))
        e.w32(store + 0x10, ARR + 0x400 if routes else 0)
        e.uc.mem_write(store + 0x14, struct.pack("<H", len(routes)))

    def voice(self, v, sc):
        """one voice: cycles per block (mean of 4 after 4 to settle) and whether its output stays finite"""
        e = self.e
        self.vals = {PARAMS + 8: v["knob"], PARAMS + 0x44: v["res"], VOICE + 0x150: v["level"],
                     VOICE + 0x184: v["pan"], VOICE + 0x288: 0.0}
        e.w32(PAD + 0x18, 1 << 8 | 2)
        e.uc.mem_write(PAD + 0x100, bytes(0x500))
        e.uc.mem_write(PAD + 0x5A8, struct.pack("<f", 1.0))
        if self.mod:
            self.record(v, sc)
        e.uc.mem_write(OBJ, bytes(0x94))                # voice start
        e.uc.mem_write(OBJ + 4, b"\xa5" * 0x30)
        e.w32(OBJ + 0x84, PARAMS)
        if not self.mod:                                # the stock filter: two coefficient sets, start, recompute
            e.uc.mem_write(OBJ, bytes([1]))
            e.w32(OBJ + 0x60, COEF)
            e.w32(OBJ + 0x64, COEF + 0x20)
            e.uc.mem_write(COEF, bytes(0x40))
            e.uc.mem_write(OBJ + 0x90, bytes([1]))
        e.uc.mem_write(VOICE + 0x88, struct.pack("<f", v["vel"]))
        e.uc.mem_write(VOICE + 0x90, struct.pack("<f", v["key"]))
        e.uc.mem_write(ENVP, bytes(0x40))
        e.uc.mem_write(ENVP + 0x18, struct.pack("<f", v["sustain"]))
        e.uc.mem_write(ENV, bytes(0x40))
        e.uc.mem_write(ENV + 4, bytes([v["stage"]]))
        e.w32(ENV + 8, ENVP)
        e.w32(ENV + 0x10, 1 << 20)                      # stage counters: a long stage
        e.w32(ENV + 0x14, 1 << 21)
        e.uc.mem_write(ENV + 0xC, struct.pack("<f", 1.0))
        e.uc.mem_write(LFO, bytes(0x40))
        for ramp in (0x94, 0x64, 0x74):
            e.uc.mem_write(VOICE + ramp, struct.pack("<ffff", 1.0, 0.0, 1.0, 0.0))
        rate = v["rate"]
        n_src = int(N * rate) + 16
        rng = random.Random(v["seed"])
        e.uc.mem_write(SRC, struct.pack(f"<{n_src}f", *[0.3 * math.sin(i * 0.05) + 0.2 * rng.uniform(-1, 1)
                                                         for i in range(n_src)]))
        e.uc.mem_write(BUS, struct.pack("<IIIIBB", N, N, BL, BR, 0, 1))
        total = [0, 0]
        ok = True
        for b in range(8):
            self.n = self.div = 0
            e.call("lfo_update_a" if self.mod else 0x0806F108, LFO, N)
            for ch in (LBUF, RBUF):                     # the reader, per channel
                e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", rate))[0])
                e.w32(FRAC, 0)
                e.uc.mem_write(STACK, struct.pack("<III", FRAC, ch, N))
                e.call("read_normal" if self.mod else 0x080619D0, SRC, n_src, 4, NEWPOS)
            e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, RBUF, 0, 1))
            e.call(0x08055BB8, PAD, VOICE, BUF, BUS)
            if b >= 4:
                total[0] += self.n
                total[1] += self.div
            out = struct.unpack(f"<{N}f", e.uc.mem_read(LBUF, 4 * N))
            ok &= all(x == x and abs(x) < 100 for x in out)
        return (total[0] + 13 * total[1]) / 4, ok


def voices(seed):
    rng = random.Random(seed)
    out = []
    for i in range(SAMPLES):
        k = rng.uniform(0.1, 0.9) * rng.choice((-1, 1))
        out.append(dict(knob=k, res=rng.choice((0.0, 0.3, 0.5, 0.7, 0.9, rng.random())), level=rng.uniform(0.7, 1.0),
                        pan=rng.uniform(-1, 1), vel=rng.random(), key=rng.uniform(-0.4, 0.4),
                        sustain=rng.uniform(0.2, 1.0), stage=rng.choice((2, 3, 4)), rate=rng.uniform(0.5, 2.0),
                        morph=0 if k < 0 else 1000, seed=i))
    return out


def stress(rng):
    """the earlier stress setting: oscillator on (random OSC / MOD), every own slot routed, random Fidelity, filter"""
    mod = rng.choice((0, 1))
    routes = [(src, d, sl, rng.choice((-1000, -500, 300, 700, 1000)))
              for d in (0x1E9, 0x1DF, 0x1F3, 0x1DD) for sl, src in enumerate(rng.sample(SOURCES, 3))]   # Morph, Pulse W, Level, Tune
    if mod:
        routes += [(3, d, sl, 300) for d in (200, 0x04) for sl in range(3)]
    return dict(model=rng.choice((0, 1)), interp=rng.choice(range(14)), routes=routes,
                osc=(1, mod, rng.randrange(4), rng.randrange(200, 1001), rng.randrange(7), rng.randrange(1001),
                     rng.randrange(-1000, 1001), rng.randrange(-1000, 1001), 1))


V = voices(1)
stock = Bench(STOCK, False)
mine = Bench(MOD, True)
ver = mine.e.cstr(mine.e.sym["mod_version"])
print(f"stock 3.1.9 vs this build ({ver}): {SAMPLES} random sample-pad voices, one 256-frame block each, both firmwares'"
      " own code (parameter reads stubbed in both)")
print(f"  LFO update run for real: stock {'yes' if stock.lfo_real else 'NO (stubbed)'}, "
      f"this build {'yes' if mine.lfo_real else 'NO (stubbed)'}\n")
base = [stock.voice(v, {}) for v in V]
base_mean = sum(c for c, _ in base) / len(base)
rows = [("stock 3.1.9 (its 12 dB biquad)", base_mean, all(ok for _, ok in base))]
srng = random.Random(5)
for label, sc in (("Filter Type SEM, oscillator off", dict(model=0)),
                  ("Filter Type Polivoks, oscillator off", dict(model=1)),
                  ("SEM + oscillator (OSC, square)", dict(model=0, osc=(1, 0, 1, 700, 3, 500, 0, 0, 1))),
                  ("stress: oscillator on, every slot routed, random", None)):
    res = [mine.voice(v, sc if sc is not None else stress(srng)) for v in V]
    rows.append((label, sum(c for c, _ in res) / len(res), all(ok for _, ok in res)))
print(f"  {'':52} {'cycles/voice':>12} {'vs stock':>9} {'voices @480 MHz':>16} {'@400 MHz':>9}")
for label, c, ok in rows:
    print(f"  {label:52} {c:12,.0f} {c / base_mean:8.2f}x {2.56e6 / c:16.0f} {2.1333e6 / c:9.0f}"
          + ("" if ok else "   (output NOT finite)"))
print("\n  voices = the whole 5.33 ms block budget spent on voices alone (no master effects, mixer, screen): an upper"
      " bound, for comparing the two firmwares, not a device figure.")
