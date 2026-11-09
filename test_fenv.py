"""Filter Type / envelope parameters under Unicorn: registration, pad defaults, store capacity.

Real firmware runs for: the pad record defaults (FUN_08093f20, types 3 and 0x4c) with the stock store allocator
(FUN_08093e6a / FUN_0804436c, pointed at test RAM), the stock store adder and lookup, and the patched capacity.
Stubbed: the two parameter registrars (recorded).
NOT checked: the screens, preset files on the SD card (hardware).
"""
import struct
import sys


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]

from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP

from emu import Emu

IMG = "out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
P_FILTER = 200
P_FTYPE, P_FATTACK, P_FDECAY, P_FSUSTAIN, _UNUSED, P_FDEPTH = range(0x1E1, 0x1E7)
P_FRELEASE = 0x1EB                                  # 0x1e5 is a hidden stock Keys switch

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
        ("num", 0x1E9, 8, "Morph:", 0, 1000, "fenvmorph"),
        ("num", P_FATTACK, 8, "Attack:", 0, 1000, "fenvattack"),
        ("num", P_FDECAY, 8, "Decay:", 0, 1000, "fenvdecay"),
        ("num", P_FSUSTAIN, 8, "Sustain:", 0, 1000, "fenvsus"),
        ("num", P_FRELEASE, 8, "Release:", 0, 1000, "fenvrel"),
        ("num", P_FDEPTH, 9, "Depth:", -1000, 1000, "fenvdepth"),
        ("list", 0x1E7, ["Off", "Always", "Legato"], "Glide:", "glidemode"),
        ("num", 0x1E8, 8, "Glide Time:", 0, 1000, "glidetime"),
        ("num", 0x1EC, 8, "AD Atk:", 0, 1000, "adattack"),                # 3.1.v7: "AD Atk:"
        ("num", 0x1ED, 8, "AD Decay:", 0, 1000, "addecay"),
        ("num", 0x1C0, 8, "Atk Slope:", 0, 1000, "adatkslope"),           # 3.1.v7 (1-Shot removed)
        ("num", 0x1C1, 8, "Dec Slope:", 0, 1000, "addecslope"),
        ("list", 0x1EF, ["SEM", "Polivoks"], "Filter Type:", "filtermodel"),   # on the Conf tab (Stock removed)
        ("num", 0x1F0, 4, "Osc", 0, 1000, "oscon"),                       # 3.1.uo: the oscillator (Osc tab)
        ("num", 0x1F1, 4, "OSC/MOD", 0, 1000, "oscmode"),
        ("list", 0x1F2, ["Sine", "Square", "Triangle", "Saw"], "Wave:", "oscwave"),   # a selector
        ("num", 0x1F3, 8, "Level:", 0, 1000, "osclevel"),
        ("list", 0x1DC, ["-3", "-2", "-1", "0", "+1", "+2", "+3"], "Octave:", "oscoctave"),
        ("num", 0x1DD, 8, "Tune:", 0, 1000, "osctune"),
        ("num", 0x1DE, 9, "Fine:", -1000, 1000, "oscfine"),
        ("num", 0x1DF, 9, "Pulse W:", -1000, 1000, "oscpw"),
        ("num", 0x1E0, 4, "Osc Track", 0, 1000, "osctrack")]                     # S.1: a button on the Osc tab (3.1.uk: list, Conf)
check("Type (hidden, for old presets), Morph, A/D/S/R/Depth, Glide, Glide Time, AD Atk / Decay, Atk / Dec Slope (no 1-Shot), Filter Type, Osc, Osc Track registered "
      "with unique xml names", regs[1:] == want and len({r[-1] for r in regs}) == len(regs), regs[1:])
