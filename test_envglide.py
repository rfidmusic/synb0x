"""The stock amp envelope with its glide loop replaced (env_glide, CPU) against stock 3.1.9, under Unicorn.

Real firmware runs for: FUN_0806a6c0 in both images (stock, and this build's with the jump at 0x0806a822 to
env_glide), its curve helpers. Its parameter read (FUN_0806fb30) is stubbed the same in both. Checked: for stages Attack,
Decay, Sustain and Release, gains near and far from their targets, glides that finish mid-call or not, mono and
stereo, block sizes 1 .. 256: the audio and the envelope's state afterwards are bit-identical.
NOT checked: how it sounds (it is the same arithmetic).
"""
import random
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_S0

from emu import Emu

MOD = "out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+cave/BLACKBOX.bin"
ENV, PAR, L, R = 0x24070000, 0x24071000, 0x24072000, 0x24073000
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def make(image):
    e = Emu(image, "out/cave.elf")
    e.stub(0x0806FB30, lambda: e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", 0.4))[0]))
    return e


stock, mine = make("firmware/BLACKBOX-3.1.9.bin"), make(MOD)
check("the glide loop jumps to env_glide (0x0806a822)", mine.r16(0x0806A822) != 0xEDC4 and stock.r16(0x0806A822) == 0xEDC4)
rng = random.Random(3)
cases = same = 0
worst = None
for trial in range(400):
    stage = rng.choice((1, 2, 3, 4))
    n = rng.choice((1, 3, 4, 17, 64, 128, 255, 256))
    stereo = rng.random() < 0.5
    g = rng.choice((0.0, 1.0, rng.random(), 0.25))
    tgt_par = rng.choice((0.0, 1.0, rng.random()))
    coef = rng.choice((0.0078125, 0.05, 0.5))
    count, length = rng.randrange(1, 4000), rng.randrange(4000, 9000)
    x = [rng.uniform(-1, 1) for _ in range(n)]
    y = [rng.uniform(-1, 1) for _ in range(n)]
    outs = []
    for e in (stock, mine):
        e.uc.mem_write(PAR, bytes(0x100))
        e.uc.mem_write(PAR + 0x18, struct.pack("<f", tgt_par))
        e.uc.mem_write(ENV, bytes(0x40))
        e.uc.mem_write(ENV + 4, bytes([stage]))
        e.w32(ENV + 8, PAR)
        e.uc.mem_write(ENV + 0xC, struct.pack("<f", 1.0))
        e.w32(ENV + 0x10, count)
        e.w32(ENV + 0x14, length)
        e.uc.mem_write(ENV + 0x1C, struct.pack("<ff", g, g))
        e.uc.mem_write(ENV + 0x24, struct.pack("<f", coef))
        e.uc.mem_write(L, struct.pack(f"<{n}f", *x))
        e.uc.mem_write(R, struct.pack(f"<{n}f", *y))
        e.call(0x0806A6C0, ENV, L, R if stereo else 0, n)
        outs.append(bytes(e.uc.mem_read(L, 4 * n)) + bytes(e.uc.mem_read(R, 4 * n)) + bytes(e.uc.mem_read(ENV, 0x40)))
    cases += 1
    if outs[0] == outs[1]:
        same += 1
    elif worst is None:
        worst = dict(stage=stage, n=n, stereo=stereo, g=g, tgt=tgt_par, coef=coef)
check(f"{same} of {cases} random envelope calls bit-identical to stock (audio and envelope state; mono and stereo, "
      "every stage, block sizes 1 .. 256)", same == cases, worst)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
