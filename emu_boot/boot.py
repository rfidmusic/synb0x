"""Boot the stock Blackbox 3.1.9 image from Reset_Handler under the M7 shim."""
import bisect, sys, collections
from unicorn import UC_HOOK_BLOCK
from unicorn.arm_const import *
from m7 import M7, BASE

FUNCS = sorted((int(a, 16), n) for a, n in (l.split() for l in open(__file__.rsplit('/', 1)[0] + '/funcs.txt')))
FADDR = [a for a, _ in FUNCS]

def fname(pc):
    i = bisect.bisect_right(FADDR, pc) - 1
    return f"{FUNCS[i][1]}+{pc - FUNCS[i][0]:x}" if i >= 0 else f"{pc:08x}"

def rcc_model(m):
    RCC = 0x58024400
    def cr(v):
        for on, rdy in ((0, 2), (7, 8), (12, 13), (16, 17), (24, 25), (26, 27), (28, 29)):
            v = (v | (1 << rdy)) if v & (1 << on) else (v & ~(1 << rdy))
        return v | (1 << 14) | (1 << 15) | (1 << 5)
    m.rd_hooks[RCC + 0x00] = cr
    m.rd_hooks[RCC + 0x10] = lambda v: (v & ~0x38) | ((v & 7) << 3)              # CFGR SWS = SW
    m.rd_hooks[RCC + 0x70] = lambda v: v | 2 if v & 1 else v & ~2                   # BDCR LSERDY
    m.rd_hooks[RCC + 0x74] = lambda v: v | 2 if v & 1 else v & ~2                   # CSR LSIRDY
    m.regs[RCC + 0x00] = 1                                                         # HSION at reset
    m.no_spin |= {RCC, RCC + 0x10, RCC + 0x70, RCC + 0x74}

def periph_model(m):
    fixed = {}
    for b in (0x40005400, 0x40005800, 0x40005C00, 0x58001C00):          # I2C ISR: TXE TXIS RXNE STOPF TC
        fixed[b + 0x18] = 0x67
    for b in (0x40013000, 0x40003800, 0x40003C00, 0x40013400, 0x40015000, 0x58001400):  # SPI SR
        fixed[b + 0x14] = 0x101B
    for b in (0x40011000, 0x40004400, 0x40004800, 0x40004C00, 0x40005000, 0x40011400, 0x40007800,
              0x40007C00, 0x58000C00):                                   # USART ISR: TXE TC TEACK REACK
        fixed[b + 0x1C] = 0x6000C0
    for a, v in fixed.items():
        m.rd_hooks[a] = (lambda v: lambda _: v)(v)
        m.no_spin.add(a)

PX_CURRENT_TCB = None

def cur_task(m):
    t = m.r32(m.pxtcb)
    return m.cstr(t + 0x34, 16) if t else '-'

def make(verbose=False):
    global PX_CURRENT_TCB
    m = M7(verbose)
    PX_CURRENT_TCB = m.pxtcb = m.r32(0x08087fd4)
    m.tasks = []
    def tcreate(m):
        e = dict(entry=m.reg(0), name=m.cstr(m.reg(1)), stack=m.reg(2), param=m.reg(3),
                 prio=m.r32(m.reg(13)), handle_ptr=m.r32(m.reg(13) + 4))
        m.tasks.append(e)
        print(f"  xTaskCreate {e['name']!r} entry={e['entry']:08x} param={e['param']:08x} stack={e['stack']} prio={e['prio']}")
    m.hook(0x08088ad8, tcreate)
    def logf(m):
        fmt = m.cstr(m.reg(0), 120)
        args = [m.reg(1), m.reg(2), m.reg(3)]
        sargs = []
        for a in args:
            try:                                    # (a string near the end of a memory region: read what is there)
                sargs.append(repr(m.cstr(a, 60)) if 0x20000000 <= a < 0x20020000 or 0x24000000 <= a < 0x24080000 or 0x08040000 <= a < 0x08100000 or 0xC0000000 <= a < 0xC4000000 else hex(a))
            except Exception:
                sargs.append(hex(a))
        if m.log_on:
            print(f"  LOG: {fmt.strip()!r} {' '.join(sargs)}")
    m.log_on = True
    m.hook(0x08043de4, logf)
    def systick_ctrl(v):
        m.systick_on = bool(v & 1)
    m.wr_hooks[0xE000E010] = systick_ctrl
    tick = [0]
    def gettick(m):
        tick[0] += 1
        return tick[0] // 64
    m.stub(0x0807794c, gettick)          # HAL_GetTick
    def hal_delay(m):
        tick[0] += 64 * (m.reg(0) + 1)
    m.stub(0x08077958, hal_delay)        # HAL_Delay: advance HAL time instead of busy-waiting
    m.tick = tick
    rcc_model(m)
    periph_model(m)
    m.trail = collections.deque(maxlen=40)
    def blk(uc, a, s, _):
        m.trail.append(a)
    if verbose:
        m.uc.hook_add(UC_HOOK_BLOCK, blk)
    return m

MAIN_CALLS = [0x080778d4, 0x08043e84, 0x0804409c, 0x08043504, 0x08045e68, 0x08042200, 0x08043cb8, 0x08040bcc,
              0x08045b00, 0x08041a12, 0x080419f4, 0x08041634, 0x080416d8, 0x08040aec, 0x08041c60, 0x0804c1a4,
              0x08044da0, 0x08042c0e, 0x080443a8, 0x0808be4c, 0x0807d36c, 0x08046340, 0x08087a70, 0x08046938,
              0x08087a44]

def trace_main(m):
    seen = set()
    for a in MAIN_CALLS:
        def h(m, a=a):
            lr = m.uc.reg_read(UC_ARM_REG_LR) & ~1
            if 0x08044188 <= lr < 0x08044330:
                print(f"  main -> {a:08x}  (insns~{m.insns}, tick {m.tick[0]//64})")
        m.hook(a, h)

if __name__ == "__main__":
    m = make()
    trace_main(m)
    m.hook(0x08087a44, lambda m: m._req_stop('halt-kstart'))
    sp = m.r32(BASE); rst = m.r32(BASE + 4)
    m.uc.reg_write(UC_ARM_REG_SP, sp); m.msp = sp
    for step in range(int(sys.argv[1]) if len(sys.argv) > 1 else 20):
        r = m.run(rst if step == 0 else m.uc.reg_read(UC_ARM_REG_PC), 2_000_000)
        pc = m.uc.reg_read(UC_ARM_REG_PC)
        print(step, r, cur_task(m), hex(pc), fname(pc), 'lr', fname(m.uc.reg_read(UC_ARM_REG_LR)), 'tick', m.tick[0])
        if r == 'error': break
        if r == 'halt-kstart':
            import m7; m7.save(m, 'snap_kstart.pkl', dict(tick=m.tick[0], tasks=m.tasks))
            print('saved snap_kstart.pkl'); break
    print('trail:', ' '.join(fname(a) for a in list(m.trail)[-20:]))