check("new ids are below the 500-slot parameter table", all(r[1] < 500 for r in regs))
check("the hook replaces the Filter registration call", e.r16(0x0808D59C) != 0xF7FE)
sys.path.insert(0, "patches")
from thumb import bl as _bl                         # noqa: E402  (the patcher's own BL encoder)
sites = {0x08056FF8: "lfo_update_a", 0x0805800A: "lfo_update_a", 0x08066838: "lfo_update_b"}
check("the three LFO updates (sample, multisample, clip / slicer voices) call lfo_update_a / _b",
      all(bytes(e.uc.mem_read(a, 4)) == _bl(a, e.sym[f]) for a, f in sites.items()))

# --- capacity: movs r1,#64 -> #88 at both allocation sites (3.1.uo 80, 3.1.uk 88)
check("store capacity raised to 88 at 0x080949f0 and 0x08093f26",
      e.r16(0x080949F0) == 0x2158 and e.r16(0x08093F26) == 0x2158, (hex(e.r16(0x080949F0)), hex(e.r16(0x08093F26))))

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
    check(f"{name}: capacity 88, {count} entries, none dropped", cap == 88 and count <= cap and count == len(ent), (cap, count))
    check(f"{name}: Filter defaults fully open (1000)", ent.get(P_FILTER) == 1000, ent.get(P_FILTER))
    check(f"{name}: Morph 0 (LP), Type LP, A 0, D 300, S 0, R 300, Depth 0",
          [ent.get(i) for i in (0x1E9, P_FTYPE, P_FATTACK, P_FDECAY, P_FSUSTAIN, P_FRELEASE, P_FDEPTH)] == [0, 0, 0, 300, 0, 300, 0],
          [ent.get(i) for i in (0x1E9, P_FTYPE, P_FATTACK, P_FDECAY, P_FSUSTAIN, P_FRELEASE, P_FDEPTH)])
    check(f"{name}: stock Res default unchanged (500)", ent.get(0x11) == 500, ent.get(0x11))
    if kind == 3:
        check(f"sample pad: stock entries after Filter still present (0xdc last), 82 entries (of 88)", 0xDC in ent and count == 82, count)
    check(f"{name}: Filter Type SEM (0), stored right after AD Decay", ent.get(0x1EF) == 0, ent.get(0x1EF))
    check(f"{name}: Glide Off, Glide Time 200", (ent.get(0x1E7), ent.get(0x1E8)) == (0, 200), (ent.get(0x1E7), ent.get(0x1E8)))
    arr = e.r32(STORE + 4)
    ids = [e.r16(arr + 8 * i) for i in range(count)]
    check(f"{name}: AD Attack 0, AD Decay 300, then Filter Type, side by side; no LFO Mode (3.1.v7)",
          (ent.get(0x1EC), ent.get(0x1ED)) == (0, 300) and 0x1EE not in ent
          and ids.index(0x1ED) == ids.index(0x1EC) + 1 and ids.index(0x1EF) == ids.index(0x1EC) + 2,
          (ent.get(0x1EC), ent.get(0x1ED), ent.get(0x1EE)))
    check(f"{name}: the record still fits (capacity 88)", count <= 88, count)
    check(f"{name}: oscillator Off, OSC, sine, Level 70 %, Octave 0, Tune centre, Fine 0, PW 0, right after Filter Type",
          [ent.get(i) for i in (0x1F0, 0x1F1, 0x1F2, 0x1F3, 0x1DC, 0x1DD, 0x1DE, 0x1DF)] == [0, 0, 0, 700, 3, 500, 0, 0]
          and ids[ids.index(0x1EF) + 1:ids.index(0x1EF) + 9] == [0x1F0, 0x1F1, 0x1F2, 0x1F3, 0x1DC, 0x1DD, 0x1DE, 0x1DF],
          [ent.get(i) for i in (0x1F0, 0x1F1, 0x1F2, 0x1F3, 0x1DC, 0x1DD, 0x1DE, 0x1DF)])
    check(f"{name}: Osc Track On (as 3.1.uo), stored right after Pulse W",
          ent.get(0x1E0) == 1 and ids.index(0x1E0) == ids.index(0x1DF) + 1, ent.get(0x1E0))
    check(f"{name}: Atk Slope 50 % (linear), Dec Slope 27 % (the earlier decay), right after Osc Track (3.1.v7)",
          (ent.get(0x1C0), ent.get(0x1C1)) == (500, 270) and ids.index(0x1C0) == ids.index(0x1E0) + 1
          and ids.index(0x1C1) == ids.index(0x1E0) + 2, (ent.get(0x1C0), ent.get(0x1C1)))
    e.call(0x08093E9C, STORE, P_FDECAY)
    check(f"{name}: stock lookup finds the new entries", e.uc.reg_read(UC_ARM_REG_R0) == 300)

