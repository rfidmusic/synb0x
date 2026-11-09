"""Fake SD card: FAT32 image served through the firmware's own FatFS by replacing the 5 sd_diskio driver
functions (SD_Driver @0x080cfc1c: initialize/status/read/write/ioctl)."""
import os, re
from fat32 import Fat32, SEC

BB = "/Users/tony/Documents/Blackbox"
IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdcard.img")

def build(preset="000 SL BASS MUSIC DEMO", force=False):
    if os.path.exists(IMG) and not force:
        return bytearray(open(IMG, "rb").read())
    pdir = os.path.join(BB, "Presets", preset)
    files = {n: open(os.path.join(pdir, n), "rb").read() for n in os.listdir(pdir)
             if os.path.isfile(os.path.join(pdir, n)) and not n.startswith('.')}
    st = open(os.path.join(BB, "settings.tml"), "rb").read()
    st = re.sub(rb'<preset name="[^"]*"/>', b'<preset name="' + preset.encode() + b'"/>', st)
    tree = {"settings.tml": st, "Presets": {preset: files}}
    total = sum(len(v) for v in files.values())
    img = Fat32(size_mb=max(64, total // (1 << 20) + 40)).build(tree)
    open(IMG, "wb").write(img)
    return img

def install(m, img):
    m.sd = img
    m.sd_log = []
    def rd(m):
        buf, sec, cnt = m.reg(1), m.reg(2), m.reg(3)
        m.uc.mem_write(buf, bytes(img[sec * SEC:(sec + cnt) * SEC]))
        m.sd_log.append(('R', sec, cnt))
        return 0
    def wr(m):
        buf, sec, cnt = m.reg(1), m.reg(2), m.reg(3)
        img[sec * SEC:(sec + cnt) * SEC] = bytes(m.uc.mem_read(buf, cnt * SEC))
        m.sd_log.append(('W', sec, cnt))
        return 0
    def ioctl(m):
        cmd, buf = m.reg(1), m.reg(2)
        if cmd == 1:
            m.w32(buf, len(img) // SEC)
        elif cmd == 2:
            m.uc.mem_write(buf, (SEC).to_bytes(2, 'little'))
        elif cmd == 3:
            m.w32(buf, 1)
        return 0
    m.stub(0x080458dc, value=0)      # disk_initialize -> ready
    m.stub(0x08045ab4, value=0)      # disk_status -> ready
    m.stub(0x08045974, rd)           # disk_read
    m.stub(0x080459e8, wr)           # disk_write
    m.stub(0x08045a5c, ioctl)        # disk_ioctl
