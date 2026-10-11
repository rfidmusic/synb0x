"""The compiled code cave (./build.sh), appended after the stock image, plus the build letter in the version string."""
import os

from thumb import ROOT

STOCK_END = 0x080F1E78
BUILD = b"J"  # Tools screen shows 3.1.<BUILD>; S = solo, T = + slice knobs, U = + ducking (crashed: heap), V = U with state moved off the heap, W = duck shapes EXP1/EXP2/PUMP/LINR, X = + slicer Zoom knob, Y = + Keys screen chords, Z = chord label shortened to fit the button, a = six more chord shapes (Opn Shl Qrt + parallel m7 m9 Mj7), b = + sequence note conditions A:B, PLAY list reordered around ALWAYS, c = + pad crunch, 24 dB SVF with resonance drive, CPU meter on the version label, d = crunch rates moved down (16k..2k), CPU meter in the global cell name, new pad overdrive, Interp / crunch on Slicer and Clip pads, compressor models, e = sequencer edits play this pass, f = Comp Thresh, Tools order, Saturation label, lenient solo check, g = crunch reads the app's Interp, Interp under Saturation, sequencer grace, h = Interp label -> Fidelity, i = reverb Type selector + Room, j = Room v2 (8 lines, diffusion, modulation), k = Munchi Delay in FX1, l = Fidelity machine modes (SP1200, SP-12, S950, MPC60), m = solo fix, FX pages rebuild on Type, Munchi Clock/Width/Duck, Room Size/Mod/Early/Width, n = SP Raw + Saturation as SP input drive, E = filter-env branch: Pad-1 ducker, Keys chords, note conditions and sequencer fix removed; filter Type LP/HP/BP, per-pad filter envelope, KEY and FENV modulation sources, Filt tab, F = E with Main tab Level, Pitch, Pan, Saturation / A D S R (blank slots made the envelope row jump back on every value change), G = F + glide (Off / Always / Legato, Glide Time) on sample and multisample pads, H = G + startup screen name Synb0x, I = H with less CPU: cached settings positions, one-pass two-stage filter, envelope steps skipped at rest, J = I + modulation indicators on the Filt tab and the Filter knob reading 0-100 % (display only)

PATCHES = [
    (0x080CF290, b"3.1.9\0", b"3.1." + BUILD + b"\0"),
    (STOCK_END, b"", open(os.path.join(ROOT, "out", "cave.bin"), "rb").read()),
]