# --- modulation: KEY and FENV in the Source list
names, codes = e.r32(0x0808CCC0), e.r32(0x0809A69C)
listed = [(e.cstr(e.r32(names + 4 * i)), e.r16(codes + 2 * i)) for i in range(12)]
check("Source list: stock eight, then KEY (0xe), FENV (1), AD (2) and OSC (3)", listed[:2] == [("none", 0), ("VEL", 0xD)] and
      listed[8:] == [("KEY", 0xE), ("FENV", 1), ("AD", 2), ("OSC", 3)], listed)
check("all five list-table references point at the new tables",
      e.r32(0x080B6964) == names and e.r32(0x080B696C) == codes and e.r32(0x080B7B00) == codes)
check("list length 12 at the registration and both screen loops",
      e.r16(0x0808CB3E) == 0x210C and e.r16(0x080B67CC) == 0x2B0C and e.r16(0x080B7994) == 0x200C)

PADA, VOICE, MSG, PADB = 0x24040000, 0x24041000, 0x24042000, 0x24043000
F32 = lambda a: struct.unpack("<f", e.uc.mem_read(a, 4))[0]


def route(handler, pad, dest, slot, src, amount):
    e.uc.mem_write(MSG, bytes(0xC) + struct.pack("<IIHh", dest, slot, src, amount))
    e.call(handler, pad, MSG)


def slots(param):
    """{slot: (source object, amount)} of a parameter object (slot 0 at +8)"""
    return {k: (e.r32(param + 8 + 8 * k), F32(param + 12 + 8 * k)) for k in range(3)}


e.uc.mem_write(PADA, bytes(0x1000))
e.uc.mem_write(VOICE, bytes(0x600))
route("fenv_mod_msg_a", PADA, 200, 1, 1, 500)                  # FENV -> Filter, slot 1, +50
rows = [(e.r16(PADA + 0x4F0 + 12 * i), e.r16(PADA + 0x4F2 + 12 * i), e.r8(PADA + 0x4F4 + 12 * i)) for i in range(e.r32(PADA + 0x54C))]
check("sample pad: FENV is kept as a voice row (dest 200, source 1, slot 1)", rows == [(200, 1, 1)], rows)
route("fenv_mod_msg_a", PADA, 0x5C, 0, 0xE, 1000)              # KEY -> Pitch: stock row
e.call("fenv_voice_copy", PADA, VOICE)
FENV_OBJ = VOICE + 0xA8 + 0x44
check("voice copy: Filter slot 1 = the voice's FENV object, amount 0.5",
      slots(VOICE + 0x2F8)[1] == (FENV_OBJ, 0.5), slots(VOICE + 0x2F8))
check("voice copy: KEY -> Pitch still installed by stock (voice + 0x8c)", slots(VOICE + 0x288)[0][0] == VOICE + 0x8C,
      slots(VOICE + 0x288))
