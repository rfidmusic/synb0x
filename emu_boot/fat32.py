"""Minimal FAT32 image builder (LFN entries, contiguous allocation) for the emulated SD card."""
import struct

SEC = 512


def _lfn_checksum(sfn):
    s = 0
    for c in sfn:
        s = (((s & 1) << 7) | (s >> 1)) + c & 0xFF
    return s


class Fat32:
    def __init__(self, size_mb=96, spc=1):
        self.nsec = size_mb * 2048
        self.spc = spc
        self.rsvd = 32
        nclus_est = self.nsec // spc
        self.fatsz = (nclus_est * 4 + SEC - 1) // SEC + 1
        self.data0 = self.rsvd + 2 * self.fatsz
        self.nclus = (self.nsec - self.data0) // spc
        assert self.nclus > 65525
        self.img = bytearray(self.nsec * SEC)
        self.fat = [0x0FFFFFF8, 0x0FFFFFFF]
        self.csize = spc * SEC

    def alloc(self, nbytes):
        n = max(1, (nbytes + self.csize - 1) // self.csize)
        first = len(self.fat)
        for i in range(n):
            self.fat.append(first + i + 1 if i < n - 1 else 0x0FFFFFFF)
        return first, n

    def coff(self, clus):
        return (self.data0 + (clus - 2) * self.spc) * SEC

    def write_chain(self, first, data):
        o = self.coff(first)
        self.img[o:o + len(data)] = data          # contiguous

    def _entries(self, name, is_dir, clus, size, idx):
        base, ext = (name.rsplit(".", 1) + [""])[:2] if "." in name else (name, "")
        b = "".join(c for c in base.upper() if c.isalnum())[:6] or "X"
        e = "".join(c for c in ext.upper() if c.isalnum())[:3]
        sfn = (f"{b}~{idx}"[:8].ljust(8) + e.ljust(3)).encode()
        chk = _lfn_checksum(sfn)
        u = name.encode("utf-16-le") + b"\0\0"
        chars = [u[i:i + 2] for i in range(0, len(u), 2)]
        while len(chars) % 13:
            chars.append(b"\xff\xff")
        parts = [chars[i:i + 13] for i in range(0, len(chars), 13)]
        out = []
        for seq in range(len(parts), 0, -1):
            p = parts[seq - 1]
            ord_ = seq | (0x40 if seq == len(parts) else 0)
            out.append(bytes([ord_]) + b"".join(p[0:5]) + bytes([0x0F, 0, chk]) + b"".join(p[5:11]) + b"\0\0" +
                       b"".join(p[11:13]))
        attr = 0x10 if is_dir else 0x20
        out.append(sfn + struct.pack("<BBBHHHHHHHI", attr, 0, 0, 0, 0x5021, 0x5021, clus >> 16, 0, 0x5021,
                                     clus & 0xFFFF, size))
        return b"".join(out)

    def add_dir(self, tree, clus, parent):
        """tree: name -> bytes | dict.  Directory `clus` already allocated (or 2 for root)."""
        ents = []
        if clus != 2:
            ents.append(b".          " + struct.pack("<BBBHHHHHHHI", 0x10, 0, 0, 0, 0, 0, clus >> 16, 0, 0,
                                                     clus & 0xFFFF, 0))
            pc = 0 if parent == 2 else parent
            ents.append(b"..         " + struct.pack("<BBBHHHHHHHI", 0x10, 0, 0, 0, 0, 0, pc >> 16, 0, 0,
                                                     pc & 0xFFFF, 0))
        subdirs = []
        for i, (name, v) in enumerate(sorted(tree.items()), 1):
            if isinstance(v, dict):
                c, _ = self.alloc(self.csize * 8)     # dirs: reserve 8 clusters
                ents.append(self._entries(name, True, c, 0, i))
                subdirs.append((v, c))
            else:
                c, _ = self.alloc(len(v)) if v else (0, 0)
                if v:
                    self.write_chain(c, v)
                ents.append(self._entries(name, False, c, len(v), i))
        blob = b"".join(ents)
        assert len(blob) <= self.csize * (8 if clus != 2 else 64), "directory too big"
        self.write_chain(clus, blob)
        for v, c in subdirs:
            self.add_dir(v, c, clus)

    def build(self, tree):
        root, _ = self.alloc(self.csize * 64)
        assert root == 2
        self.add_dir(tree, 2, 0)
        assert len(self.fat) < self.nclus
        bs = bytearray(SEC)
        bs[0:3] = b"\xEB\x58\x90"
        bs[3:11] = b"MSWIN4.1"
        struct.pack_into("<HBHBHHBHHHII", bs, 11, SEC, self.spc, self.rsvd, 2, 0, 0, 0xF8, 0, 63, 255, 0, self.nsec)
        struct.pack_into("<IHHIHH", bs, 36, self.fatsz, 0, 0, 2, 1, 6)
        struct.pack_into("<BBBI11s8s", bs, 64, 0x80, 0, 0x29, 0x12345678, b"BLACKBOX   ", b"FAT32   ")
        bs[510:512] = b"\x55\xAA"
        self.img[0:SEC] = bs
        fsi = bytearray(SEC)
        struct.pack_into("<I", fsi, 0, 0x41615252)
        struct.pack_into("<I", fsi, 484, 0x61417272)
        struct.pack_into("<II", fsi, 488, self.nclus - len(self.fat) + 2, len(self.fat))
        fsi[510:512] = b"\x55\xAA"
        self.img[SEC:2 * SEC] = fsi
        self.img[6 * SEC:7 * SEC] = bs
        fat = bytearray(self.fatsz * SEC)
        fat[:4 * len(self.fat)] = struct.pack(f"<{len(self.fat)}I", *self.fat)
        for k in range(2):
            o = (self.rsvd + k * self.fatsz) * SEC
            self.img[o:o + len(fat)] = fat
        return self.img
