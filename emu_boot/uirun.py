import sys, collections
from audio import *
import m7
m = setup()
m.TICK_INSNS = 20000
c = collections.Counter()
for a in (0x08092f5c, 0x08045b34, 0x080864e8, 0x080870f6, 0x08042c90, 0x08042c54):
    m.hook(a, lambda m, a=a: c.update([hex(a)]))
N = int(sys.argv[1])
for i in range(N):
    ui_frame(m)
    run_for(m, int(sys.argv[2]) if len(sys.argv) > 2 else 300_000)
    if i % 10 == 0:
        print(i, cur_task(m), dict(c), len(m.sd_log), m.sd_log[-2:], flush=True)
m7.save(m, 'snap_ui.pkl', dict(tick=m.tick[0], tasks=m.tasks))