e.uc.mem_write(VOICE + 0x2F8 + 0x2C, struct.pack("<f", 1.0))   # parameter range -1..1 as the voice constructor sets it
e.uc.mem_write(VOICE + 0x2F8 + 0x28, struct.pack("<f", -1.0))
e.uc.mem_write(FENV_OBJ + 4, struct.pack("<f", 0.8))           # envelope level
e.call(0x0806FB30, VOICE + 0x2F8)
got = struct.unpack("<f", struct.pack("<I", e.uc.reg_read(__import__("unicorn").arm_const.UC_ARM_REG_S0)))[0]
check(f"stock modulated read of Filter: 0.5 x envelope 0.8 = {got:.2f}", abs(got - 0.4) < 1e-6, got)
route("fenv_mod_msg_a", PADA, 200, 1, 0xD, 300)                # same slot -> VEL
e.call("fenv_voice_copy", PADA, VOICE)
check("switching the slot to VEL replaces FENV", slots(VOICE + 0x2F8)[1][0] == VOICE + 0x84, slots(VOICE + 0x2F8))
route("fenv_mod_msg_a", PADA, 200, 1, 1, -250)
route("fenv_mod_msg_a", PADA, 200, 1, 0, 0)                    # none: row removed
n = e.r32(PADA + 0x54C)
check("Source none removes the FENV row", n == 1 and e.r16(PADA + 0x4F2) == 0xE, n)

# AD (source 2): the same path, its object at filter object + 0x40 (value at + 0x44)
e.uc.mem_write(PADA, bytes(0x1000))
e.uc.mem_write(VOICE, bytes(0x600))
route("fenv_mod_msg_a", PADA, 0x5C, 2, 2, 250)                 # AD -> Pitch, slot 2, +25
route("fenv_mod_msg_a", PADA, 200, 0, 1, 500)                  # FENV -> Filter alongside
rows = sorted((e.r16(PADA + 0x4F0 + 12 * i), e.r16(PADA + 0x4F2 + 12 * i), e.r8(PADA + 0x4F4 + 12 * i)) for i in range(e.r32(PADA + 0x54C)))
check("sample pad: AD kept as its own voice row (dest pitch 0x5c, source 2, slot 2) next to FENV",
      rows == [(0x5C, 2, 2), (200, 1, 0)], rows)
e.call("fenv_voice_copy", PADA, VOICE)
AD_OBJ = VOICE + 0xA8 + 0x40
check("voice copy: Pitch slot 2 = the voice's AD object (filter object + 0x40), amount 0.25; FENV untouched",
      slots(VOICE + 0x288)[2] == (AD_OBJ, 0.25) and slots(VOICE + 0x2F8)[0] == (FENV_OBJ, 0.5),
      (slots(VOICE + 0x288), slots(VOICE + 0x2F8)))
e.uc.mem_write(VOICE + 0x288 + 0x2C, struct.pack("<f", 10.0))
e.uc.mem_write(VOICE + 0x288 + 0x28, struct.pack("<f", -10.0))
e.uc.mem_write(AD_OBJ + 4, struct.pack("<f", 0.6))             # AD level (filter object + 0x44)
e.call(0x0806FB30, VOICE + 0x288)
got = struct.unpack("<f", struct.pack("<I", e.uc.reg_read(__import__("unicorn").arm_const.UC_ARM_REG_S0)))[0]
check(f"stock modulated read of Pitch: 0.25 x AD 0.6 = {got:.3f}", abs(got - 0.15) < 1e-6, got)
route("fenv_mod_msg_a", PADA, 0x5C, 2, 0, 0)
check("Source none removes the AD row", e.r32(PADA + 0x54C) == 1 and e.r16(PADA + 0x4F2) == 1, e.r32(PADA + 0x54C))

e.uc.mem_write(PADB, bytes(0x1000))
route("fenv_mod_msg_b", PADB, 200, 2, 1, -400)                 # clip / slicer pad: FENV -> Filter, slot 2, -40
v0, v1 = slots(PADB + 0x448)[2], slots(PADB + 0x858)[2]
check("clip / slicer: both voices' Filter slot 2 = their own FENV object, amount -0.4",
      v0 == (PADB + 0x3AC + 0x44, f32(-0.4)) and v1 == (PADB + 0x7BC + 0x44, f32(-0.4)), (v0, v1))
