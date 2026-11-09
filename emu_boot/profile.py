"""Profile real audio blocks of the stock firmware (audio task: FUN_0804caa4 input + FUN_0804cb1c engine).

usage: profile.py [warmup_blocks] [profiled_blocks] [snapshot] [notes]
  notes: e.g. "36-51" -> note-on events (ch 0, vel 100) injected through FUN_080518dc before warm-up
"""
import sys, bisect, collections
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from unicorn import UC_HOOK_BLOCK
from audio import *

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
_binfo = {}

def binfo(m, a, size):
    """(instruction count, block ends in BL/BLX) for a translated block."""
    k = (a, size)
    if k not in _binfo:
        ins = list(md.disasm_lite(bytes(m.uc.mem_read(a, size)), a))
        call = bool(ins) and ins[-1][2] in ("bl", "blx")
        _binfo[k] = (len(ins) or 1, call)
    return _binfo[k]

def fidx(pc):
    return bisect.bisect_right(FADDR, pc) - 1

def fn_label(entry):
    i = fidx(entry)
    if i >= 0 and FADDR[i] == entry:
        return FUNCS[i][1]
    return f"sub_{entry:08x} (in {FUNCS[i][1]}+{entry - FADDR[i]:x})"

# the audio task's queue wait: stock FUN_08088756, or a Synb0x build's CPU meter wrapper (cpu_wait, from funcs.txt)
WAITS = {0x08088756} | {int(l.split()[0], 16) & ~1 for l in open(__file__.rsplit("/", 1)[0] + "/funcs.txt")
                        if len(l.split()) == 2 and l.split()[1] == "cpu_wait"}


class Prof:
    """Dynamic call-graph profiler: a block reached right after a BL/BLX is a function entry
    (catches helpers Ghidra did not split out); frames pop when execution reaches their return address."""
    def __init__(self, m):
        self.m = m
        self.active = False
        self.armed = False
        self.self_ = collections.Counter()
        self.incl = collections.Counter()
        self.calls = collections.Counter()
        self.isr = 0
        self.total = 0
        self.blocks = []
        m.uc.hook_add(UC_HOOK_BLOCK, self.blk)
        m.hook(0x0804caa4, self.start)

    def start(self, m):
        if self.armed and not self.active:
            self.active = True
            self.cur = 0
            # root frame: FUN_08041470 (audio task loop)
            self.stack = [(0x08041470, 0xFFFFFFFF, None)]
            self.prev_call = True      # this block (FUN_0804caa4 entry) is a call target
            self.pending_lr = m.uc.reg_read(UC_ARM_REG_LR) & ~1

    def blk(self, uc, a, size, _):
        if not self.active:
            return
        m = self.m
        if m.ipsr:
            self.isr += binfo(m, a, size)[0]
            return
        n, call = binfo(m, a, size)
        st = self.stack
        while len(st) > 1 and st[-1][2] == a:
            st.pop()
        if a in WAITS and st[-1][0] == 0x08041470:           # back to the queue wait (a mod: its cpu_wait): block done
            self.active = False
            self.blocks.append(self.cur)
            return
        if self.prev_call:
            st.append((a, uc.reg_read(UC_ARM_REG_SP), uc.reg_read(UC_ARM_REG_LR) & ~1))
            self.calls[a] += 1
        self.prev_call = call
        f = st[-1][0]
        self.self_[f] += n
        for e in {fr[0] for fr in st}:
            self.incl[e] += n
        self.total += n
        self.cur += n

if __name__ == "__main__":
    warm = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    nprof = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    m = setup(sys.argv[3] if len(sys.argv) > 3 else 'snap_loaded.pkl')
    install_events(m)
    p = Prof(m)
    if len(sys.argv) > 4:
        lo, hi = (int(x) for x in sys.argv[4].split('-'))
        for n in range(lo, hi + 1):
            note_on(m, 0, n)
    nsd = len(m.sd_log)
    k = 0
    for i in range(warm):
        dma_irq(m, k & 1); k += 1
        run_for(m, 2_000_000)
    p.armed = True
    for i in range(nprof):
        dma_irq(m, k & 1); k += 1
        run_for(m, 2_000_000)
    print(f"SD sectors read during run: {len(m.sd_log) - nsd}")
    print(f"profiled blocks: {len(p.blocks)}  instructions per block: {p.blocks}")
    tot = sum(p.blocks) / max(1, len(p.blocks))
    print(f"mean instructions per block (caa4+cb1c, excl. ISRs): {tot:.0f}   (ISR insns during blocks: {p.isr})")
    nb = max(1, len(p.blocks))
    print(f"self-sum check: {sum(p.self_.values()) / nb:.0f}")
    print("\nTop 25 by SELF instructions (per block):")
    for i, c in p.self_.most_common(25):
        print(f"  {c / nb:8.0f}  {100 * c / p.total:5.1f}%  calls/blk {p.calls[i] / nb:5.0f}  {fn_label(i)}")
    print("\nTop 25 by INCLUSIVE instructions (per block):")
    for i, c in p.incl.most_common(26):
        print(f"  {c / nb:8.0f}  {100 * c / p.total:5.1f}%  calls/blk {p.calls[i] / nb:5.0f}  {fn_label(i)}")
