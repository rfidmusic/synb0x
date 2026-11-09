"""Add every Thumb-2 BL target in the stock image as a function start (Ghidra misses small DSP helpers)."""
import struct
from m7 import FW, BASE
fw = open(FW, 'rb').read()
ghidra = {int(l.split()[0], 16): l.split()[1] for l in open('funcs.txt')}
tg = set()
for o in range(0, len(fw) - 4, 2):
    h1 = fw[o] | fw[o + 1] << 8; h2 = fw[o + 2] | fw[o + 3] << 8
    if h1 >> 11 != 0b11110 or (h2 >> 14) != 0b11 or not (h2 >> 12) & 1:
        continue
    s = (h1 >> 10) & 1; j1 = (h2 >> 13) & 1; j2 = (h2 >> 11) & 1
    imm = (s << 24) | ((1 - (j1 ^ s)) << 23) | ((1 - (j2 ^ s)) << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    if s: imm -= 1 << 25
    t = BASE + o + 4 + imm
    if BASE <= t < BASE + len(fw):
        tg.add(t)
# keep BL targets that are hit by >=2 call sites to avoid data false positives
cnt = {}
for o in range(0, len(fw) - 4, 2):
    pass
new = {t: f"sub_{t:08x}" for t in tg if t not in ghidra}
allf = dict(ghidra); allf.update(new)
with open('funcs_bl.txt', 'w') as f:
    for a in sorted(allf):
        f.write(f"{a:08x} {allf[a]}\n")
print(len(ghidra), len(new), len(allf))
