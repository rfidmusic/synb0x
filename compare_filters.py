"""Sine-sweep comparison of a combined build's filters with the builds they came from, under Unicorn.

usage: compare_filters.py <combined build dir> <SEM build dir> <Polivoks build dir>   (Filter Type 0 SEM, 1 Polivoks)
Each build dir holds out/cave.elf and out/<patchsets>/BLACKBOX.bin. A logarithmic sine sweep (20 Hz .. 20 kHz) runs through
filter_process of both builds, stereo, block by block, for every setting in the grid (cutoff, Res up to
self-oscillation, Morph, drive by input level, and Morph moving every block). The combined build's pads carry the
Filter Type (param 0x1ef, stored after LFO Mode); the original builds ignore that entry. Reported per model: the largest
sample difference and the difference's level against the output, and how many settings are bit-identical.
"""
import math
import struct
import sys

import numpy as np
from unicorn.arm_const import UC_ARM_REG_S0

from emu import Emu

IMG = "out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+cave/BLACKBOX.bin"
OBJ, PARAMS, PAD, BUF, LBUF, RBUF, AMP = 0x24060000, 0x24061000, 0x24062000, 0x24063000, 0x24064000, 0x24066000, 0x24068000
APP_PADS, ARR = 0x24020088 + 0x1840, 0x24073000
N, FS = 256, 48000.0
BLOCKS = 188                                          # 1 s


class Build:
    def __init__(self, root, model=None):
        self.e = Emu(f"{root}/{IMG}", f"{root}/out/cave.elf")
        self.vals = {}
        self.model = model
        self.e.stub(0x0806FB30, self.param)
        self.e.w32(OBJ + 0x84, PARAMS)

    def param(self):
        v = self.vals.get(self.e.arg(0), 0.0)
        self.e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", v))[0])

    def pad(self, morph):
        ent = [(0x8B, 0), (0xF1, 0), (0xDB, 0), (0x1E9, morph), (0x1E1, 0), (0x1E2, 0), (0x1E3, 300), (0x1E4, 0),
               (0x1EB, 300), (0x1E6, 0), (0x1EC, 0), (0x1ED, 300), (0x1EE, 0)]
        if self.model is not None:
            ent.append((0x1EF, self.model))
        e = self.e
        store = APP_PADS + 1 * 0xF0 + 2 * 0x30
        e.uc.mem_write(ARR, b"".join(struct.pack("<HHi", i, 0, v) for i, v in ent))
        e.w32(store + 4, ARR)
        e.uc.mem_write(store + 10, struct.pack("<H", len(ent)))
        e.w32(store + 0x10, 0)
        e.uc.mem_write(store + 0x14, struct.pack("<H", 0))

    def run(self, knob, res, morph, x, morph_moving=False):
        e = self.e
        e.uc.mem_write(OBJ + 4, b"\xa5" * 0x30)       # stale state, then a voice start
        e.uc.mem_write(OBJ + 0x40, bytes(0x20))
        e.uc.mem_write(AMP, bytes([3]))
        e.w32(PAD + 0x18, 1 << 8 | 2)
        self.vals[PARAMS + 8], self.vals[PARAMS + 0x44] = knob, res
        out_l, out_r = [], []
        for b in range(len(x) // N):
            m = int(500 + 500 * math.sin(b / 6)) if morph_moving else morph
            self.pad(m)
            blk = x[b * N:(b + 1) * N]
            e.uc.mem_write(LBUF, struct.pack(f"<{N}f", *blk))
            e.uc.mem_write(RBUF, struct.pack(f"<{N}f", *(-blk)))
            e.uc.mem_write(BUF, struct.pack("<IIIIBB", N, N, LBUF, RBUF, 0, 1))
            e.call("filter_process", OBJ, BUF, PAD, AMP)
            out_l += struct.unpack(f"<{N}f", e.uc.mem_read(LBUF, 4 * N))
            out_r += struct.unpack(f"<{N}f", e.uc.mem_read(RBUF, 4 * N))
        return np.array(out_l + out_r, dtype=np.float64)


def knob_for(hz):
    return 2 * math.log2(hz / 20) / 10 - 1


t = np.arange(BLOCKS * N) / FS
T = BLOCKS * N / FS
sweep = np.sin(2 * np.pi * 20 * T / math.log(1000) * (np.exp(t / T * math.log(1000)) - 1))   # 20 Hz -> 20 kHz
grid = [(hz, res, morph, amp, False) for hz in (300, 2000) for res in (0.0, 0.5, 0.9, 1.0)
        for morph in (0, 500, 1000) for amp in (0.25, 0.9)]
grid += [(1000, res, 0, 0.5, True) for res in (0.3, 0.97)]

combined = sys.argv[1]
for label, model, orig in (("SEM", 0, sys.argv[2]), ("Polivoks", 1, sys.argv[3])):
    a, b = Build(combined, model), Build(orig)
    worst_abs, worst_db, same, rows = 0.0, -999.0, 0, []
    for hz, res, morph, amp, moving in grid:
        x = (amp * sweep).astype(np.float32)
        ya = a.run(knob_for(hz), res, morph, x, moving)
        yb = b.run(knob_for(hz), res, morph, x, moving)
        d = ya - yb
        dmax = float(np.abs(d).max())
        ref = float(np.sqrt(np.mean(yb ** 2))) or 1e-30
        ddb = 20 * math.log10(float(np.sqrt(np.mean(d ** 2))) / ref) if dmax > 0 else -math.inf
        same += dmax == 0.0
        worst_abs = max(worst_abs, dmax)
        worst_db = max(worst_db, ddb)
        rows.append((hz, res, morph, amp, moving, dmax, ddb))
    print(f"{label:9} vs its own build: {same} of {len(grid)} settings bit-identical; largest sample difference "
          f"{worst_abs:.3g}; difference level at most {worst_db:.1f} dB below the output")
    for r in rows:
        if r[5] > 0:
            print(f"    cutoff {r[0]} Hz, Res {r[1]}, Morph {r[2]}, level {r[3]}{', Morph moving' if r[4] else ''}: "
                  f"max {r[5]:.3g}, {r[6]:.1f} dB")
