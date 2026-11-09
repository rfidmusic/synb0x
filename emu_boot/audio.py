"""Restore the at-osKernelStart snapshot, run the real FreeRTOS scheduler, and drive the audio task
by injecting fake SAI-DMA half/full interrupts (calls the stock ISR helper FUN_08041534)."""
import sys, collections
from snap import *

PARAM = 0x24001f90
TRAMP = open(__file__.rsplit('/', 1)[0] + '/tramp.bin', 'rb').read()

def setup(path='snap_kstart.pkl', sdcard=True):
    m = restore(path)
    if sdcard:
        import sd
        sd.install(m, sd.build())
    m.uc.mem_write(0x100, TRAMP)
    m.fake_vec[200] = 0x101
    m.regs[0xE000E4B8] = 0x6060        # NVIC IPR for fake IRQs 184/185 (below configMAX_SYSCALL priority)
    m.uc.mem_write(0x200, open(__file__.rsplit('/', 1)[0] + '/tramp2.bin', 'rb').read())
    m.fake_vec[201] = 0x201
    m.blocks = 0
    m.in_block = False
    def cb_enter(m):
        m.in_block = True
    def cb_exit_hook(m):
        pass
    m.hook(0x0804cb1c, cb_enter)
    return m

def dma_irq(m, half):
    m.w32(0x1F0, half)
    m.pend.add(200)

def ui_frame(m):
    m.pend.add(201)

def run_for(m, insns):
    pc = m.uc.reg_read(UC_ARM_REG_PC)
    return m.run(pc, insns)

if __name__ == "__main__":
    m = setup()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    hits = collections.Counter()
    m.hook(0x0804cb1c, lambda m: hits.update(['cb1c']))
    m.hook(0x0804caa4, lambda m: hits.update(['caa4']))
    m.hook(0x08053164, lambda m: hits.update(['render']))
    run_for(m, 3_000_000)          # let tasks initialise
    for i in range(n):
        dma_irq(m, i & 1)
        run_for(m, 2_000_000)
        print(i, cur_task(m), dict(hits), flush=True)
    for nme, t in task_tcbs(m).items():
        print(nme, task_where(m, t))


# ---------------------------------------------------------------- MIDI-style engine events
APP = 0x2400a9c0
EVBUF = 0x400            # ITCM scratch: 0x18-byte engine event
RESUME = 0x300           # ITCM: Python hook restores the interrupted FUN_0804cb1c call

def install_events(m):
    """Queue engine events (the same struct FUN_0804cb1c builds from MIDI bytes and hands to FUN_080518dc).
    They are injected at the start of the next FUN_0804cb1c, by really calling FUN_080518dc in the audio task."""
    m.ev_queue = []
    m.uc.mem_write(RESUME, b"\x00\xbf\x00\xbf")
    saved = {}

    def at_cb1c(m):
        if not m.ev_queue or saved:
            return
        ev = m.ev_queue.pop(0)
        uc = m.uc
        saved['r'] = [m.reg(i) for i in range(4)] + [uc.reg_read(UC_ARM_REG_LR)]
        m.uc.mem_write(EVBUF, ev)
        m.setreg(0, m.r32(APP + 0x9a74))
        m.setreg(1, EVBUF)
        uc.reg_write(UC_ARM_REG_LR, RESUME | 1)
        uc.reg_write(UC_ARM_REG_PC, 0x080518dd)

    def at_resume(m):
        r = saved.pop('r')
        for i in range(4):
            m.setreg(i, r[i])
        m.uc.reg_write(UC_ARM_REG_LR, r[4])
        m.uc.reg_write(UC_ARM_REG_PC, 0x0804cb1d)   # re-enter; hook fires again for the next queued event
    m.hook(0x0804cb1c, at_cb1c)
    m.hook(RESUME, at_resume)

def note_on(m, ch, note, vel=100):
    m.ev_queue.append(struct.pack("<IIIIII", 5, 0, ch, note, vel, 0))

def note_off(m, ch, note):
    m.ev_queue.append(struct.pack("<IIIIII", 6, 0, ch, note, 0, 0))

import struct
