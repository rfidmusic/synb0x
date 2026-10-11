"""Run the patched image's solo code under Unicorn against a fake mixer view.

Real firmware runs for: cell set-unmuted (0x080a4f10), view set-mode (0x080b5e44), cell set-mode.
Stubbed and recorded: post msg, hit-test, set-screen, fill, outline, original touch handlers.
"""
import struct
import subprocess
import sys

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP

BASE = 0x08040000
IMG = open("out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+comp+fx2+munchi+cave/BLACKBOX.bin", "rb").read()
SYM = {l.split()[2]: int(l.split()[0], 16) for l in subprocess.run(
    ["arm-none-eabi-nm", "out/cave.elf"], capture_output=True, text=True).stdout.splitlines()}

VIEW, APP, PT, STACK, RET = 0x24070000, 0x24060000, 0x24078000, 0x2407F000, 0x0807FFF0
STATE = 0x2405FF60

uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
uc.mem_map(0x08000000, 0x200000)
uc.mem_write(BASE, IMG)
uc.mem_map(0x24000000, 0x80000)
uc.mem_write(RET, b"\x00\xbf\x00\xbf")
uc.mem_write(STATE, b"\xa5" * 64)  # uninitialised RAM: ensure() must cope

calls = []


def cell(i):
    return VIEW + 0x3AC + i * 0x1A0


def rd8(a):
    return uc.mem_read(a, 1)[0]


def rd32(a):
    return struct.unpack("<I", uc.mem_read(a, 4))[0]


def ret(value=None):
    if value is not None:
        uc.reg_write(UC_ARM_REG_R0, value)
    uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))


def stub(addr, fn):
    STUBS[addr] = fn


STUBS = {}
stub(0x080AED14, lambda: (calls.append(("post", *struct.unpack("<HHIHHIII", uc.mem_read(uc.reg_read(UC_ARM_REG_R1), 24))[0::2][:1],
                                         struct.unpack("<H", uc.mem_read(uc.reg_read(UC_ARM_REG_R1) + 8, 2))[0],
                                         rd32(uc.reg_read(UC_ARM_REG_R1) + 12))), ret()))
stub(0x080B5E78, lambda: (uc.mem_write(uc.reg_read(UC_ARM_REG_R2), struct.pack("<I", cell(rd32(uc.reg_read(UC_ARM_REG_R1))))), ret(1)))
stub(0x0809EAEC, lambda: (calls.append(("screen", uc.reg_read(UC_ARM_REG_R1))), ret()))
stub(0x0808EA22, lambda: (calls.append(("fill", uc.reg_read(UC_ARM_REG_R1))), ret()))
stub(0x0808E994, lambda: (calls.append(("outline", uc.reg_read(UC_ARM_REG_R1))), ret()))
stub(0x080B5F44, lambda: (calls.append(("orig_down",)), ret()))
stub(0x080B5EBC, lambda: (calls.append(("orig_move",)), ret()))


def on_code(uc, addr, size, _):
    if addr in STUBS:
        STUBS[addr]()


uc.hook_add(UC_HOOK_CODE, on_code)


def call(name_or_addr, *args):
    addr = SYM[name_or_addr] if isinstance(name_or_addr, str) else name_or_addr
    for reg, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
        uc.reg_write(reg, v)
    uc.reg_write(UC_ARM_REG_SP, STACK)
    uc.reg_write(UC_ARM_REG_LR, RET | 1)
    calls.clear()
    uc.emu_start(addr | 1, RET, count=200000)
    return list(calls)


def set_screen(s):
    uc.mem_write(APP + 0x8CA4, bytes([s]))


def unmuted():
    return [rd8(cell(i) + 0x189) for i in range(16)]


def touch(i):
    uc.mem_write(PT, struct.pack("<I", i))
    return call("solo_touch_down", VIEW, PT, 0)


fails = 0


def check(label, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + label)
    fails += not cond


