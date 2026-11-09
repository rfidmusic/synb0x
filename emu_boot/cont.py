import sys, collections
from audio import *
m = setup(sys.argv[1])
m.TICK_INSNS = 20000
ff = [a for a, n in FUNCS if 0x08086000 <= a < 0x08087a00]
c = collections.Counter()
for a in ff:
    m.hook(a, lambda m, a=a: c.update([fname(a)]))
for i in range(int(sys.argv[2])):
    ui_frame(m)
    for k in range(3):
        dma_irq(m, (3 * i + k) & 1)
        run_for(m, 150000)
    if i % 10 == 0:
        pc = m.uc.reg_read(UC_ARM_REG_PC)
        print(i, cur_task(m), fname(pc), dict(c), len(m.sd_log), flush=True); c.clear()
for nme, t in task_tcbs(m).items(): print(nme, task_where(m, t))
if len(sys.argv) > 3:
    import m7; m7.save(m, sys.argv[3], dict(tick=m.tick[0], tasks=m.tasks)); print('saved', sys.argv[3])
