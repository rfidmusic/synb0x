"""Cortex-M7 shim on top of Unicorn's A-profile Thumb core (UC_CPU_ARM_MAX, which has FPv5 incl. f64).

Unicorn's M-profile cores lack FPv5-D16, so we run A-profile and model the M-profile bits in Python:
  * MRS/MSR of special regs (MSP, PSP, CONTROL, BASEPRI, PRIMASK, IPSR...), CPSID/CPSIE  -> per-address code hooks
  * exception entry (extended FP frame) / EXC_RETURN exit                                 -> outer run loop
  * SVC, PendSV (ICSR write), SysTick (every TICK_INSNS instructions)
  * MMIO (0x40000000-0x60000000, 0xE0000000-0xE0100000) register file + spin detection: a PC that keeps
    re-reading the same register gets a cycling sequence of values so HAL polling loops terminate.
"""
import struct
from collections import defaultdict

from unicorn import (UC_ARCH_ARM, UC_HOOK_CODE, UC_HOOK_INTR, UC_HOOK_MEM_UNMAPPED, UC_MODE_THUMB, Uc, UcError)
from unicorn.arm_const import *

BASE = 0x08040000
FW = "/Users/tony/OpenWork Chat/blackbox/blackbox-mod/firmware/BLACKBOX-3.1.9.bin"
EXC_PAGE = 0xFFFFF000
R = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
     UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_R12,
     UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC]
S = [getattr(__import__("unicorn.arm_const", fromlist=["x"]), f"UC_ARM_REG_S{i}") for i in range(32)]

MEM = [(0x00000000, 0x10000),      # ITCM
       (0x08000000, 0x200000),     # flash
       (0x1FF00000, 0x20000),      # system memory
       (0x20000000, 0x20000),      # DTCM
       (0x24000000, 0x80000),      # AXI SRAM
       (0x30000000, 0x48000),      # SRAM1-3
       (0x38000000, 0x10000),      # SRAM4
       (0x38800000, 0x1000),       # backup SRAM
       (0x90000000, 0x1000000),    # QSPI (unused?)
       (0xC0000000, 0x4000000),    # SDRAM
       (EXC_PAGE, 0x1000)]


