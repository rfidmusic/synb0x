# Synb0x

An unofficial feature mod for the **original 1010music Blackbox** (not the Blackbox 2), built on stock firmware 3.1.9.
Synb0x is a fork of [j3threejay/blackbox-mod](https://github.com/j3threejay/blackbox-mod) by Justin Joe (build 3.1.n):
it keeps most of that mod, drops a few of its features and adds a synth-style voice: two filter models with a
modulatable LP / notch / HP morph, a filter envelope, an AD envelope, a modulation oscillator, glide, and a lot less
CPU. Firmware version: **S.1** (previous releases: 3.1.t, 3.1.s).

> **Not affiliated with, endorsed by, or supported by 1010music.** This repository does not contain 1010music's
> firmware. You supply your own copy, downloaded from 1010music, and patch it yourself. Use at your own risk: this is
> tested on one unit, it may misbehave on yours, and running modified firmware may affect your warranty. Don't ask
> 1010music for support on a modded unit; flash stock first.

## Checksums

| File | SHA-256 |
|---|---|
| Stock `BLACKBOX.bin` from 1010music's **3.1.9** zip (what you patch) | `281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d` |
| Patched `BLACKBOX.bin`, **Synb0x S.1** (what `apply.py` writes) | `5c2b24860fba306be715c03a7145c8d5b87f4d7500d3a32318cfad3bb5b037a0` |

The patcher checks both itself and prints the result's SHA-256. To check a file by hand:

```
shasum -a 256 BLACKBOX.bin          # macOS / Linux
certutil -hashfile BLACKBOX.bin SHA256   # Windows
```

The same value is in [`SHA256SUMS`](SHA256SUMS) and in the patch file itself (`docs/blackbox-mod-S.1.json`,
`output_sha256`). Earlier releases are on their tags, branches and release pages: 3.1.t
(`4fe8f429d6e8ca61b467608cf484f9587fc2d67641a702c6238749508230f3a8`, branch `release/3.1.t`) and 3.1.s
(`2fbff5563ef236dfb2b84b04ba462f4da38a6bb9e2a2f50329cd6fdf7cc4c4de`, branch `release/3.1.s`).

## Install

1. Download **blackbox 3.1.9** from <https://1010music.com/downloads> and unzip it. You need the `BLACKBOX.bin` inside.
2. Either use the **Synb0x Firmware Patcher** app (Windows or macOS): download `Synb0x-Firmware-Patcher-Windows.zip`
   or `-macOS.zip` from the S.1 release, unzip and open it, choose the stock `BLACKBOX.bin`, pick S.1 (or 3.1.t /
   3.1.s) and where to save (the SD card's root installs it there), then Make Synb0x Firmware. It checks the stock file
   and the result by SHA-256 like `apply.py`, and contains no firmware. The apps aren't signed: on macOS right-click
   the app and choose Open the first time; on Windows choose More info -> Run anyway.

   Or with Python 3 (nothing to install):

   ```
   python3 apply.py path/to/BLACKBOX.bin
   ```

   It writes `out/blackbox-mod-S.1/BLACKBOX.bin` and prints its SHA-256, which must match the table above. It refuses
   to run on anything but the stock 3.1.9 file, and refuses to overwrite it.
3. Keep the stock `BLACKBOX.bin` somewhere safe. That file is your way back.
4. Copy the patched `BLACKBOX.bin` to the root of the Blackbox's microSD card and install it the way you install any
   1010music firmware update (hold BACK + INFO while powering on).
5. The startup screen reads Synb0x; the CPU meter next to the version reads **S.1** (at 480 MHz) or **S.1s** (at the
   stock clock, see CPU below).

**To go back to stock:** put the stock `BLACKBOX.bin` on the card and install it the same way. A build that doesn't
boot is recoverable the same way: the bootloader is never touched.

## What Synb0x adds

**Filter** (Filt tab, right after Main: Filter, Res, Morph, Depth / Attack, Decay, Sustain, Release)
- **Filter Type** per pad (Conf tab): **SEM**, a 12 dB/oct 2-pole state-variable filter like the Oberheim SEM, or
  **Polivoks**, a 12 dB/oct state-variable filter with slew-limited, rail-clipping integrators (after the Formanta
  Polivoks), 2x oversampled. A voice runs only its pad's filter.
- **Morph**: LP (0 %) -> notch (50 %) -> HP (100 %) as a crossfade, a modulation destination.
- The **Filter** knob is cutoff across its whole travel: 20 Hz far left to 20.5 kHz far right, shown 0-100 %; new pads
  start fully open. **Res** runs from a flat, no-peak setting (Q 0.707) up to the stock noon value, then on to gentle,
  in-tune self-oscillation.
- **Filter envelope** per voice: Attack, Decay, Sustain, Release (0 ms - 60 s) and Depth.
- The filter runs **before** the pad's Level, Pan and amp envelope, like a synth's VCF before its VCA, on every pad type.

**Modulation**
- **Mod tab** (was LFO): Waveform / Trig, Rate / Beat, AD Atk / AD Decay, Atk Slope / Dec Slope. The LFO always loops
  at full depth: each route's amount sets how far it moves its destination.
- **AD envelope** (source **AD**): a one-shot attack / decay per voice, 0 - 60 s each. **Atk Slope** and **Dec Slope**
  curve its two stages without changing their times (50 % = straight; defaults keep older presets sounding the same).
- **Oscillator** (Osc tab of Sample and Multisample pads): a per-voice modulation source **OSC** for Filter (audio-rate
  cutoff) and Level (AM). Wave (Sine, Square, Triangle, Saw), Level, Octave, Tune / Fine, Pulse W, then the **Osc**
  and **Osc Track** buttons (Osc Track On: follows the note, Pitch and Glide; Off: fixed C4). It is never heard
  itself, and costs no CPU when off or not routed.
- Sources **KEY** (key follow) and **FENV** (the filter envelope). Pulse W, Level and Tune of the oscillator, and
  Morph, are modulation destinations.

**Playing**
- **Glide** on Sample and Multisample pads (Conf tab): Off / Always / Legato, Glide Time up to 10 s.
- **Long samples** (over 4 min 16 s): an exact sample-cache index, so they no longer overload the audio engine.

**CPU**
- **480 MHz** on revision V chips (most units): the CPU runs at 479.23 MHz instead of 399.36 MHz. The build reads the
  chip's revision at power-on and runs exactly like stock on any other. Audio, SD, display and USB clocks are
  untouched; the sample rate stays exact.
- **Granular**: Fidelity picks the grain interpolation (HighQ = stock cubic, anything else = linear, much cheaper);
  the grain window is read from the processor's fast memory; grains no longer clear their whole buffer every block,
  and the grain mix loop no longer divides every sample (new in S.1, same sound bit for bit).
- Stereo samples, grains and filters run both channels in one loop; the copy loop moves a cache line at a time;
  Saturation and the delay line's reader are cheaper. All of these are bit-identical to stock where stock had them.
- A **CPU meter** next to the version: average / worst block of the last second.

**Kept from blackbox-mod 3.1.n**: Solo in the mixer, Slicer knobs, **Fidelity** (crunch rates and the machine modes
SP1200, SP-12, S950, MPC60, SP Raw), **Saturation** (soft saturation in place of the hard clip).

**Not in Synb0x** (removed from 3.1.n): Pad-1 ducker sources, Keys chords, note conditions, sequencer fix, the Munchi
delay, Room reverb and the master compressor models (the Delay, Reverb and Compressor are stock again), browser patcher.

## Presets

They load. Synb0x's settings save with the pad; presets made before them get the defaults. Stock firmware ignores the
extra settings. Older presets: the LFO's Depth and 1-Shot are ignored (Depth is always 100 %); a pad saved with the
Filter knob at centre (stock: filter off) loads as a low-pass; convert those first (below).

**Preset format spec:** [`docs/PRESET_FORMAT.md`](docs/PRESET_FORMAT.md) lists every `preset.xml` attribute of stock
3.1.9 and Synb0x S.1 (ids, stored ranges, list items, defaults, meaning), read from the firmware itself, so presets can
be written by other tools or converted from other formats. The same table as a CSV sheet:
[`docs/Blackbox_preset_format.csv`](docs/Blackbox_preset_format.csv).

### Converting older presets

Presets saved before Synb0x (stock 3.1.9, blackbox-mod 3.1.n) load, but the Filter knob means something else now, so
filtered pads sound different. The **Synb0x Preset Converter** rewrites them to sound as they did:

- **App** (Windows and macOS): download `Synb0x-Preset-Converter-Windows.zip` or `-macOS.zip` from the release, unzip
  and open it. Add the SD card (or a Presets folder, a preset folder, a single `preset.xml`); it lists every preset and
  what will change. Then **Replace in place** (each original kept beside it as `preset.xml.bak`) or **Make copies**
  (`<name> syn`), and Convert.
- **Command line** (Python 3, nothing to install): `python3 convert_presets.py --in-place /Volumes/BLACKBOX` rewrites
  every older `preset.xml` on the card (originals kept as `preset.xml.bak`); without `--in-place` it writes
  `<name> syn` copies. The app runs from source too: `pip install PyQt6`, then `python3 preset_converter_gui.py`.

Presets already saved on Synb0x, or converted before, are skipped. To undo a conversion in place, delete `preset.xml`
and rename `preset.xml.bak` back.

## Known issues

- On SEM, low notes take up to ~0.3 s to build up self-oscillation from silence (gentle by design).
- The AD envelope still starts late on granular pads (grain scheduling).
- Solo can stick: after un-soloing, pads may stay muted. Unmute them in Mute mode.

## Build from source

Needs `arm-none-eabi-gcc` (Homebrew's 16.2 reproduces the release byte for byte) and Python 3. Put your stock image at
`firmware/BLACKBOX-3.1.9.bin` (see `firmware/README.md`).

```
./build.sh
python3 patch.py solo slice filter fenv filttab glide splash cpu od clock delay grain cache grainfast cave
```

That writes `out/<patchsets>/BLACKBOX.bin`, byte-identical to S.1 (the SHA-256 above). `python3 make_patch.py <image>
S.1` turns an image into the release patch in `docs/`.

How it works: the stock image is left as it is. New code (`src/`) is compiled and appended after it, and a handful of
call sites and table entries (`patches/`) are redirected to the new code. Tests (`test_*.py`) run the patched functions
under Unicorn (`pip install unicorn`): `for t in test_*.py; do python3 $t; done`. `emu_boot/` boots a whole image under
the emulator for end-to-end checks. The full history of every build is in [`CHANGELOG.txt`](CHANGELOG.txt).

## What is and isn't in this repository

In it: original source code, patch definitions (addresses and replacement bytes), tools (`apply.py`,
`convert_presets.py`, and the two apps: `synb0x_patcher_gui.py`, `preset_converter_gui.py`), the preset format spec,
and MIT-licensed third-party DSP with its notices ([THIRD_PARTY.md](THIRD_PARTY.md)).

Not in it, and please don't add it in issues or pull requests: 1010music's firmware, patched firmware images,
decompiled or disassembled listings of the firmware, and 1010music's manuals or artwork.

## Credits and license

Synb0x is built on [blackbox-mod](https://github.com/j3threejay/blackbox-mod) by Justin Joe, whose patcher, toolchain,
test harness and features are most of this project. Third-party DSP is listed in [THIRD_PARTY.md](THIRD_PARTY.md).

MIT ([LICENSE](LICENSE)). "1010music" and "Blackbox" are trademarks of 1010music LLC, used only to say what this mod
is for.

Questions, problems, or a concern from 1010music: open an issue on this repository and it will be dealt with promptly.
