"""Startup screen: the name "blackbox" (FUN_080c70b8, the label above "by 1010music" and the version) reads "Synb0x".
The string is used only there (one literal, 0x080c72c0); it keeps its 12-byte slot."""
PATCHES = [
    (0x080CFAA0, b"blackbox\0\0\0\0", b"Synb0x\0\0\0\0\0\0"),
]
