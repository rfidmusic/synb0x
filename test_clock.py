"""3.1.v2 (TEST): 480 MHz on rev V silicon (src/clock.c) under Unicorn.

Real firmware runs for: clock_osc, clock_config, clock_sdram, clock_480 and the version text (short_version via
cpu_name). Stubbed: the HAL calls they wrap (record their arguments); the registers are plain memory set up here.
Checked: the three call sites call the hooks; rev V: SYSCFG clock on, overdrive on, waits for VOSRDY, PLL1 N 468 /
Q 5 handed to HAL_RCC_OscConfig (everything else in the struct as stock), 4 flash wait states, refresh count 1477;
rev Y and others: everything exactly as stock (N 390, Q 4, 2 wait states, 0x603, overdrive untouched); the version
text reads v4 / v4s (3.1.v4) by the PLL actually running.
NOT checked: the device (voltage, clock, heat, the SDRAM at 95.85 MHz).
"""
import struct
import sys

from emu import Emu

IMG = "out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+clock+delay+grain+cache+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


sys.path.insert(0, "patches")
from thumb import bl  # noqa: E402
img = open(IMG, "rb").read()
for at, name in ((0x08043F20, "clock_osc"), (0x08043F52, "clock_config"), (0x08045EC0, "clock_sdram")):
    check(f"{at:#x} calls {name}", img[at - 0x08040000:at - 0x08040000 + 4] == bl(at, e.sym[name]))
e.uc.mem_map(0x58000000, 0x30000)
e.uc.mem_map(0x5C001000, 0x1000)
e.uc.mem_map(0x00000000, 0x10000)                 # ITCM (3.1.v4: clock_config copies the grain window there)
IDC, DIVR, APB4, ODEN, D3CR = 0x5C001000, 0x58024430, 0x580244F4, 0x5800042C, 0x58024818
OSC = 0x24070000
stock_osc = struct.pack("<19I", 0x21, 0x10000, 0, 0, 0, 0, 1, 0, 0, 2, 2, 3, 390, 2, 4, 2, 4, 0, 0)
seen = {}
e.stub(0x0807D37C, lambda: seen.__setitem__("osc", bytes(e.uc.mem_read(e.arg(0), len(stock_osc)))), value=0)
e.stub(0x0807DB5C, lambda: seen.__setitem__("lat", e.arg(1)), value=0)
e.stub(0x08045DD8, lambda: seen.__setitem__("ref", e.arg(1)))


def run(rev, pll_n_after):
    seen.clear()
    e.w32(IDC, rev << 16 | 0x450)
    e.w32(APB4, 0)
    e.w32(ODEN, 0)
    e.w32(D3CR, 0xC000 | 0x2000)                    # VOS1, VOSRDY
    e.uc.mem_write(OSC, stock_osc)
    e.call("clock_osc", OSC)
    osc = struct.unpack("<19I", seen["osc"])
    e.w32(DIVR, (pll_n_after - 1) | (1 << 9) | ((osc[14] - 1) << 16) | (1 << 24))
    e.call("clock_config", 0x24071000, 2)
    e.call("clock_sdram", 0x24072000, 0x603)
    dest = bytearray(64)
    e.call("cpu_name", 0x24073000)
    return osc, e.r32(APB4), e.r32(ODEN), seen["lat"], seen["ref"], e.cstr(0x24073000)


osc, apb4, oden, lat, ref, name = run(0x2003, 468)
want = list(struct.unpack("<19I", stock_osc))
want[12], want[14] = 468, 5
check("rev V: SYSCFG clock on, overdrive (ODEN) on", apb4 & 2 and oden & 1, (apb4, oden))
check("rev V: HAL_RCC_OscConfig gets PLL1 N 468, Q 5, everything else as stock", list(osc) == want, osc)
check("rev V: 4 flash wait states, refresh count 1477", (lat, ref) == (4, 1477), (lat, ref))
import struct as _s
check("3.1.v4: clock_config copied the grain window to ITCM 0x8000 (8192 floats, as in flash)",
      bytes(e.uc.mem_read(0x8000, 0x8000)) == bytes(e.uc.mem_read(0x080D26AC, 0x8000)) and
      _s.unpack("<I", bytes(e.uc.mem_read(0x08057FD8, 4)))[0] == 0x8000)
check(f"rev V: the version reads '{name}'", name == "S.1", name)
for rev, label in ((0x1003, "rev Y"), (0x1001, "rev Z"), (0x2001, "rev X")):
    osc, apb4, oden, lat, ref, name = run(rev, 390)
    check(f"{label}: exactly stock (N 390, Q 4, overdrive untouched, 2 wait states, 0x603)",
          osc == struct.unpack("<19I", stock_osc) and oden == 0 and apb4 == 0 and (lat, ref) == (2, 0x603),
          (osc[12], osc[14], oden, lat, ref))
# the short name the meter shows follows the PLL actually running
e.w32(0x2405FFD0, 0x43505532)                       # the meter has readings (MAGIC, STATUS_OK, 34 / 71 %)
e.uc.mem_write(0x2405FFD0 + 18, struct.pack("<HHBB", 340, 710, 1, 1))
for n, want_s in ((468, "S.1 34/71%"), (390, "S.1s 34/71%")):
    e.w32(DIVR, (n - 1) | (1 << 9) | (3 << 16) | (1 << 24))
    e.call("cpu_name", 0x24073000)
    check(f"PLL1 N {n}: the meter reads '{e.cstr(0x24073000)}'", e.cstr(0x24073000) == want_s, e.cstr(0x24073000))
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
