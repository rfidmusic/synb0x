"""Filter Type / envelope parameters under Unicorn: registration, pad defaults, store capacity.

Real firmware runs for: the pad record defaults (FUN_08093f20, types 3 and 0x4c) with the stock store allocator
(FUN_08093e6a / FUN_0804436c, pointed at test RAM), the stock store adder and lookup, and the patched capacity.
Stubbed: the two parameter registrars (recorded).
NOT checked: the screens, preset files on the SD card (hardware).
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP

from emu import Emu

IMG = "out/solo+slice+filter+fenv+cpu+od+comp+fx2+munchi+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
P_FILTER = 200
P_FTYPE, P_FATTACK, P_FDECAY, P_FSUSTAIN, P_FRELEASE, P_FDEPTH = range(0x1E1, 0x1E7)

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


# --- registration: Filter as stock, then the six new parameters
regs = []


def sp(k):
    """k-th stack argument at the moment of the call"""
    return e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4 * k)


e.stub(0x0808C12C, lambda: regs.append(("num", e.arg(1), e.arg(2), e.cstr(e.arg(3)), sp(0), sp(1), e.cstr(sp(2)))))
e.stub(0x0808C0D8, lambda: regs.append(("list", e.arg(1), [e.cstr(e.r32(e.arg(3) + 4 * i)) for i in range(sp(0))],
                                         e.cstr(e.arg(2)), e.cstr(sp(1)))))
e.uc.mem_write(0x24050000, b"Filter:\0")
e.uc.mem_write(0x24050010, b"dualfilcutoff\0")
STACK = 0x2407F000
e.w32(STACK, -1000)
e.w32(STACK + 4, 1000)
e.w32(STACK + 8, 0x24050010)

e.call("fenv_register", 0x24040000, P_FILTER, 9, 0x24050000)
check("Filter is still registered as stock (200, bipolar -1000..1000, dualfilcutoff)",
      regs and regs[0] == ("num", 200, 9, "Filter:", -1000, 1000, "dualfilcutoff"), regs[:1])
want = [("list", P_FTYPE, ["LP", "HP", "BP"], "Type:", "fenvtype"),
        ("num", P_FATTACK, 8, "Attack:", 0, 1000, "fenvattack"),
        ("num", P_FDECAY, 8, "Decay:", 0, 1000, "fenvdecay"),
        ("num", P_FSUSTAIN, 8, "Sustain:", 0, 1000, "fenvsus"),
        ("num", P_FRELEASE, 8, "Release:", 0, 1000, "fenvrel"),
        ("num", P_FDEPTH, 9, "Depth:", -1000, 1000, "fenvdepth")]
check("Type (LP/HP/BP) and Attack/Decay/Sustain/Release/Depth registered with unique xml names", regs[1:] == want, regs[1:])
check("new ids are below the 500-slot parameter table", all(r[1] < 500 for r in regs))
check("the hook replaces the Filter registration call", e.r16(0x0808D59C) != 0xF7FE)

# --- capacity: movs r1,#64 -> #72 at both allocation sites
check("store capacity raised to 72 at 0x080949f0 and 0x08093f26",
      e.r16(0x080949F0) == 0x2148 and e.r16(0x08093F26) == 0x2148, (hex(e.r16(0x080949F0)), hex(e.r16(0x08093F26))))

# --- pad record defaults through the real stock function, with the stock allocator
POOL, LIMIT = 0x24030000, 0x24038000
e.w32(0x2400008C, POOL)                          # SDRAM pool bump pointer and limit, here in test RAM
e.w32(0x24000088, LIMIT)
STORE, TYPEBYTE = 0x24020000, 0x24021000


def defaults(kind):
    e.uc.mem_write(STORE, bytes(0x20))
    e.uc.mem_write(TYPEBYTE, bytes([kind]))
    e.call(0x08093F20, STORE, TYPEBYTE)
    arr, count, cap = e.r32(STORE + 4), e.r16(STORE + 10), e.r16(STORE + 12)
    ent = {}
    for i in range(count):
        ent[e.r16(arr + 8 * i)] = e.r32(arr + 8 * i + 4)
    return ent, count, cap


for kind, name in ((3, "sample pad"), (0x4C, "empty pad")):
    ent, count, cap = defaults(kind)
    check(f"{name}: capacity 72, {count} entries, none dropped", cap == 72 and count <= cap and count == len(ent), (cap, count))
    check(f"{name}: Filter defaults fully open (1000)", ent.get(P_FILTER) == 1000, ent.get(P_FILTER))
    check(f"{name}: Type LP, A 0, D 300, S 0, R 300, Depth 0",
          [ent.get(i) for i in (P_FTYPE, P_FATTACK, P_FDECAY, P_FSUSTAIN, P_FRELEASE, P_FDEPTH)] == [0, 0, 300, 0, 300, 0],
          [ent.get(i) for i in (P_FTYPE, P_FATTACK, P_FDECAY, P_FSUSTAIN, P_FRELEASE, P_FDEPTH)])
    check(f"{name}: stock Res default unchanged (500)", ent.get(0x11) == 500, ent.get(0x11))
    if kind == 3:
        check(f"sample pad: stock entries after Filter still present (0xdc last)", 0xDC in ent and count == 65, count)
    e.call(0x08093E9C, STORE, P_FDECAY)
    check(f"{name}: stock lookup finds the new entries", e.uc.reg_read(UC_ARM_REG_R0) == 300)

print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
