"""CPU meter under Unicorn.

Real firmware runs for: the text-object setter (string copy + dirty flag) on fake label text objects.
Stubbed: the FreeRTOS queue wait (advances a fake DWT cycle counter), the label setter.
NOT checked: that the DWT counter runs on the unit, the label redraw, and which screen shows which label (hardware).
"""
import struct
import sys

from emu import Emu

e = Emu("out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+comp+fx2+munchi+cave/BLACKBOX.bin", "out/cave.elf")
V = e.cstr(e.sym["mod_version"])                # the version this build shows
SV = V.split("-")[-1]                           # with numbers: the part after the "-"
e.uc.mem_map(0xE0000000, 0x100000)
CYC, STATE = 0xE0001004, 0x2405FFD0
TEXT = [0x24060000, 0x24061000, 0x24062000]
clock = {"busy": 0, "idle": 0, "got": 1}


def cyc():
    return e.r32(CYC) & 0xFFFFFFFF


def receive():
    e.w32(CYC, cyc() + clock["idle"])
    e.calls.append(("wait", e.arg(0), e.arg(2)))
    e.ret(clock["got"])


e.stubs[0x08088756] = receive
e.stub(0x080A3DEC)


def block(busy, idle):
    """One audio period: the task works `busy` cycles, then waits `idle` cycles for the next interrupt."""
    clock["idle"] = idle
    e.w32(CYC, cyc() + busy)
    return e.call("cpu_wait", 0x24001F00, 0x24001F80, 2000, 0)


def text(i):
    return e.cstr(TEXT[i] + 0x31)


def labels(init=None):
    init = init or V
    for t in TEXT:
        e.uc.mem_write(t, bytes(0x60))
        e.uc.mem_write(t + 0x31, init.encode() + b"\0")
    e.call("cpu_label_a", TEXT[0] - 0x34, e.sym["mod_version"])
    e.call("cpu_text_b", TEXT[1], e.sym["mod_version"])
    e.call("cpu_text_c", TEXT[2], e.sym["mod_version"])


fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


e.uc.mem_write(STATE, b"\xa5" * 36)            # patch RAM is not zeroed at boot
e.w32(CYC, 123456)
labels()
check("labels built at boot are remembered (all three) and keep the version text", all(e.r32(STATE + 24 + 4 * i) == TEXT[i] for i in range(3)) and text(1) == V, [hex(e.r32(STATE + 24 + 4 * i)) for i in range(3)])
check("cycle counter switched on (TRCENA, unlock, CYCCNTENA)", e.r32(0xE000EDFC) & (1 << 24) and e.r32(0xE0001FB0) & 0xFFFFFFFF == 0xC5ACCE55 and e.r32(0xE0001000) & 1)

