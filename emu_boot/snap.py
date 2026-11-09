"""Shared loader: build the emulator and restore a snapshot."""
from boot import *
import m7, boot

def restore(path='snap_kstart.pkl', verbose=False):
    m = make(verbose)
    ex = m7.load(m, path)
    m.tick[0] = ex['tick']
    m.tasks = ex.get('tasks', [])
    return m

def task_tcbs(m):
    out = {}
    for base, size in ((0x24000000, 0x80000), (0x20000000, 0x20000)):
        mem = bytes(m.uc.mem_read(base, size))
        for t in m.tasks + [dict(name='IDLE'), dict(name='Tmr Svc')]:
            nm = t['name'].encode() + b'\0'
            i = mem.find(nm)
            while i >= 0:
                tcb = base + i - 0x34
                if i >= 0x34 and base <= m.r32(tcb) < base + size:     # pxTopOfStack in same RAM
                    out[t['name']] = tcb
                i = mem.find(nm, i + 1)
    return out

def task_where(m, tcb):
    """PC/LR stacked for a switched-out task."""
    if tcb == m.r32(m.pxtcb):
        return 'running'
    sp = m.r32(tcb)
    exc = m.r32(sp + 32)
    sp += 36 + (64 if not exc & 0x10 else 0)
    lr, pc = m.r32(sp + 20), m.r32(sp + 24)
    # walk a few return addresses from the stack for context
    chain = []
    for i in range(0, 0x100, 4):
        v = m.r32(sp + 32 + i)
        if 0x08040000 < v < 0x080f0000 and v & 1:
            chain.append(fname(v - 1))
    return f"pc={fname(pc)} lr={fname(lr)} stack: {' < '.join(chain[:8])}"