# fake view: 16 cells, pad id = row<<4|col, all unmuted, no parent for post()
for i in range(16):
    uc.mem_write(cell(i) + 0x38, struct.pack("<H", (i // 4) << 4 | (i % 4)))
    uc.mem_write(cell(i) + 0x189, b"\x01")
uc.mem_write(VIEW + 0x2C, b"\0\0\0\0")

# Mixer -> Mute
set_screen(0x2E)
check("MIX on Mixer goes to Mute (0x2f)", call("solo_mix_pressed", APP, 0x2F, 0, 0) == [("screen", 0x2F)])
call("solo_set_mode", VIEW, 1)
check("Mute mode is not Solo", rd8(STATE + 4) == 0)
check("view mute flag set by real set-mode", rd8(VIEW + 0x1E40) == 1)
check("touch in Mute mode reaches the original handler", touch(3) == [("orig_down",)])

# Mute -> Solo
set_screen(0x2F)
check("MIX on Mute re-enters 0x2f", call("solo_mix_pressed", APP, 0x2E, 0, 0) == [("screen", 0x2F)])
call("solo_set_mode", VIEW, 1)
check("Solo mode active", rd8(STATE + 4) == 1)

# pad 5 muted beforehand
uc.mem_write(cell(5) + 0x189, b"\x00")
c = touch(2)
posts = [x for x in c if x[0] == "post"]
check("solo pad 2: 14 mute posts (pad 5 already muted, pad 2 stays)", len(posts) == 14 and all(p[3] == 0 for p in posts))
check("solo pad 2: posts carry msg 0x44", all(p[1] == 0x44 for p in posts))
check("solo pad 2: only pad 2 audible", unmuted() == [1 if i == 2 else 0 for i in range(16)])
check("touch in Solo never reaches the original handler", not any(x[0].startswith("orig") for x in c))

c = touch(7)
check("add pad 7: one unmute post for pad id 0x13", [x for x in c if x[0] == "post"] == [("post", 0x44, 0x13, 1)])
check("pads 2 and 7 audible", unmuted() == [1 if i in (2, 7) else 0 for i in range(16)])

# drawing in Solo mode
c = call("solo_mute_fill", cell(7) + 4, 0xB, 0)
check("soloed pad fill is dark yellow + 2 yellow outlines", c == [("fill", 0x1C), ("outline", 0x14), ("outline", 0x14)])
c = call("solo_mute_fill", cell(0) + 4, 0xC, 0)
check("muted pad stays red with yellow outline", c == [("fill", 0xC), ("outline", 0x14), ("outline", 0x14)])
c = call("solo_mute_fill", 0x24050000 + 4, 0xB, 0)
check("cells of other views untouched", c == [("fill", 0xB)])

touch(2)
check("unsolo pad 2: only pad 7 audible", unmuted() == [1 if i == 7 else 0 for i in range(16)])
touch(7)
check("clear last solo restores previous mutes (only pad 5 muted)", unmuted() == [0 if i == 5 else 1 for i in range(16)])

# a non-soloed pad that will not stay muted (an empty pad, or a hand edit) must NOT break the set: his 3.1.d report,
# "un-solo left nothing playing"
touch(9)
uc.mem_write(cell(0) + 0x189, b"\x01")  # pad 0 reads unmuted although the solo muted it
c = call("solo_mute_fill", cell(9) + 4, 0xB, 0)
check("a stray unmuted pad: pad 9 still drawn as soloed", c[0] == ("fill", 0x1C))
touch(9)
check("un-solo pad 9 restores the state from before the solo (only pad 5 muted), not 'everything muted'", unmuted() == [0 if i == 5 else 1 for i in range(16)])

# his 3.1.l report: a soloed pad that merely READS muted at the next tap (screen refresh, engine / screen disagreeing)
# must not drop the set and re-capture the solo's own mutes
touch(9)
uc.mem_write(cell(9) + 0x189, b"\x00")  # pad 9 reads muted, no hand edit
touch(9)
check("un-solo after a soloed pad read muted: still restores the state from before the solo (only pad 5 muted)", unmuted() == [0 if i == 5 else 1 for i in range(16)])
touch(9)
touch(9)
check("solo and un-solo again afterwards: back to only pad 5 muted", unmuted() == [0 if i == 5 else 1 for i in range(16)])

# a real hand edit (a tap in plain Mute mode) while a solo set exists drops the set: the hand edit wins
touch(9)                                 # solo pad 9: everything else muted
call("solo_set_mode", VIEW, 1)           # back into plain Mute mode (no MIX pending)
check("plain Mute mode after a solo", rd8(STATE + 4) == 0)
check("hand tap in Mute mode reaches the original handler", touch(9) == [("orig_down",)])
uc.mem_write(cell(9) + 0x189, b"\x00")  # the original handler muted pad 9 by hand
uc.mem_write(STATE + 5, b"\x01")        # MIX again: pending
call("solo_set_mode", VIEW, 1)
touch(4)
check("next solo after a hand edit starts fresh on pad 4", unmuted() == [1 if i == 4 else 0 for i in range(16)])
touch(4)
check("clearing it restores the hand-edited state at that tap (everything muted)", unmuted() == [0] * 16)

# Solo -> Mixer, and the move handler
check("move in Solo is swallowed", call("solo_touch_move", VIEW, PT, 0) == [])
set_screen(0x2F)
check("MIX in Solo goes to Mixer (0x2e)", call("solo_mix_pressed", APP, 0x2E, 0, 0) == [("screen", 0x2E)])
call("solo_set_mode", VIEW, 0)
check("Solo disarmed on Mixer", rd8(STATE + 4) == 0)
check("move on Mixer reaches the original handler", call("solo_touch_move", VIEW, PT, 0) == [("orig_move",)])
c = call("solo_mute_fill", cell(0) + 4, 0xB, 0)
check("no outline outside Solo", c == [("fill", 0xB)])

# INFO from Solo (set-mode 0 without MIX), then INFO back into Mute: must be Mute, not Solo
set_screen(0x2F)
call("solo_mix_pressed", APP, 0x2E, 0, 0)  # Mute -> Solo
call("solo_set_mode", VIEW, 1)
call("solo_set_mode", VIEW, 0)             # INFO: back to Mixer
call("solo_set_mode", VIEW, 1)             # INFO: into Mute
check("INFO path lands in Mute, not Solo", rd8(STATE + 4) == 0)

# from another screen MIX goes to Mixer
set_screen(0x02)
check("MIX from Pads goes to Mixer", call("solo_mix_pressed", APP, 0x2E, 0, 0) == [("screen", 0x2E)])

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