route("fenv_mod_msg_b", PADB, 0x62, 1, 2, 700)                 # clip / slicer: AD -> Pan, slot 1, +70
a0, a1 = slots(PADB + 0x26C)[1], slots(PADB + 0x26C + 0x410)[1]
check("clip / slicer: both voices' Pan slot 1 = their own AD object (+0x40), amount 0.7 x the pan scale 2",
      a0[0] == PADB + 0x3AC + 0x40 and a1[0] == PADB + 0x7BC + 0x40 and abs(a0[1] - 1.4) < 1e-6 and abs(a1[1] - 1.4) < 1e-6,
      (a0, a1))
route("fenv_mod_msg_b", PADB, 0x11, 0, 0xE, 1000)              # KEY -> Res: stock
check("clip / slicer: KEY -> Res still routed by stock (pad + 0x2b0)", slots(PADB + 0x484)[0][0] == PADB + 0x2B0)

# --- the stock parameter getter reads every new parameter from the pad record (none is intercepted as a hidden switch)
APPB, REFB, OUT = 0x24010000, 0x24046000, 0x24046100
store = APPB + 0x1840 + 1 * 0xF0 + 2 * 0x30
ARRB = 0x24052000
ours = [P_FTYPE, P_FATTACK, P_FDECAY, P_FSUSTAIN, P_FRELEASE, P_FDEPTH, 0x1E7, 0x1E8, 0x1EC, 0x1ED, 0x1C0, 0x1C1]
e.uc.mem_write(ARRB, b"".join(struct.pack("<HHi", pid, 0, 100 + k) for k, pid in enumerate(ours)))
e.w32(store + 4, ARRB)
e.uc.mem_write(store + 10, struct.pack("<H", len(ours)))
e.uc.mem_write(REFB, struct.pack("<IH", 0, 1 << 4 | 2))
got = {}
for pid in ours:
    e.w32(OUT, 0xDEAD)
    e.call(0x08099504, APPB, REFB, pid, OUT)
    got[hex(pid)] = e.r32(OUT)
check("stock getter (FUN_08099504) returns each new parameter's stored value",
      got == {hex(pid): 100 + k for k, pid in enumerate(ours)}, got)
e.uc.mem_write(APPB + 0x8CC7, b"\x01")
e.call(0x08099504, APPB, REFB, 0x1E5, OUT)
check("(0x1e5, Filter Release's old id, is the hidden Keys switch: the getter returns app+0x8cc7, not the record)",
      e.r32(OUT) == 1 and P_FRELEASE != 0x1E5)


# (3.1.v7) the LFO's Depth fixed at 100 %: the stock LFO update (FUN_0806f108) multiplies its wave by the modulated
# Depth (FUN_0806fb30, now not called); with Depth at 41 % its output is the wave itself
from unicorn.arm_const import UC_ARM_REG_S0 as _S0
LFOO, LPAR = 0x24060000, 0x24061000
depth_reads = []
e.stubs[0x080705E8] = lambda: (e.uc.reg_write(_S0, struct.unpack("<I", struct.pack("<f", -0.37))[0]), e.ret())
e.stubs[0x0806FB30] = lambda: (depth_reads.append(1), e.uc.reg_write(_S0, struct.unpack("<I", struct.pack("<f", 0.41))[0]), e.ret())
e.w32(LFOO + 4, LPAR)
e.call(0x0806F108, LFOO)
out = struct.unpack("<f", e.uc.mem_read(LFOO + 0x3C, 4))[0]
check(f"LFO Depth fixed at 100 %: output = the wave ({out:.2f}), the Depth knob not read", abs(out + 0.37) < 1e-6 and not depth_reads,
      (out, depth_reads))
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
