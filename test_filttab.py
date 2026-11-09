"""Filt tab under Unicorn: tab bars, the Filt page list, grid-or-list tests, re-entry clamp, Main page tables.

Real firmware runs for: the patched grid tests inside FUN_080b886c and FUN_080b8898, the re-entry clamp (patched, and
the stock one from the unpatched image for comparison), the pad record lookup and the settings lookup.
Stubbed (recorded): button set-id / set-label, tab bar insert, list clear / add, the stock page-list function,
the grid and list refresh calls.
NOT checked: what the screen draws, touch and encoder handling on the device (hardware).
"""
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R2, UC_ARM_REG_SP

from emu import RET, STACK, Emu

IMG = "out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
stock = Emu("firmware/BLACKBOX-3.1.9.bin", "out/cave.elf")
P_FILTER, P_RES = 200, 0x11
P_FTYPE, P_FATTACK, P_FDECAY, P_FSUSTAIN, _UNUSED, P_FDEPTH = range(0x1E1, 0x1E7)
P_FRELEASE = 0x1EB                                  # 0x1e5 is a hidden stock Keys switch
P_FMORPH = 0x1E9
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


# --- tab bars
BAR, SLOTS, VTBL = 0x24040000, 0x24041000, 0x24045000
SET_ID = 0x0807FF00                                  # a stub address for the button's set-id method
e.uc.mem_write(SET_ID, b"\x70\x47")                  # bx lr (never reached: stubbed)
events = []
e.stub(SET_ID, lambda: events.append(("id", (e.arg(0) - SLOTS) // 0xA0, e.arg(1))))
e.stub(0x080A3DEC, lambda: events.append(("label", (e.arg(0) - SLOTS) // 0xA0, e.cstr(e.arg(1)))))
e.stub(0x080C4ED8, lambda: events.append(("add", (e.arg(1) - SLOTS) // 0xA0, e.r16(BAR + 0x36))))
e.w32(VTBL + 0x24, SET_ID | 1)
for s in range(6):
    e.w32(SLOTS + s * 0xA0, VTBL)
names = ["Main", "Pos", "Mod", "Gran", "Conf", "Filt"]       # LFO is shown as Mod; tab 3 is Osc on bars 0 and 2
# bar 0 is built without Osc (filt_bar_show adds it for sample pads, below); multisample (bar 2) has it always
want_tabs = {0: [0, 5, 1, 2, 4], 1: [0, 5, 1, 2, 3, 4], 2: [0, 3, 5, 2, 4]}
for bar in range(3):
    events.clear()
    e.call("filt_tabs", BAR, SLOTS + 4 * 0xA0, bar)
    ids = {s: v for k, s, v in events if k == "id"}
    labels = {s: v for k, s, v in events if k == "label"}
    added = [s for k, s, _ in events if k == "add"]
    counts = {c for k, _, c in events if k == "add"}
    want_names = dict(enumerate(names)) if bar == 1 else {**dict(enumerate(names)), 3: "Osc"}
    check(f"bar {bar}: all six buttons named (ids 0x12f..0x134, Main, Pos, Mod (was LFO), {want_names[3]}, Conf, Filt)",
          ids == {s: 0x12F + s for s in range(6)} and labels == want_names, (ids, labels))
    shown = list(reversed(added))                    # the bar places the first insert rightmost
    check(f"bar {bar}: on screen " + " ".join(want_names[t] for t in shown), shown == want_tabs[bar], shown)
    check(f"bar {bar}: count {len(want_tabs[bar])} set before the first insert", counts == {len(want_tabs[bar])}, counts)

# --- filt_bar_show: bar 0 (sample, clip, slicer) gets the Osc tab only while a sample pad is shown
SCREEN = 0x24060000
SBAR, SSLOT0 = SCREEN + 0xF6D0, SCREEN + 0x104F8 - 0x3C0
SSTORE, SARR = SCREEN + 0x7D8, 0x24068000
shows, unlinks = [], []
e.stub(0x080B8724, lambda: shows.append(e.arg(1)))
e.stub(0x080AEC62, lambda: (unlinks.append((e.arg(1) - SSLOT0) // 0xA0), e.w32(e.arg(1) + 0x2C, 0)))
e.stub(0x080C4ED8, lambda: (events.append(("add", (e.arg(1) - SSLOT0) // 0xA0, e.r16(e.arg(0) + 0x36))),
                            e.w32(e.arg(1) + 0x2C, e.arg(0))))
for t in range(6):
    e.w32(SSLOT0 + t * 0xA0, VTBL)
    e.w32(SSLOT0 + t * 0xA0 + 0x2C, 0)


def show(mode, bar=0):
    e.uc.mem_write(SARR, struct.pack("<HHi", 0x8B, 0, mode))
    e.w32(SSTORE + 4, SARR)
    e.uc.mem_write(SSTORE + 10, struct.pack("<H", 1))
    events.clear(), shows.clear(), unlinks.clear()
    e.call("filt_bar_show", SCREEN, bar)
    return list(reversed([s for k, s, _ in events if k == "add"])), list(unlinks), list(shows)


events.clear()
e.call("filt_tabs", SBAR, SSLOT0 + 4 * 0xA0, 0)                          # bar 0 as the screen builds it: no Osc
for t in range(6):                                                       # (the stub add above set the parents)
    pass
added, gone, shown_bar = show(0)
check("bar 0, sample pad: laid out again with Osc: Main Osc Filt Pos Mod Conf, then shown",
      added == [0, 3, 5, 1, 2, 4] and sorted(gone) == [0, 1, 2, 4, 5] and shown_bar == [0], (added, gone, shown_bar))
added, gone, shown_bar = show(0)
check("bar 0, the next sample pad: already right, left alone", added == [] and gone == [] and shown_bar == [0], (added, gone))
added, gone, shown_bar = show(1)
check("bar 0, clip pad: Osc taken out again: Main Filt Pos Mod Conf",
      added == [0, 5, 1, 2, 4] and sorted(gone) == [0, 1, 2, 3, 4, 5], (added, gone))
added, gone, shown_bar = show(2)
check("bar 0, slicer pad: no Osc, left alone", added == [] and gone == [], (added, gone))
added, gone, shown_bar = show(3, bar=1)
check("granular (bar 1): never touched", added == [] and gone == [] and shown_bar == [1], (added, gone, shown_bar))
e.stub(0x080C4ED8, lambda: events.append(("add", (e.arg(1) - SLOTS) // 0xA0, e.r16(BAR + 0x36))))

# --- the Filt page
APP = 0x24010000
REF = 0x24046000
calls = []
e.stub(0x080A4FC2, lambda: calls.append(("clear",)))
e.stub(0x080A5038, lambda: calls.append(("add", e.arg(1), struct.unpack("<i", struct.pack("<I", e.arg(2)))[0])))
e.stub(0x08098D40, lambda: calls.append(("stock", e.arg(3))), value=1)


def pad_record(row, col, values):
    store = APP + 0x1840 + row * 0xF0 + col * 0x30
    arr = 0x24050000 + (row * 5 + col) * 0x200
    e.uc.mem_write(arr, b"".join(struct.pack("<HHi", i, 0, v) for i, v in values.items()))
    e.w32(store + 4, arr)
    e.uc.mem_write(store + 10, struct.pack("<H", len(values)))


vals = {4: 800, P_FILTER: -250, P_RES: 640, P_FMORPH: 620, P_FDEPTH: -300, P_FATTACK: 10, P_FDECAY: 20, P_FSUSTAIN: 30,
        P_FRELEASE: 40, 0x8B: 0, 0x1EC: 150, 0x1ED: 450, 0x1EE: 1}
pad_record(2, 1, vals)
e.uc.mem_write(REF, struct.pack("<IH", 0, 2 << 4 | 1))   # pad ref: +4 = row << 4 | col, class 0
calls.clear()
e.call("filt_page", APP, REF, 0x24047000, 5)
want = [("clear",)] + [("add", i, vals[i]) for i in (P_FILTER, P_RES, P_FMORPH, P_FDEPTH, P_FATTACK, P_FDECAY, P_FSUSTAIN, P_FRELEASE)]
check("Filt page: Filter, Res, Morph, Depth / Attack, Decay, Sustain, Release, from the pad's record", calls == want, calls)
check("Filt page reports filled (1)", e.uc.reg_read(UC_ARM_REG_R0) == 1)

# the same page through the real list functions, with modulation routes in the record (they light the indicators)
del e.stubs[0x080A4FC2], e.stubs[0x080A5038]
LIST = 0x24047000
store = APP + 0x1840 + 2 * 0xF0 + 1 * 0x30
ROUTES = 0x24057000
routes = [(0x0D, 200, 0), (0x04, 0x11, 2), (0x01, 200, 1), (0x0D, 0x5C, 0)]      # VEL->Filter, LFO->Res, FENV->Filter, VEL->Pitch
e.uc.mem_write(ROUTES, b"".join(struct.pack("<IHHhH", 0, src, dest, slot, 0) for src, dest, slot in routes))
e.w32(store + 0x10, ROUTES)
e.uc.mem_write(store + 0x14, struct.pack("<H", len(routes)))
e.w32(store + 0x20, 0xA1B2C3D4)
e.w32(store + 0x24, 0x01020304)
e.uc.mem_write(LIST, bytes(0x260))
e.call("filt_page", APP, REF, LIST, 5)
got = {}
for i in range(e.r32(LIST)):
    pid = e.r16(LIST + 4 + 12 * i)
    got[pid] = tuple(e.r16(LIST + 12 * i + 6 + 2 * k) for k in range(3))   # sources in slots 0, 1, 2 (+6, +8, +10)
check("Filt page, real list: Filter's slots carry VEL and FENV, Res's slot 2 carries LFO (modulation indicators)",
      got.get(200) == (0x0D, 0x01, 0) and got.get(0x11) == (0, 0, 0x04), got)
check("Filt page, real list: knobs without routes have none (Morph, Attack)",
      got.get(P_FMORPH) == (0, 0, 0) and got.get(P_FATTACK) == (0, 0, 0), (got.get(P_FMORPH), got.get(P_FATTACK)))
check("Filt page, real list: the record's two trailing words copied (+0x248, +0x24c) as the stock pad pages do",
      e.r32(LIST + 0x248) & 0xFFFFFFFF == 0xA1B2C3D4 and e.r32(LIST + 0x24C) == 0x01020304)
e.w32(store + 0x10, 0)
e.uc.mem_write(store + 0x14, struct.pack("<H", 0))
e.stub(0x080A4FC2, lambda: calls.append(("clear",)))
e.stub(0x080A5038, lambda: calls.append(("add", e.arg(1), struct.unpack("<i", struct.pack("<I", e.arg(2)))[0])))
for tab in range(5):
    calls.clear()
    e.call("filt_page", APP, REF, 0x24047000, tab)
    if tab == 2:
        check("tab 2 (Mod): the stock LFO page, then AD Atk, AD Decay, Atk Slope, Dec Slope from the pad's record",
              calls == [("stock", 2), ("add", 0x1EC, vals.get(0x1EC, 0)), ("add", 0x1ED, vals.get(0x1ED, 0)),
                        ("add", 0x1C0, vals.get(0x1C0, 0)), ("add", 0x1C1, vals.get(0x1C1, 0))], calls)
    elif tab == 3:
        osc_ids = (0x1F2, 0x1F3, 0x1DC, 0x1DD, 0x1DE, 0x1DF, 0x1F0, 0x1E0)
        check("tab 3 of a sample pad: the Osc page: Wave, Level, Octave, Tune / Fine, Pulse W, Osc, Osc Track (no "
              "OSC/MOD: the oscillator only modulates; S.1: Osc Track from the Conf tab)",
              calls == [("clear",)] + [("add", i, vals.get(i, 0)) for i in osc_ids], calls)
    else:
        check(f"tab {tab}: stock page list", calls == [("stock", tab)], calls)
for kind, what in ((0x40, "global settings"), (0x41, "kind 0x41"), (0x0100 | 0x21, "an FX cell")):
    e.uc.mem_write(REF + 4, struct.pack("<H", kind))
    calls.clear()
    e.call("filt_page", APP, REF, 0x24047000, 5)
    check(f"tab 5 of {what}: left to stock", calls == [("stock", 5)], calls)
    calls.clear()
    e.call("filt_page", APP, REF, 0x24047000, 2)
    check(f"tab 2 of {what}: left to stock (no AD knobs)", calls == [("stock", 2)], calls)

# --- grid or list: the helpers' flags, then the real patched code paths
for t in range(6):
    for fn, reg in (("filt_is_list_r2", UC_ARM_REG_R2), ("filt_is_list_r3", __import__("unicorn").arm_const.UC_ARM_REG_R3)):
        e.uc.reg_write(reg, t)
        e.uc.reg_write(UC_ARM_REG_SP, STACK)
        e.uc.reg_write(UC_ARM_REG_LR, RET | 1)
        e.uc.emu_start(e.sym[fn] | 1, RET)
        z = (e.uc.reg_read(UC_ARM_REG_CPSR) >> 30) & 1
        check(f"{fn}: tab {t} ({names[t]}) is a {'list' if t in (1, 4) else 'grid'} tab", z == (t in (1, 4)), z)

SCREEN = 0x24000000
refresh = []
e.stub(0x080A82AC, lambda: refresh.append("grid"))
e.stub(0x080B9D20, lambda: refresh.append("list"))
for t in range(6):
    e.w32(SCREEN + 0xF6CC, t)
    refresh.clear()
    e.call(0x080B886C, SCREEN)
    check(f"FUN_080b886c refreshes the {'list' if t in (1, 4) else 'grid'} on tab {t}", refresh == ["list" if t in (1, 4) else "grid"], refresh)
for t in range(6):
    e.w32(SCREEN + 0xF6CC, t)
    e.uc.mem_write(SCREEN + 0xD80, b"\x55")
    e.uc.mem_write(SCREEN + 0xA618, b"\x55")
    e.uc.reg_write(UC_ARM_REG_R0, SCREEN)
    e.uc.reg_write(UC_ARM_REG_SP, STACK)
    e.uc.reg_write(UC_ARM_REG_LR, RET | 1)
    e.uc.emu_start(0x080B8898 | 1, 0x080B88CE)            # up to the two visibility stores
    grid = (e.r8(SCREEN + 0xD80), e.r8(SCREEN + 0xA618))
    want_v = (0, 1) if t in (1, 4) else (1, 0)
    check(f"FUN_080b8898 tab {t}: grid shown {grid[0]}, list shown {grid[1]}", grid == want_v, grid)

# --- re-entry clamp: same as stock for every stock tab, plus Filt for every pad mode
def clamp(emu, state, mode):
    store = APP + 0x1840 + 0xF0 + 0x30
    arr = 0x24058000
    emu.uc.mem_write(arr, struct.pack("<HHi", 0x8B, 0, mode))
    emu.w32(store + 4, arr)
    emu.uc.mem_write(store + 10, struct.pack("<H", 1))
    emu.uc.mem_write(REF, struct.pack("<IH", 0, 1 << 4 | 1))
    emu.call(0x080991A8, APP, state, REF)
    return emu.uc.reg_read(UC_ARM_REG_R0)


diff = []
for mode in (-1, 0, 1, 2, 3, 4):
    for state in range(0x10, 0x22):
        a, b = clamp(e, state, mode), clamp(stock, state, mode)
        if a != b:
            diff.append((mode, hex(state), hex(a), hex(b)))
check("clamp: identical to stock except Filt (0x1d) kept for pad modes 0..3 and Osc (0x1b) for sample pads",
      sorted(diff) == sorted([(m, "0x1d", "0x1d", "0x18") for m in (0, 1, 2, 3)] + [(0, "0x1b", "0x1b", "0x18")]), diff)

# --- the Filter knob's number: 0..100 %, display only, through the real knob-cell formatter
CELL = 0x24048000
shown = []
e.stub(0x080C3B98, lambda: shown.append(e.cstr(e.arg(1))))


def knob_text(pid, ptype, value):
    e.uc.mem_write(CELL, bytes(0x400))
    e.uc.mem_write(CELL + 0x94, struct.pack("<HBB", pid, ptype, 0))
    e.w32(CELL + 0x98, value)
    e.uc.mem_write(CELL + 0x3C8, b"\x01\x00")          # the cell shows its value
    shown.clear()
    e.call("filt_knob_text", CELL, 1)
    return shown[-1] if shown else None, e.r32(CELL + 0x98)


cases = {-1000: "0.0%", -500: "25.0%", 0: "50.0%", 500: "75.0%", 1000: "100.0%"}
got = {v: knob_text(200, 9, v) for v in cases}
check("Filter knob shows 0.0% .. 100.0% (far left .. far right)", {v: t for v, (t, _) in got.items()} == cases, got)
check("Filter's stored value is unchanged after drawing", all(back == v for v, (_, back) in got.items()), got)
check("other bipolar knobs still show -100..100 (Pan -50.0%, Depth -30.0%)",
      knob_text(0x62, 9, -500)[0] == "-50.0%" and knob_text(0x1E6, 9, -300)[0] == "-30.0%",
      (knob_text(0x62, 9, -500), knob_text(0x1E6, 9, -300)))
check("knob-cell formatter calls go through the wrapper (3 sites)",
      all(e.r16(a) != stock.r16(a) for a in (0x080A957E, 0x080A965E, 0x080A9704)))

# --- Morph is a modulation target: the 28-id stock list + Morph, at every place that reads it
targets = e.r32(0x080B8924) & 0xFFFFFFFF
ids = list(struct.unpack("<32H", e.uc.mem_read(targets, 64)))
stock_ids = list(struct.unpack("<28H", stock.uc.mem_read(0x080F12BC, 56)))
check("modulation targets: the stock 28 ids, then Morph (0x1e9) and the oscillator's Pulse W, Level, Tune (not Wave)",
      ids == stock_ids + [0x1E9, 0x1DF, 0x1F3, 0x1DD], [hex(i) for i in ids])
check("both references and all three lengths updated (32 ids, end = start + 64)",
      e.r32(0x080B8BF8) & 0xFFFFFFFF == targets and e.uc.mem_read(0x080B88D6, 4) == bytes.fromhex("03f14001")
      and e.r16(0x080B896A) == 0x2220 and e.r16(0x080B8980) == 0x2220)
SCREEN2 = 0x24000000
for pid, want in ((0x1E9, 1), (200, 1), (P_FATTACK, 0), (0x1E1, 0)):
    e.uc.mem_write(SCREEN2 + 0xF6CC, struct.pack("<I", 5))
    e.stub(0x080B886C, lambda: e.ret(pid))                 # the focused knob's parameter
    e.uc.reg_write(UC_ARM_REG_R0, SCREEN2)
    e.uc.reg_write(UC_ARM_REG_SP, STACK)
    e.uc.reg_write(UC_ARM_REG_LR, RET | 1)
    e.uc.emu_start(0x080B8898 | 1, 0x080B88F8)            # up to where it keeps "is a modulation target" in r3
    got = e.uc.reg_read(__import__("unicorn").arm_const.UC_ARM_REG_R3)
    check(f"focused {hex(pid)}: modulation button {'opens' if want else 'stays off'} (real FUN_080b8898)", got == want, got)

# --- tab press range, Main tables
check("tab press: ids 0x12f..0x134 accepted (cmp r3,#5)", e.r16(0x080B9496) == 0x2B05)
mains = [struct.unpack("<8H", e.uc.mem_read(a, 16)) for a in
         (0x080EFC18, 0x080EFAB0, 0x080EF948, 0x080EF7E0, 0x080EF510, 0x080EF3A8, 0x080EF240, 0x080EF0D8, 0x080EEF70)]
check("Main tab in all nine tables: Level, Pitch, Pan, Saturation / Attack, Decay, Sustain, Release (no Filter, Res)",
      all(m == (4, 0x5C, 0x62, 0xDB, 0x3C, 0x3E, 0x3F, 0x40) for m in mains), mains)


BUTTONS = (0x1F0, 0x1F1, 0x0C, 0x0D)                   # type-4 buttons: Osc, (OSC/MOD); stock Beat Sync, Key Trig


def rows_stay(ids):
    """The grid's own rule (FUN_080a87b6): after a refresh it leaves the bottom row if slots 2-3 hold no knob and the
    top row if slots 0-1 hold none (id 1 = blank; a type-4 button is no knob either). Both halves need a knob for both
    rows to stay selectable."""
    knob = [i not in (0, 1) and i not in BUTTONS for i in ids]
    return (knob[0] or knob[1]) and (knob[2] or knob[3])


check("Main tab: both knob rows stay selectable after a value change", all(rows_stay(m) for m in mains), mains)

# (3.1.v7) the Mod tab from the stock LFO page's real entries: Waveform 8, Rate 9 (or the synced 10), Depth 0xb,
# Beat Sync 0xc, Key Trig 0xd, each with modulation marks; reordered Waveform, Trig, Rate, Beat, Depth left out
def mod_page(rate_id):
    def stock_lfo():
        lst = e.arg(2)
        ent = [(8, 3, 0x0E), (rate_id, 400, 0x0D), (0x0B, 410, 0x02), (0x0C, 1, 0), (0x0D, 1, 0)]
        e.w32(lst, len(ent))
        for k, (pid, v, mark) in enumerate(ent):
            e.uc.mem_write(lst + 4 + 12 * k, struct.pack("<HHHHi", pid, mark, 0, 0, v))
        e.ret(1)
    e.stubs[0x08098D40] = stock_lfo
    del e.stubs[0x080A5038]
    e.uc.mem_write(0x24047000, bytes(0x260))
    e.call("filt_page", APP, REF, 0x24047000, 2)
    n = e.r32(0x24047000)
    out = [(e.r16(0x24047000 + 4 + 12 * k), e.r16(0x24047000 + 6 + 12 * k), e.r32(0x24047000 + 12 + 12 * k)) for k in range(n)]
    e.stub(0x080A5038, lambda: calls.append(("add", e.arg(1), struct.unpack("<i", struct.pack("<I", e.arg(2)))[0])))
    e.stub(0x08098D40, lambda: calls.append(("stock", e.arg(3))), value=1)
    return out


for rid in (9, 10):
    got = mod_page(rid)
    ids = [g[0] for g in got]
    check(f"Mod tab (rate {rid}): Waveform, Trig, Rate, Beat / AD Atk, AD Decay, Atk Slope, Dec Slope; no Depth; the "
          "stock entries keep their values and modulation marks",
          ids == [8, 0x0D, rid, 0x0C, 0x1EC, 0x1ED, 0x1C0, 0x1C1] and got[0][1:] == (0x0E, 3) and got[2][1:] == (0x0D, 400),
          got)
    check(f"Mod tab (rate {rid}): both knob rows stay selectable (a knob in slots 0-1 and in 2-3)", rows_stay(ids), ids)
filt = struct.unpack("<8H", e.uc.mem_read(e.sym["filt_ids"], 16))
check("Filt tab: both knob rows stay selectable after a value change", rows_stay(filt), filt)
osc = struct.unpack("<8H", e.uc.mem_read(e.sym["osc_ids"], 16))
check("Osc tab: both knob rows stay selectable after a value change (the buttons are not in slots 0-1)",
      rows_stay(osc), osc)
check("rule check: the 3.1.v Osc layout (Osc, OSC/MOD first) fails it", not rows_stay((0x1F0, 0x1F1, 0x1F2, 0x1F3)))

print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
