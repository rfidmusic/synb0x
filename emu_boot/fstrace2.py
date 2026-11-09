import sys, collections
from audio import *
m = setup()
m.TICK_INSNS = 20000
ff = [a for a, n in FUNCS if 0x08086000 <= a < 0x08087a00]
seq = []
for a in ff:
    m.hook(a, lambda m, a=a: seq.append((a, m.uc.reg_read(UC_ARM_REG_LR) & ~1)))
for i in range(int(sys.argv[1])):
    ui_frame(m)
    run_for(m, 200000)
out = []
for a, lr in seq:
    k = f"{a:08x}<-{fname(lr)}"
    if out and out[-1][0] == k: out[-1][1] += 1
    else: out.append([k, 1])
for k, n in out: print(n, k)
print('sd reads', len(m.sd_log), m.sd_log[-12:])
for nme, t in task_tcbs(m).items(): print(nme, task_where(m, t))
import m7; m7.save(m, 'snap_ui.pkl', dict(tick=m.tick[0], tasks=m.tasks))
