"""Startup screen name. Checks the image only (what the screen draws is hardware)."""
import struct
import sys

IMG = "out/solo+slice+filter+fenv+filttab+glide+splash+cpu+od+comp+fx2+munchi+cave/BLACKBOX.bin"
fw = open(IMG, "rb").read()
o = lambda a: a - 0x08040000
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


name = fw[o(0x080CFAA0):o(0x080CFAAC)]
check("startup screen name reads Synb0x", name.split(b"\0")[0] == b"Synb0x", name)
check("the screen's label still points at it", struct.unpack_from("<I", fw, o(0x080C72C0))[0] == 0x080CFAA0)
check("'by 1010music' untouched", fw[o(0x080CFAAC):o(0x080CFAAC) + 13] == b"by 1010music\0")
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