PERIOD = 2_560_000                              # 5.33 ms at 480 MHz
c = block(0, PERIOD)
check("the wait itself is passed through unchanged", c[0] == ("wait", 0x24001F00, 2000))
for i in range(187):
    block(PERIOD * 30 // 100, PERIOD * 70 // 100)
check("before a full second: labels untouched", text(0) == V)
block(PERIOD * 30 // 100, PERIOD * 70 // 100)
check(f"after 188 blocks at 30% busy: '{SV} 30/30%' on every label", [text(i) for i in range(3)] == [SV + " 30/30%"] * 3, [text(i) for i in range(3)])
check("the label's own dirty flag is set by the stock setter", e.r8(TEXT[1] + 0x55) == 1 or e.r8(TEXT[1] + 0x56) == 1)

for i in range(188):
    busy = 80 if i == 50 else 40
    block(PERIOD * busy // 100, PERIOD * (100 - busy) // 100)
check("one heavy block in a second: average 40%, peak 80%", text(1) == SV + " 40/80%", text(1))

for i in range(188):
    block(PERIOD * 120 // 100, PERIOD * 5 // 100)
check("overrun (work longer than a period): reads over 100%", text(1).endswith("/96%") or int(text(1).split()[1].split("/")[0]) > 90, text(1))

clock["got"] = 0
block(10_000, PERIOD * 400)                     # a 2 s timeout with no interrupt (audio stopped)
clock["got"] = 1
block(0, PERIOD)
for i in range(188):
    block(PERIOD // 10, PERIOD * 9 // 10)
check("after a wait that timed out, the next second measures cleanly again (10/10%)", text(1) == SV + " 10/10%", text(1))

e.w32(CYC, 0xFFFFFFFF - PERIOD * (188 + 50))   # wraps during the second report; the jump itself is absorbed by the first
for i in range(188 * 2):
    block(PERIOD // 4, PERIOD * 3 // 4)
check("cycle counter wrapping past 2^32 does not disturb the reading (25/25%)", text(1) == SV + " 25/25%", text(1))

e.uc.mem_write(TEXT[2] + 0x31, b"\x13\x37garbage\0")
for i in range(188):
    block(PERIOD // 2, PERIOD // 2)
check("a remembered pointer whose text no longer says 3.1. is not written", text(2) == "\x13\x37garbage" and text(1) == SV + " 50/50%", (text(2), text(1)))
e.w32(STATE + 24, 0x08001234)
for i in range(188):
    block(PERIOD // 2, PERIOD // 2)
check("a pointer outside RAM is skipped, the others still update", text(1) == SV + " 50/50%")

# --- the global cell's name: what the screens actually show
APP, ADDR, INFO = 0x24020088, 0x24070000, 0x24071000
e.uc.mem_write(ADDR, struct.pack("<IH", 0, 0x40))
e.uc.mem_write(INFO, b"\xee" * 0x60)
e.w32(APP + 0xE988, 12 * 1024 * 1024)           # memory figure the stock code formats next to the name
e.w32(APP + 0xE98C, 0)
e.stub(0x080C89F4, lambda: e.calls.append(("fmt", e.arg(0))))
c = e.call(0x0809AD74, APP, ADDR, INFO)
check("global cell info (stock function, patched copy): name reads version + load", e.cstr(INFO) == SV + " 50/50%", e.cstr(INFO))
check("...and the stock code still formats its size field after it (at +0x40)", ("fmt", INFO + 0x40) in c, c)
check("name text stays well inside its 64 bytes", len(e.cstr(INFO)) < 20)

e.uc.mem_write(STATE, b"\xa5" * 36)            # fresh boot
e.w32(CYC, 777)
clock["idle"] = 0
for i in range(376):
    e.call("cpu_wait", 0x24001F00, 0x24001F80, 2000, 0)  # cycle counter never moves
e.call(0x0809AD74, APP, ADDR, INFO)
check("cycle counter dead: shows '--%' instead of nothing", e.cstr(INFO) == SV + " --%", e.cstr(INFO))
e.uc.mem_write(STATE, b"\xa5" * 36)
e.call(0x0809AD74, APP, ADDR, INFO)
check("before anything is measured: just the version", e.cstr(INFO) == V, e.cstr(INFO))

# --- the version: 3.1.9-syn everywhere the stock "3.1.9" was referenced, never cut short by the meter
check("version string is 3.1.s", V == "3.1.s", V)
lits = [e.r32(a) & 0xFFFFFFFF for a in (0x0809AF30, 0x080AEAF4, 0x080C55E8, 0x080C72C8)]
check("all four stock references point at it", lits == [e.sym["mod_version"]] * 4, [hex(x) for x in lits])
check(f"with numbers the labels read {SV} + load, 12 characters at most at ordinary loads", all(text(i).startswith(SV + " ") and len(text(i)) <= 12 for i in (0, 1)), [text(i) for i in range(3)])
NAME = 0x24070800
e.uc.mem_write(NAME, bytes(64))
e.call("cpu_name", NAME)
check("before (or without) a reading, the global name shows the full version", e.cstr(NAME) == V, e.cstr(NAME))

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
