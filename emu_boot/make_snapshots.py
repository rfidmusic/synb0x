"""Full pipeline: reset -> osKernelStart (snap_kstart.pkl) -> UI boot + SD mount + preset load (snap_loaded.pkl).

  ../.venv/bin/python make_snapshots.py      (run from anywhere; ~5 min)
"""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
PY = sys.executable
if not os.path.exists('snap_kstart.pkl'):
    subprocess.run([PY, '-u', 'boot.py', '45'], check=True)
from audio import *
import m7
m = setup('snap_kstart.pkl')
m.TICK_INSNS = 20000                    # 1 FreeRTOS tick per 20k instructions
# phase 1: UI frames only (splash, SD mount, settings.tml)
for i in range(160):
    ui_frame(m)
    run_for(m, 200_000)
print('phase 1 done, SD sectors read:', len(m.sd_log), flush=True)
# phase 2: UI frames + 3 audio blocks per frame (the engine consumes the UI's message ring)
for i in range(300):
    ui_frame(m)
    for k in range(3):
        dma_irq(m, (3 * i + k) & 1)
        run_for(m, 150_000)
    if i % 50 == 0:
        print('phase 2 frame', i, 'SD sectors read:', len(m.sd_log), flush=True)
m7.save(m, 'snap_loaded.pkl', dict(tick=m.tick[0], tasks=m.tasks))
print('saved snap_loaded.pkl')
