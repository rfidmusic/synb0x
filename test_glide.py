"""Glide (portamento) under Unicorn: start / retune offsets, the per-block slide, the rate, the call-site thunks.

Real firmware runs for: the 2^x rate table (FUN_0805f728), the settings lookup, the backup SRAM enable.
Stubbed (recorded): the stock note-on and 2^(semitones/12) behind the thunks.
NOT checked: how it sounds, the stock note-on paths themselves (hardware).
"""
import math
import struct
import sys

from unicorn.arm_const import (UC_ARM_REG_LR, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4,
                               UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_S0, UC_ARM_REG_S5, UC_ARM_REG_SP)

from emu import RET, STACK, Emu

IMG = "out/solo+slice+filter+fenv+filttab+glide+cpu+od+comp+fx2+munchi+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)                 # backup SRAM
e.uc.mem_map(0x58024000, 0x1000)                 # RCC + PWR
P_GLIDE, P_GLIDETIME = 0x1E7, 0x1E8
OFF, ALWAYS, LEGATO = 0, 1, 2
FS = 48000.0
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def f32w(a, v):
    e.uc.mem_write(a, struct.pack("<f", v))


def f32r(a):
    return struct.unpack("<f", e.uc.mem_read(a, 4))[0]


def sreg(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def sget(reg=UC_ARM_REG_S0):
    return struct.unpack("<f", struct.pack("<I", e.uc.reg_read(reg)))[0]


APP_PADS = 0x24020088 + 0x1840
PAD = 0x24060000
VOICES = [0x24062000 + i * 0x600 for i in range(4)]
ROW, COL = 1, 3


def store(mode, time):
    s = APP_PADS + ROW * 0xF0 + COL * 0x30
    arr = 0x24073000
    e.uc.mem_write(arr, struct.pack("<HHiHHi", P_GLIDE, 0, mode, P_GLIDETIME, 0, time))
    e.w32(s + 4, arr)
    e.uc.mem_write(s + 10, struct.pack("<H", 2))


def pad_voices(*voices):
    e.uc.mem_write(PAD, bytes(0x80))
    e.w32(PAD + 0x18, ROW << 8 | COL)
    for i, v in enumerate(voices):
        e.w32(PAD + 0x2C + 4 * i, v)
    e.w32(PAD + 0x6C, len(voices))


def voice(v, active=1, stage=1, choked=0):
    e.uc.mem_write(v, bytes(0x600))              # includes the filter object at +0xa8: offset +0x58 zeroed, as stock start
    e.uc.mem_write(v, bytes([active]))
    e.uc.mem_write(v + 0x2C, bytes([stage]))
    e.uc.mem_write(v + 0x40, bytes([choked]))


def off(v):
    return f32r(v + 0xA8 + 0x58)


def seconds(t):
    return 10 * (t / 1000) ** 3


def advance(v, frames):
    e.call("glide_advance", v + 0xA8, frames)


# --- Always: every note slides from the last one, over Glide Time whatever the interval
store(ALWAYS, 400)
pad_voices(VOICES[0])
voice(VOICES[0])
e.call("glide_pre", PAD)
e.call("glide_start", VOICES[0], PAD, 60)
check("first note after power-on: nothing to slide from", off(VOICES[0]) == 0.0, off(VOICES[0]))
voice(VOICES[1])
pad_voices(VOICES[0], VOICES[1])
e.call("glide_pre", PAD)
e.call("glide_start", VOICES[1], PAD, 67)
check("Always: next note (67 after 60) starts 7 semitones low", off(VOICES[1]) == -7.0, off(VOICES[1]))
t = seconds(400)
blocks = int(t * FS / 256)
for _ in range(blocks // 2):
    advance(VOICES[1], 256)
check(f"halfway through Glide Time 40 ({t:.2f} s): -3.5 semitones", abs(off(VOICES[1]) + 3.5) < 0.05, off(VOICES[1]))
for _ in range(blocks):
    advance(VOICES[1], 256)
check("at Glide Time: at pitch (offset exactly 0)", off(VOICES[1]) == 0.0, off(VOICES[1]))

voice(VOICES[2])
pad_voices(VOICES[1], VOICES[2])
e.call("glide_start", VOICES[2], PAD, 43)         # two octaves down: same time
blocks_big = 0
while off(VOICES[2]) != 0.0 and blocks_big < 10 * blocks:
    advance(VOICES[2], 256)
    blocks_big += 1
check("constant time: a 24-semitone slide takes as long as a 7-semitone one", abs(blocks_big - blocks) <= 1, (blocks_big, blocks))

voice(VOICES[3])
pad_voices(VOICES[2], VOICES[3])
e.call("glide_start", VOICES[3], PAD, 48)
for _ in range(blocks // 4):
    advance(VOICES[3], 256)
mid = 48 + off(VOICES[3])
voice(VOICES[0])
pad_voices(VOICES[3], VOICES[0])
e.call("glide_start", VOICES[0], PAD, 60)
check(f"a note during a slide starts from where the pitch is ({mid:.2f}), not from the last note (43... 48)",
      abs(60 + off(VOICES[0]) - mid) < 1e-4, (60 + off(VOICES[0]), mid))

# a sliding voice recycled for the next note (stock zeroes its offset at the voice start, after glide_pre)
store(OFF, 400)                                   # the setup note at 48, not sliding
voice(VOICES[3])
pad_voices(VOICES[3])
e.call("glide_pre", PAD)
e.call("glide_start", VOICES[3], PAD, 48)
store(ALWAYS, 400)
voice(VOICES[2])
pad_voices(VOICES[3], VOICES[2])
e.call("glide_pre", PAD)
e.call("glide_start", VOICES[2], PAD, 60)          # slides from 48
for _ in range(blocks // 4):
    advance(VOICES[2], 256)
mid = 60 + off(VOICES[2])
check(f"(a slide 48 -> 60 is in progress: {mid:.2f})", 50 < mid < 59, mid)
e.call("glide_pre", PAD)                          # next note-on: stock then recycles VOICES[2] and zeroes it
voice(VOICES[2])
pad_voices(VOICES[2])
e.call("glide_start", VOICES[2], PAD, 72)
check(f"the sliding voice recycled for the next note: still starts from where the pitch was ({mid:.2f})",
      abs(72 + off(VOICES[2]) - mid) < 1e-4, (72 + off(VOICES[2]), mid))
e.uc.mem_write(0x38800700 + 4 + (ROW * 5 + COL) * 16, struct.pack("<f", float("nan")))
e.uc.mem_write(0x38800700 + 4 + (ROW * 5 + COL) * 16 + 10, b"\x00")   # not fresh: falls back to note + offset
voice(VOICES[1])
pad_voices(VOICES[2], VOICES[1])
e.call("glide_start", VOICES[1], PAD, 50)
check("a damaged backup SRAM note (NaN): no slide, not a NaN pitch", off(VOICES[1]) == 0.0, off(VOICES[1]))

# --- Off and Glide Time 0
store(OFF, 400)
voice(VOICES[1])
pad_voices(VOICES[0], VOICES[1])
e.call("glide_start", VOICES[1], PAD, 72)
check("Off: no slide", off(VOICES[1]) == 0.0)
store(ALWAYS, 0)
voice(VOICES[2])
pad_voices(VOICES[1], VOICES[2])
e.call("glide_start", VOICES[2], PAD, 50)
check("Glide Time 0: no slide", off(VOICES[2]) == 0.0)

# --- Legato: only while a note of the pad is held (taken before the note-on)
store(LEGATO, 300)
voice(VOICES[0], stage=4)                         # released
pad_voices(VOICES[0])
e.call("glide_start", VOICES[0], PAD, 60)
e.call("glide_pre", PAD)                          # before the note-on: only the released voice exists
voice(VOICES[1])
pad_voices(VOICES[0], VOICES[1])
e.call("glide_start", VOICES[1], PAD, 64)
check("Legato, previous note released: no slide", off(VOICES[1]) == 0.0, off(VOICES[1]))
voice(VOICES[2], stage=3)                         # held (sustain)
pad_voices(VOICES[2])
e.call("glide_start", VOICES[2], PAD, 64)
e.call("glide_pre", PAD)                          # next note while 64 is held
voice(VOICES[3])
pad_voices(VOICES[2], VOICES[3])
e.call("glide_start", VOICES[3], PAD, 69)
check("Legato, previous note held: slides (5 semitones)", off(VOICES[3]) == -5.0, off(VOICES[3]))
voice(VOICES[0], stage=2, choked=1)               # held but choked: not a held note
pad_voices(VOICES[0])
e.call("glide_pre", PAD)
voice(VOICES[1])
pad_voices(VOICES[0], VOICES[1])
e.call("glide_start", VOICES[1], PAD, 62)
check("Legato, the only other voice is choked: no slide", off(VOICES[1]) == 0.0, off(VOICES[1]))

# --- legato retune of a sounding voice (stock Legato switch): the same voice slides to the new note
store(LEGATO, 300)
voice(VOICES[2], stage=3)
pad_voices(VOICES[2])
e.call("glide_start", VOICES[2], PAD, 55)
e.call("glide_pre", PAD)
e.call("glide_retune", VOICES[2], PAD, 58)
check("retune 55 -> 58 in place: offset -3, sliding up", off(VOICES[2]) == -3.0, off(VOICES[2]))
advance(VOICES[2], 1024)
here = 58 + off(VOICES[2])
e.call("glide_retune", VOICES[2], PAD, 53)
check("retune again mid-slide: continues from where it is", abs(53 + off(VOICES[2]) - here) < 1e-4, (53 + off(VOICES[2]), here))
store(OFF, 300)
e.call("glide_retune", VOICES[2], PAD, 60)
check("retune with Glide Off: straight to pitch", off(VOICES[2]) == 0.0)

# --- the rate: 2^(octaves + offset / 12) through the stock table
def fw_exp2(x):
    e.uc.reg_write(UC_ARM_REG_S0, sreg(x))
    e.call(0x0805F728)
    return sget()


voice(VOICES[0])
f32w(VOICES[0] + 0xA8 + 0x58, -7.0)
e.uc.reg_write(UC_ARM_REG_S0, sreg(0.25))
e.uc.reg_write(UC_ARM_REG_R4, VOICES[0])
e.call("glide_rate_thunk")
got, want = sget(), fw_exp2(0.25 - 7 / 12)
check(f"rate thunk (voice in r4): 2^(0.25 + -7/12) = {got:.4f}", abs(got - want) < 1e-6 and abs(got - 2 ** (0.25 - 7 / 12)) < 0.002, (got, want))
f32w(VOICES[0] + 0xA8 + 0x58, 0.0)
e.uc.reg_write(UC_ARM_REG_S0, sreg(0.25))
e.uc.reg_write(UC_ARM_REG_R4, VOICES[0])
e.call("glide_rate_thunk")
check("no slide: the stock rate exactly", sget() == fw_exp2(0.25))

# --- thunks keep the stock calls' arguments
seen = {}


def note_on_stub():
    sp = e.uc.reg_read(UC_ARM_REG_SP)
    seen["regs"] = [e.uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
    seen["stack"] = [e.r32(sp + 4 * i) for i in range(3)]
    seen["s0"], seen["s5"] = sget(), sget(UC_ARM_REG_S5)
    seen["sp"] = sp


e.stub(0x08058548, note_on_stub)
store(LEGATO, 300)
voice(VOICES[0], stage=3)
pad_voices(VOICES[0])
for k, v in enumerate((0x11, 0x22, 0x33)):
    e.w32(STACK + 4 * k, v)
for r, v in ((UC_ARM_REG_R0, PAD), (UC_ARM_REG_R1, 7), (UC_ARM_REG_R2, 8), (UC_ARM_REG_R3, 62)):
    e.uc.reg_write(r, v)
e.uc.reg_write(UC_ARM_REG_S0, sreg(1.5))
e.uc.reg_write(UC_ARM_REG_S5, sreg(-2.25))
e.uc.reg_write(UC_ARM_REG_SP, STACK)
e.uc.reg_write(UC_ARM_REG_LR, RET | 1)
e.uc.emu_start(e.sym["glide_note_on"] | 1, RET)
check("note-on thunk: r0-r3, the three stack arguments, s0 and s5 reach the stock note-on unchanged",
      seen["regs"] == [PAD, 7, 8, 62] and seen["stack"] == [0x11, 0x22, 0x33] and seen["s0"] == 1.5 and seen["s5"] == -2.25
      and seen["sp"] == STACK, seen)
e.uc.mem_write(0x38800700 + 4 + (ROW * 5 + COL) * 16 + 9, b"\x00")
e.call("glide_note_on", PAD, 0, 0, 0)
held = e.r8(0x38800700 + 4 + (ROW * 5 + COL) * 16 + 9)
check("note-on thunk records the held note (voice in sustain)", held == 1, held)

semis = []
e.stub(0x0805F6B8, lambda: semis.append(e.arg(0)))
for name, vreg, preg, nreg in (("glide_start_thunk", UC_ARM_REG_R5, UC_ARM_REG_R4, UC_ARM_REG_R7),
                               ("glide_retune_thunk", UC_ARM_REG_R6, UC_ARM_REG_R4, UC_ARM_REG_R3)):
    store(OFF, 300)                               # the setup note itself does not slide
    voice(VOICES[1], stage=3)
    voice(VOICES[2])
    pad_voices(VOICES[1], VOICES[2])
    e.call("glide_start", VOICES[1], PAD, 60)
    store(ALWAYS, 300)
    semis.clear()
    e.uc.reg_write(vreg, VOICES[2])
    e.uc.reg_write(preg, PAD)
    e.uc.reg_write(nreg, 65)
    e.call(name, 65 - 60)
    check(f"{name}: voice / pad / note from the stock registers (slide -5), r0 passed on to the stock 2^(x/12)",
          off(VOICES[2]) == -5.0 and semis == [5], (off(VOICES[2]), semis))

# --- Conf tab and defaults
def ids(a, n):
    return list(struct.unpack(f"<{n}H", e.uc.mem_read(a, 2 * n)))


conf = {"Sample": ids(0x080EFD38, 13), "Multisample": ids(0x080EFAB0 + 4 * 0x48, 12), "Sample (empty pad)": ids(0x080EF4C8, 13)}
for name, l in conf.items():
    i = l.index(0xA0)
    check(f"Conf, {name}: Glide and Glide Time right after Poly Mode, list still ends with 0", l[i + 1:i + 3] == [P_GLIDE, P_GLIDETIME] and 0 in l, l)

print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