class M7:
    TICK_INSNS = 100000

    def __init__(self, verbose=False):
        self.fw = open(FW, "rb").read()
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.ctl_set_cpu_model(UC_CPU_ARM_MAX)
        for a, n in MEM:
            uc.mem_map(a, n)
        uc.mem_write(BASE, self.fw)
        uc.reg_write(UC_ARM_REG_C1_C0_2, 0xF << 20)
        uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        self.verbose = verbose
        # M-profile state
        self.msp = self.psp = 0
        self.control = 0
        self.basepri = 0
        self.primask = 0
        self.faultmask = 0
        self.ipsr = []           # stack of active exception numbers
        self.pend = set()        # pending exception numbers
        self.stop_reason = None
        # MMIO
        self.regs = {}
        self.spin = defaultdict(int)
        self.mmio_log = defaultdict(int)
        self.rd_hooks = {}        # addr -> fn(value)->value
        self.wr_hooks = {}        # addr -> fn(value)
        self.no_spin = set()
        self.mtrace = None
        self.last_key, self.spin_c = None, 0
        uc.mmio_map(0x40000000, 0x20000000, self._mrd_p, None, self._mwr_p, None)
        uc.mmio_map(0xE0000000, 0x100000, self._mrd_c, None, self._mwr_c, None)
        self.wr_hooks[0xE000ED04] = self._icsr
        self.rd_hooks[0xE000ED04] = lambda v: (self.ipsr[-1] if self.ipsr else 0) | (0x10000000 if 14 in self.pend else 0)
        self.cyc = 0

        def cyccnt(v):
            self.cyc += 1000
            return self.cyc & 0xFFFFFFFF
        self.rd_hooks[0xE0001004] = cyccnt
        self.wr_hooks[0xE000ED08] = lambda v: setattr(self, "vtor", v)
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        uc.hook_add(UC_HOOK_INTR, self._intr)
        uc.hook_add(UC_HOOK_CODE, self._exc_ret, begin=EXC_PAGE, end=EXC_PAGE + 0xFFF)
        self.stubs = {}
        self._scan_sysinsns()
        self.insns = 0
        self.vtor = BASE
        self.fake_vec = {}
        self.unmapped = []

    # ------------------------------------------------------------------ helpers
    def r32(self, a):
        return struct.unpack("<I", self.uc.mem_read(a, 4))[0]

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def reg(self, n):
        return self.uc.reg_read(R[n])

    def setreg(self, n, v):
        self.uc.reg_write(R[n], v & 0xFFFFFFFF)

    def cstr(self, a, n=64):
        return bytes(self.uc.mem_read(a, n)).split(b"\0")[0].decode("latin1")

    def stub(self, addr, fn=None, value=None):
        """Replace the function at addr: fn(self) may return a value for r0."""
        addr &= ~1

        def h(uc, a, size, _):
            v = fn(self) if fn else None
            if v is None:
                v = value
            if v is not None:
                uc.reg_write(UC_ARM_REG_R0, v & 0xFFFFFFFF)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
        self.stubs[addr] = self.uc.hook_add(UC_HOOK_CODE, h, begin=addr, end=addr)

    def hook(self, addr, fn):
        """Observe (not replace) execution at addr."""
        addr &= ~1
        return self.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: fn(self), begin=addr, end=addr)

    def in_handler(self):
        return bool(self.ipsr)

    def psp_active(self):
        return not self.ipsr and (self.control & 2)

    # ------------------------------------------------------------------ MMIO
    def _mrd_p(self, uc, off, size, _):
        return self.mmio_read(0x40000000 + off, size)

    def _mrd_c(self, uc, off, size, _):
        return self.mmio_read(0xE0000000 + off, size)

    def _mwr_p(self, uc, off, size, value, _):
        self.mmio_write(0x40000000 + off, size, value)

    def _mwr_c(self, uc, off, size, value, _):
        self.mmio_write(0xE0000000 + off, size, value)

    SPIN_SEQ = (None, "inv", 0xFFFFFFFF, 0, None, "inv")

    def mmio_read(self, addr, size):
        w = addr & ~3
        sh = (addr & 3) * 8
        v = self.regs.get(w, 0)
        if w in self.rd_hooks:
            v = self.rd_hooks[w](v)
        pc = self.uc.reg_read(UC_ARM_REG_PC)
        key = w
        if key == self.last_key:
            self.spin_c += 1
        else:
            self.last_key, self.spin_c = key, 1
        c = self.spin_c
        self.mmio_log[w] += 1
        if c > 3 and w < 0xE0000000 and w not in self.no_spin:
            m = self.SPIN_SEQ[(c // 2) % len(self.SPIN_SEQ)]
            if m == "inv":
                v = ~v & 0xFFFFFFFF
            elif m is not None:
                v = m
        v = (v >> sh) & ((1 << (8 * size)) - 1)
        if self.mtrace is not None:
            self.mtrace.append(('R', pc, addr, v))
        return v

    def mmio_write(self, addr, size, value):
        w = addr & ~3
        sh = (addr & 3) * 8
        mask = ((1 << (8 * size)) - 1) << sh
        old = self.regs.get(w, 0)
        v = (old & ~mask) | ((value << sh) & mask)
        self.regs[w] = v
        if self.mtrace is not None:
            self.mtrace.append(('W', self.uc.reg_read(UC_ARM_REG_PC), addr, value))
        if w in self.wr_hooks:
            self.wr_hooks[w](v)

    def _unmapped(self, uc, access, addr, size, value, _):
        pc = uc.reg_read(UC_ARM_REG_PC)
        self.unmapped.append((pc, addr, access))
        if self.verbose or len(self.unmapped) < 20:
            print(f"  unmapped access {access} @{addr:08x} pc={pc:08x}")
        page = addr & ~0xFFF
        try:
            uc.mem_map(page, 0x1000)
            self.extra_pages = getattr(self, "extra_pages", []) + [page]
        except UcError:
            return False
        return True

    # ------------------------------------------------------------------ system instructions
    def _scan_sysinsns(self):
        fw = self.fw
        for o in range(0, len(fw) - 4, 2):
            h1 = fw[o] | fw[o + 1] << 8
            h2 = fw[o + 2] | fw[o + 3] << 8
            a = BASE + o
            if h1 == 0xF3EF and (h2 & 0xF000) == 0x8000:          # MRS Rd, sysm
                self.uc.hook_add(UC_HOOK_CODE, self._mrs, begin=a, end=a, user_data=((h2 >> 8) & 0xF, h2 & 0xFF))
            elif (h1 & 0xFFF0) == 0xF380 and (h2 & 0xFF00) == 0x8800:   # MSR sysm, Rn
                self.uc.hook_add(UC_HOOK_CODE, self._msr, begin=a, end=a, user_data=(h1 & 0xF, h2 & 0xFF))
            elif h1 in (0xB672, 0xB662, 0xB671, 0xB661):          # CPSID i / CPSIE i / f
                self.uc.hook_add(UC_HOOK_CODE, self._cps, begin=a, end=a, user_data=h1)

    def _xpsr(self):
        cpsr = self.uc.reg_read(UC_ARM_REG_CPSR)
        return (cpsr & 0xF8000000) | 0x01000000 | (self.ipsr[-1] if self.ipsr else 0)

    def _mrs(self, uc, a, size, ud):
        rd, sysm = ud
        sp = uc.reg_read(UC_ARM_REG_SP)
        v = {0: self._xpsr() & 0xF8000000, 1: self._xpsr() & 0xF80001FF, 3: self._xpsr(),
             5: self._xpsr() & 0x1FF, 6: self._xpsr() & 0x1FF, 7: self._xpsr() & 0x1FF,
             8: self.msp if self.psp_active() else sp,
             9: sp if self.psp_active() else self.psp,
             16: self.primask, 17: self.basepri, 18: self.basepri, 19: self.faultmask,
             20: self.control}.get(sysm, 0)
        self.setreg(rd, v)
        uc.reg_write(UC_ARM_REG_PC, (a + 4) | 1)

    def _msr(self, uc, a, size, ud):
        rn, sysm = ud
        v = self.reg(rn)
        if sysm == 8:
            if self.psp_active():
                self.msp = v
            else:
                uc.reg_write(UC_ARM_REG_SP, v)
        elif sysm == 9:
            if self.psp_active():
                uc.reg_write(UC_ARM_REG_SP, v)
            else:
                self.psp = v
        elif sysm == 16:
            self.primask = v & 1
        elif sysm == 17:
            self.basepri = v & 0xFF
            if self.basepri == 0 and self.pend:
                self._req_stop("unmask")
        elif sysm == 18:
            if v & 0xFF and (self.basepri == 0 or (v & 0xFF) < self.basepri):
                self.basepri = v & 0xFF
        elif sysm == 19:
            self.faultmask = v & 1
        elif sysm == 20:
            was = self.psp_active()
            self.control = v & 7
            now = self.psp_active()
            if was != now:
                sp = uc.reg_read(UC_ARM_REG_SP)
                if now:
                    self.msp, sp = sp, self.psp
                else:
                    self.psp, sp = sp, self.msp
                uc.reg_write(UC_ARM_REG_SP, sp)
        uc.reg_write(UC_ARM_REG_PC, (a + 4) | 1)

    def _cps(self, uc, a, size, h1):
        if h1 == 0xB672:
            self.primask = 1
        elif h1 == 0xB662:
            self.primask = 0
            if self.pend:
                self._req_stop("unmask")
        elif h1 == 0xB671:
            self.faultmask = 1
        else:
            self.faultmask = 0
        uc.reg_write(UC_ARM_REG_PC, (a + 2) | 1)

    def _icsr(self, v):
        self.regs[0xE000ED04] = 0
        if v & (1 << 28):
            self.pend.add(14)
            self._stop_next("pendsv")
        if v & (1 << 26):
            self.pend.add(15)
            self._stop_next("pendst")

    def _stop_next(self, why):
        """Stop before the next instruction (a stop from inside an MMIO callback re-executes the store)."""
        if getattr(self, "_oneshot", None) is not None:
            return
        first = [True]

        def cb(uc, a, size, _):
            if first[0]:          # the hook fires for the current instruction too on some versions
                first[0] = False
                if a == self._oneshot_pc:
                    return
            uc.hook_del(self._oneshot)
            self._oneshot = None
            self._req_stop(why)
        self._oneshot_pc = self.uc.reg_read(UC_ARM_REG_PC)
        self._oneshot = self.uc.hook_add(UC_HOOK_CODE, cb)

    def _req_stop(self, why):
        self.stop_reason = why
        self.uc.emu_stop()

    # ------------------------------------------------------------------ exceptions
    def _intr(self, uc, intno, _):
        if intno == 2:   # SVC
            self.pend.add(11)
            self._req_stop("svc")
        else:
            pc = uc.reg_read(UC_ARM_REG_PC)
            print(f"  intr {intno} at pc={pc:08x}")
            self._req_stop(f"intr{intno}")

    def _exc_ret(self, uc, a, size, _):
        self._req_stop("excret")

    def can_take(self, n):
        if self.primask:
            return n in (2, 3)   # NMI/HardFault
        if n in (11,):
            return True
        if self.ipsr:            # no nesting of PendSV/SysTick
            return False
        if self.basepri:
            return False         # PendSV/SysTick are lowest priority (0xF0)
        return True

    def enter(self, n):
        uc = self.uc
        sp = uc.reg_read(UC_ARM_REG_SP)
        thread = not self.ipsr
        on_psp = self.psp_active()
        sp -= 0x68                       # extended frame: 8 + 16 + fpscr + reserved = 26 words
        align = 0
        if sp & 4:
            sp -= 4
            align = 1
        regs = [uc.reg_read(R[i]) for i in (0, 1, 2, 3, 12, 14)]
        pc = uc.reg_read(UC_ARM_REG_PC)
        xpsr = self._xpsr() | (align << 9)
        words = regs + [pc & ~1, xpsr] + [uc.reg_read(S[i]) for i in range(16)] + \
            [uc.reg_read(UC_ARM_REG_FPSCR), 0]
        uc.mem_write(sp, struct.pack("<26I", *[w & 0xFFFFFFFF for w in words]))
        if on_psp:
            self.psp = sp
            uc.reg_write(UC_ARM_REG_SP, self.msp)
        else:
            uc.reg_write(UC_ARM_REG_SP, sp)
        exc = 0xFFFFFFE0 | (0 if not thread else 8) | (4 if on_psp else 0) | 1
        uc.reg_write(UC_ARM_REG_LR, exc)
        self.ipsr.append(n)
        h = self.fake_vec[n] if n in self.fake_vec else self.r32(self.vtor + 4 * n)
        uc.reg_write(UC_ARM_REG_PC, h | 1)

    def exit(self):
        uc = self.uc
        exc = uc.reg_read(UC_ARM_REG_PC) | 1       # 0xFFFFFFxD etc
        n = self.ipsr.pop()
        to_psp = bool(exc & 4)
        ext = not (exc & 0x10)
        if to_psp:
            self.msp = uc.reg_read(UC_ARM_REG_SP)
            sp = self.psp
            self.control |= 2
        else:
            sp = uc.reg_read(UC_ARM_REG_SP)
        nw = 26 if ext else 8
        w = struct.unpack(f"<{nw}I", uc.mem_read(sp, nw * 4))
        for i, r in enumerate((0, 1, 2, 3, 12, 14)):
            uc.reg_write(R[r], w[i])
        pc, xpsr = w[6], w[7]
        if ext:
            for i in range(16):
                uc.reg_write(S[i], w[8 + i])
            uc.reg_write(UC_ARM_REG_FPSCR, w[24])
        sp += nw * 4 + (4 if xpsr & 0x200 else 0)
        cpsr = uc.reg_read(UC_ARM_REG_CPSR)
        uc.reg_write(UC_ARM_REG_CPSR, (cpsr & 0x07FFFFFF) | (xpsr & 0xF8000000))
        uc.reg_write(UC_ARM_REG_SP, sp)
        if to_psp:
            self.psp = sp
        uc.reg_write(UC_ARM_REG_PC, pc | 1)

    # ------------------------------------------------------------------ run loop
    def run(self, pc, max_insns, until=None, chunk=None):
        """Run from pc for up to max_insns, delivering exceptions; returns when done/until reached."""
        chunk = chunk or self.TICK_INSNS
        uc = self.uc
        uc.reg_write(UC_ARM_REG_PC, pc | 1)
        done = 0
        since_tick = 0
        while done < max_insns:
            # deliver pending exceptions
            pcv = uc.reg_read(UC_ARM_REG_PC)
            if EXC_PAGE <= pcv <= 0xFFFFFFFF:
                self.exit()
                continue
            for n in sorted(self.pend):
                if self.can_take(n):
                    self.pend.discard(n)
                    self.enter(n)
                    break
            self.stop_reason = None
            start = uc.reg_read(UC_ARM_REG_PC)
            before = self.insns
            try:
                uc.emu_start(start | 1, until if until else 0xFFFFFFFF, count=chunk)
            except UcError as e:
                pcv = uc.reg_read(UC_ARM_REG_PC)
                print(f"  UcError {e} at pc={pcv:08x} lr={uc.reg_read(UC_ARM_REG_LR):08x}")
                return "error"
            # approximate: count chunk as executed unless stopped early
            n = chunk if self.stop_reason is None else 0
            done += n if n else 1
            since_tick += n if n else 2000
            self.insns += n
            pcv = uc.reg_read(UC_ARM_REG_PC)
            if until and (pcv & ~1) == (until & ~1):
                return "until"
            if self.stop_reason and self.stop_reason.startswith("halt"):
                return self.stop_reason
            if since_tick >= self.TICK_INSNS and self.systick_on:
                since_tick = 0
                self.pend.add(15)
        return "budget"

    systick_on = False


# ---------------------------------------------------------------------- snapshots
import pickle, zlib

ALLREGS = R[:15] + S + [UC_ARM_REG_CPSR, UC_ARM_REG_FPSCR]
for _i in range(16):
    ALLREGS.append(getattr(__import__("unicorn.arm_const", fromlist=["x"]), f"UC_ARM_REG_D{16 + _i}"))


def save(m, path, extra=None):
    uc = m.uc
    st = dict(regs=[uc.reg_read(r) for r in ALLREGS], pc=uc.reg_read(UC_ARM_REG_PC),
              mem={}, py=dict(msp=m.msp, psp=m.psp, control=m.control, basepri=m.basepri, primask=m.primask,
                              faultmask=m.faultmask, ipsr=list(m.ipsr), pend=set(m.pend), regs=dict(m.regs),
                              vtor=m.vtor, cyc=m.cyc, systick_on=m.systick_on), extra=extra)
    for a, n in MEM + [(p, 0x1000) for p in getattr(m, "extra_pages", [])]:
        st["mem"][a] = zlib.compress(bytes(uc.mem_read(a, n)), 1)
    pickle.dump(st, open(path, "wb"))


def load(m, path):
    st = pickle.load(open(path, "rb"))
    uc = m.uc
    for a, b in st["mem"].items():
        b = zlib.decompress(b)
        try:
            uc.mem_write(a, b)
        except UcError:
            uc.mem_map(a, len(b))
            uc.mem_write(a, b)
    for r, v in zip(ALLREGS, st["regs"]):
        uc.reg_write(r, v)
    uc.reg_write(UC_ARM_REG_PC, st["pc"] | 1)
    for k, v in st["py"].items():
        setattr(m, k, v)
    return st.get("extra")
