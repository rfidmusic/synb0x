import sys, collections
from snap import *
m = restore()
reasons = collections.Counter()
orig = m._req_stop
def rs(why):
    reasons[why] += 1
    orig(why)
m._req_stop = rs
pc = m.uc.reg_read(UC_ARM_REG_PC)
for step in range(int(sys.argv[1])):
    r = m.run(pc, 500_000)
    pc = m.uc.reg_read(UC_ARM_REG_PC)
    print(step, r, cur_task(m), fname(pc), 'lr', fname(m.uc.reg_read(UC_ARM_REG_LR)), dict(reasons), m.pend, m.ipsr, m.basepri, m.primask, flush=True)
    reasons.clear()
