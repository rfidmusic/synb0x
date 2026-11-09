"""delay_read (cave) against the stock FUN_0806ab70 (still in the image) on the same random line states: output samples
and the line's state after, bit for bit. Needs: ./build.sh; python3 patch.py solo slice filter fenv filttab glide splash cpu od clock delay grain cache cave"""
import random, struct, sys
sys.path.insert(0, ".")
from emu import Emu
e = Emu("out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+clock+delay+grain+cache+cave/BLACKBOX.bin", "out/cave.elf")
LINE, FRAME, BUF, L, R = 0x24070000, 0x24070100, 0x24000000, 0x24071000, 0x24072000
rng = random.Random(7)
bad = cases = interp = 0
for k in range(3000):
    ln = rng.choice((3, 4, 100, 4096, 48000, 96000, rng.randint(3, 60000)))
    n = rng.choice((1, 2, 31, 64, 128, 256))
    wr = rng.randrange(ln)
    dist = rng.choice((0, 1, 2, rng.randrange(ln)))
    target = rng.choice((dist, dist, dist + 1, dist - 1, max(0, dist - rng.randint(0, 300)), rng.randrange(ln)))
    rd = (wr - dist) % ln
    if rng.random() < 0.03: rd = ln + rng.randint(0, 3)            # odd states: index past the end
    frac = rng.choice((0.0, rng.random(), 0.999999, 0.5))
    if rng.random() < 0.02: frac = rng.choice((1.0, 1.7, -0.25))
    bufv = struct.pack(f"<{min(ln + 4, 96004)}f", *[rng.uniform(-1, 1) for _ in range(min(ln + 4, 96004))])
    left = rng.random() < 0.5
    res = []
    for fn in (0x0806AB70, "delay_read"):
        e.uc.mem_write(BUF, bufv)
        e.uc.mem_write(LINE, struct.pack("<IIIfIIB3x", BUF, wr, rd, frac, target & 0xffffffff, ln, 0))
        e.uc.mem_write(FRAME, struct.pack("<IIIIBB2x", n, 0, L, R, 0, 1))
        e.uc.mem_write(L, b"\x55" * 4 * 256); e.uc.mem_write(R, b"\x66" * 4 * 256)
        e.call(fn, LINE, FRAME, int(left), count=5_000_000)
        res.append((bytes(e.uc.mem_read(LINE, 28)), bytes(e.uc.mem_read(L, 1024)), bytes(e.uc.mem_read(R, 1024))))
    cases += 1
    interp += dist != target
    if res[0] != res[1]:
        bad += 1
        if bad < 5: print("MISMATCH", dict(ln=ln, n=n, wr=wr, rd=rd, dist=dist, target=target, frac=frac))
print(("PASS" if not bad else "FAIL") + f" delay_read = stock FUN_0806ab70 bit for bit: {cases} cases ({interp} varispeed), {bad} mismatches")
print(f"\n{int(bad > 0)} failure(s)")
sys.exit(int(bad > 0))
