"""Write a tester sheet (CHANGELOG.txt) into each firmware folder next to the repo: only what is in that file
(version, SHA-256, the filter it runs, changes, fixes, optimizations). The full history is CHANGELOG.txt here."""
import hashlib, os, textwrap

ROOT = "/Users/tony/OpenWork Chat/blackbox"
STOCK = "281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d"

COMMON_S = [
    "Filter knob is cutoff across its whole travel (20 Hz far left to 20.5 kHz far right, shown 0-100%).",
    "Filter envelope per voice on the Filt tab: Attack, Decay, Sustain, Release (0 ms - 60 s) and Depth.",
    "Filt tab after Main: Filter, Res, {mode}, Depth / A, D, S, R. Main tab: Level, Pitch, Pan,"
    " Saturation / amp A, D, S, R.",
    "Modulation sources KEY (key follow) and FENV (the filter envelope), routable to any destination.",
    "Glide on sample / multisample pads (Conf tab): Off / Always / Legato, Glide Time up to 10 s.",
    "Startup screen reads Synb0x. CPU meter next to the version: average / peak % of the last second.",
    "Kept from blackbox-mod 3.1.n: mixer Solo, Slicer knobs, Fidelity crunch and machine modes (SP1200,"
    " SP-12, S950, MPC60, SP Raw), Saturation, master compressor models, Room reverb, Munchi delay.",
    "Not in this firmware (removed from 3.1.n): Pad-1 ducker sources, Keys chords, note conditions,"
    " sequencer fix.",
]
FIXES = [
    "No click when the Filter knob reaches fully open (the filter switches off only after its glide,"
    " and fades back in).",
    "Filt tab Release knob keeps its value (it used a parameter id the stock firmware reserves).",
    "Clip / slicer pads: the second voice reads its own pad's Fidelity setting.",
]
OPT = [
    "Settings lookups cached per voice, both filter stages in one pass, idle envelopes skipped.",
    "Branch-free soft clipping: filter at high Res about 21 % less CPU, Saturation about 14 % less.",
]
MORPH_FIX = ["No zipper clicks when Morph moves (by hand or by modulation): its mix ramps per sample."]
RES_REMAP = ["Res below noon: runs from a flat, no-peak setting up to the stock noon value, so the filter stays"
             " 24 dB/oct with a flat passband at every Res (before, low Res sagged and softened to ~18 dB/oct)."]
AD = ["Modulation source AD: a one-shot Attack / Decay envelope per voice (AD Attack, AD Decay on the Mod"
      " tab, 0 - 60 s), routable to any destination including Morph. The LFO tab is renamed Mod."]
AD_FIX = ["AD starts on the note's first audio block (Pitch / Level / Pan see it at once; Attack 0 = full"
          " immediately)."]
ONESHOT_MODE = ["LFO Mode Loop / 1-Shot: in 1-Shot the LFO runs one cycle from the note start and holds."]
ONESHOT_BTN = ["LFO 1-Shot is an on / off button on the Mod tab (like Key Trig), bottom row: Key Trig, 1-Shot,"
               " AD Attack, AD Decay."]
KNOWN_GRAN = ["Known: AD still starts late on granular pads (grain scheduling)."]

SEM_T = ("24 dB/oct state-variable filter, two stages (after Mutable Instruments' stmlib SVF), the second"
         " carrying Res; drive past noon (input soft clip, soft-limited resonance). Morph: LP (0 %) ->"
         " notch (50 %) -> HP (100 %) as a plain crossfade, like the Oberheim SEM's mode knob;"
         " Morph is a modulation destination.")
SEM_S = ("24 dB/oct state-variable filter, two stages (after Mutable Instruments' stmlib SVF), the second"
         " carrying Res; drive past noon. Type: LP, HP or BP.")

OPT_OWN = ["Settings lookups cached per voice, idle envelopes skipped.",
           "Branch-free soft clipping in Saturation: about 14 % less CPU."]


ORDER = ["Voice order: the filter (with Fidelity) now runs before the pad's Level (with velocity), Pan and amp envelope,"
         " like a synth's VCF before its VCA, on every pad type (stock: Level, Pan, envelope, then the filter; Clip and"
         " Slicer pads: before their amp envelope, their Level and Pan are applied elsewhere). The amp"
         " envelope now shapes everything the filter makes, its self-oscillation and drive included, and the filter's"
         " drive and Fidelity see the sample before Level and velocity (turning Level down or playing softly no longer"
         " drives the filter less)."]


METER = ["CPU meter on the Tools screen: a test build's longer name is shortened while readings show (\"td 8/17%\""
         " instead of \"3.1.td 8/17%\", which did not fit and lost its end); the full name shows for the first second."]


CPU_STOCK = ["Lower CPU, same sound (bit-identical, checked against stock 3.1.9): the stock per-voice gain, copy,"
             " clear and bus-mix loops run four values at a time and the amp envelope's glide keeps its values in"
             " registers (about 5,200 cycles less per voice per block); Munchi has no divisions per sample any"
             " more (about 10,500 less per block)."]
MUNCHI = ["Munchi delay uses less CPU: its reverb is skipped while silent (Wand at or left of centre) and"
          " starts clean when brought back, and its settings update once per block: about 121,000 cycles per"
          " block at Wand 20 % (was 223,000) and 36,000 at the centre (was 139,000)."]
VOICES = ("Max voices (emulator, every pad Poly X, Saturation on all 16 pads, every modulation slot routed from"
          " random sources, random Fidelity / filter / Res / Morph{extra}; master: {master}): {v480} voices at"
          " 480 MHz, {v400} at 400 MHz; {heavy480} if every voice were the heaviest. Real loads also depend on"
          " memory waits: check the CPU meter.")
CPU_T = VOICES.format(extra="", master="Munchi with its reverb, Room, compressor Squash", v480=37, v400=29,
                      heavy480=29) + " With 16 channels of MIDI playing (MIDI sources live, MIDI CC routed): 36 and 28."
CPU_U = VOICES.format(extra=", random Filter Type", master="Munchi with its reverb, compressor Squash", v480=37,
                      v400=29, heavy480=28) + " With 16 channels of MIDI playing (MIDI sources live, MIDI CC routed): 36 and 28."
CPU_V = VOICES.format(extra=", random Filter Type, the oscillator on in OSC or MOD with every route",
                      master="Munchi with its reverb", v480=25, v400=20, heavy480=20) + (
    " With 16 channels of MIDI playing (MIDI sources live, MIDI CC routed): the same.")


V1 = ["3.1.v1 is 3.1.v without the Munchi delay: the delay slot is the stock delay again (presets saved with Munchi play"
      " the stock delay), to make room for the shared reader. The CPU meter shows the short name: v1 34/71%.",
      "Shared reader: a stereo sample's two channels are read in one loop (the reading point steps once), Normal and"
      " HighQ, bit-identical to stock: about 2,500 cycles less per stereo voice per block (Normal 13,500 -> 11,000,"
      " HighQ 21,200 -> 18,400)."]
CPU_V1 = VOICES.format(extra=", random Filter Type, the oscillator on in OSC or MOD with every route",
                       master="no mod effect (the stock delay and Plate are not counted, as in every build)", v480=29,
                       v400=23, heavy480=22) + " With 16 channels of MIDI playing: 29 and 24."


def t_line(extra_changes, filt=SEM_T, opt_extra=(), own_filter=False, no_room=False, no_comp=False, no_munchi=False):
    feats = [c.format(mode="Morph") for c in COMMON_S] + AD + AD_FIX + ONESHOT_BTN     # in the 3.1.t release
    if no_room:
        feats = [f.replace(" master compressor models, Room reverb,", " master compressor models,") for f in feats]
    if no_comp:
        feats = [f.replace(" master compressor models,", "") for f in feats]
    if no_munchi:
        feats = [f.replace(", Munchi delay.", ".") for f in feats]
    return filt, extra_changes, feats, FIXES + MORPH_FIX, (OPT_OWN if own_filter else OPT) + list(opt_extra)

def s_line(extra_changes):
    feats = [c.format(mode="Type") for c in COMMON_S]
    return SEM_S, extra_changes, feats, FIXES, OPT

builds = {
    "blackbox-mod-3.1.t": ("3.1.t", "Build", t_line(
        [ORDER[0].replace(", its self-oscillation and drive included", ", its resonance and drive included")]
        + MUNCHI + CPU_STOCK + KNOWN_GRAN, opt_extra=[CPU_T])),
    "blackbox-mod-3.1.u": ("3.1.u", "Build", t_line(ORDER + MUNCHI + CPU_STOCK + RES_REMAP + [
        "Filter Type on the Conf tab of every pad mode (Saturation, Fidelity, Launch Mode, Filter Type,"
        " Output, Poly Mode, Glide, Glide Time, ...; Pan is only on the Main tab now): SEM or Polivoks,"
        " per pad. Default SEM: pads from older presets open with SEM. (The Stock filter type of earlier"
        " test builds is gone: it went unstable under fast cutoff modulation. Saved as filtermodel: presets"
        " from those builds open with SEM.)",
        "SEM: 24 dB/oct, Res below noon keeps it flat; self-oscillates from about 93 % into a clean sine"
        " at the cutoff, in tune (KEY -> Filter at +100 % plays it one octave per octave).",
        "Polivoks: self-oscillation from about 92 % Res left free as on the original: rough, at the rails,"
        " about 5.6 semitones below the cutoff; cutoff up to 16 kHz.",
        "Changing Filter Type while a pad plays restarts that voice's filter.",
        "No Room reverb: the Reverb is the stock Plate (presets saved with Room load as Plate), to make room"
        " for the full filters.",
        "Known: low notes take up to ~0.4 s to build up self-oscillation from silence (SEM)."]
        + KNOWN_GRAN,
        filt=("Two filters, chosen per pad with Filter Type (Conf tab): SEM = 24 dB/oct state-variable"
              " filter, two stages (after Mutable Instruments' stmlib SVF); Polivoks = 12 dB/oct state-variable"
              " filter with slew-limited, rail-clipping integrators (after the Formanta Polivoks). Each has Morph: LP (0 %) -> notch"
              " (50 %) -> HP (100 %) as a crossfade, a modulation destination. A voice runs only its pad's"
              " filter."),
        own_filter=True, no_room=True,
        opt_extra=["SEM and Polivoks are the full versions of the builds they came from (no trimming): in sine"
                   " sweeps against those builds both are bit-identical.",
                   CPU_U])),
    "blackbox-mod-3.1.v": ("3.1.v", "Build", t_line(ORDER + MUNCHI + CPU_STOCK + RES_REMAP + [
        "Oscillator: a new Osc tab between Main and Filt on Sample and Multisample pads (not Granular, Clip"
        " or Slicer). Top row: Wave, Level, Octave (-3 .. +3), Tune. Bottom row: Fine, Pulse W, then the"
        " Osc (on / off) and OSC/MOD buttons (knobs first: with buttons in the first two slots the knobs"
        " could not hold Wave and Level). One oscillator per voice, playing the note's pitch (with the"
        " pad's Pitch and Glide, unless Osc Track is Off).",
        "Osc Track (Conf tab of Sample and Multisample pads, 5th: Saturation, Fidelity, Launch Mode, Filter"
        " Type, Osc Track, Output, Poly Mode, Glide, Glide Time, ...): key tracking On / Off, separate from"
        " the Osc button. On (default): the oscillator follows the played note, the pad's Pitch and Glide."
        " Off: it stays on C4 whatever note is played; Octave, Tune and Fine still set its pitch.",
        "Older presets: the oscillator is Off (no CPU used) and Osc Track On.",
        "Wave is a selector: Sine, Square, Triangle or Saw (one wave at a time, every wave as loud as the"
        " sine; presets saved with the earlier continuous Wave open on the nearest wave, its pulse as"
        " Square; a preset saved with Pulse in the selector opens as Saw). Sine from a lookup table; square"
        " and saw band-limited at their edges.",
        "Pulse W bends every wave: 50 % (the centre) is the plain wave; away from it Square becomes a pulse"
        " (5 % to 95 %), Sine and Triangle lean to one side (the triangle towards a saw) and the Saw's ramp"
        " gets two slopes. Bent waves lose their DC part, so they get a little quieter towards the ends, as a"
        " narrow pulse does.",
        "Level: audio taper; 100 % peaks at -12 dBFS, the default 70 % at -18 dBFS. Tune: 0 % = -6"
        " semitones, 50 % = in tune, 100 % = +6. Fine: +-50 cents. Pulse W: 50 % in the middle, 5 % to"
        " 95 % across the knob.",
        "OSC: the oscillator is added to the voice before Fidelity and the filter, so it plays through the"
        " filter, Level, Pan, the amp envelope and the effects like the sample. Routes from OSC do nothing"
        " in OSC mode.",
        "MOD: the oscillator is silent and becomes modulation source OSC (Mod tab), for Filter and Level"
        " only (Level sets its depth). OSC -> Filter moves the cutoff every 8 frames (100 % = the knob's"
        " whole travel each way); OSC -> Level is per sample (amplitude modulation; past 100 % it rings).",
        "Pulse W, Level and Tune are modulation destinations (any source; Wave is not): a route at 100 % moves"
        " Pulse W the knob's whole travel each way, 3 % to 97 % at most (pulse-width modulation). Every slot"
        " of Morph, Pulse W, Level, Tune, Filter and Level can be used at once (18 routes).",
        "No DSP when the oscillator is off, or in MOD mode with no route from OSC. It does not run on a"
        " pad with no sample; it ends with the voice (the amp envelope's release).",
        "Filter Type on the Conf tab of every pad mode: SEM or Polivoks, per pad (default SEM). (The Stock"
        " filter type of earlier test builds is gone: it went unstable when the oscillator moved its"
        " cutoff. Saved as filtermodel: presets from those builds open with SEM.)",
        "No Room reverb (the Reverb is the stock Plate) and no master compressor models (the Tools"
        " Compressor is the stock On / Off again, Comp Thresh is gone; a setting saved with a model: set"
        " Compressor again). Removed to make room for the oscillator and the three filters.",
        "Known: low notes take up to ~0.4 s to build up self-oscillation from silence (SEM)."]
        + KNOWN_GRAN,
        filt=("Two filters, chosen per pad with Filter Type (Conf tab): SEM = 24 dB/oct state-variable"
              " filter, two stages (after Mutable Instruments' stmlib SVF); Polivoks = 12 dB/oct state-variable"
              " filter with slew-limited, rail-clipping integrators (after the Formanta Polivoks). Each has Morph: LP (0 %) -> notch"
              " (50 %) -> HP (100 %) as a crossfade, a modulation destination. A voice runs only its pad's"
              " filter."),
        own_filter=True, no_room=True, no_comp=True,
        opt_extra=[CPU_V,
                   "Audio-rate filter modulation (MOD, OSC -> Filter) is cheaper: the filter keeps its 32-frame steps"
                   " and only its cutoff moves every 8 frames, from the oscillator's value there: about 15,000 cycles"
                   " per voice per block on top of the filter (was about 25,000); every voice doing it: about 35"
                   " voices at 480 MHz (was 30). A square or pulse now switches the cutoff hard instead of being"
                   " averaged over the 8 frames.",
                   "Oscillator CPU per stereo voice per block (emulator count): sine about 11,200, triangle 11,200,"
                   " square 12,200, saw 10,900, whatever the width; off: about 290 (reading its settings)."])),
    "blackbox-mod-3.1.v1-test": ("3.1.v1", "Test build", t_line(ORDER + [CPU_STOCK[0].split("; Munchi has")[0] + "."] + V1 + RES_REMAP + [
        "Oscillator: a new Osc tab between Main and Filt on Sample and Multisample pads (not Granular, Clip"
        " or Slicer). Top row: Wave, Level, Octave (-3 .. +3), Tune. Bottom row: Fine, Pulse W, then the"
        " Osc (on / off) and OSC/MOD buttons (knobs first: with buttons in the first two slots the knobs"
        " could not hold Wave and Level). One oscillator per voice, playing the note's pitch (with the"
        " pad's Pitch and Glide, unless Osc Track is Off).",
        "Osc Track (Conf tab of Sample and Multisample pads, 5th: Saturation, Fidelity, Launch Mode, Filter"
        " Type, Osc Track, Output, Poly Mode, Glide, Glide Time, ...): key tracking On / Off, separate from"
        " the Osc button. On (default): the oscillator follows the played note, the pad's Pitch and Glide."
        " Off: it stays on C4 whatever note is played; Octave, Tune and Fine still set its pitch.",
        "Older presets: the oscillator is Off (no CPU used) and Osc Track On.",
        "Wave is a selector: Sine, Square, Triangle or Saw (one wave at a time, every wave as loud as the"
        " sine; presets saved with the earlier continuous Wave open on the nearest wave, its pulse as"
        " Square; a preset saved with Pulse in the selector opens as Saw). Sine from a lookup table; square"
        " and saw band-limited at their edges.",
        "Pulse W bends every wave: 50 % (the centre) is the plain wave; away from it Square becomes a pulse"
        " (5 % to 95 %), Sine and Triangle lean to one side (the triangle towards a saw) and the Saw's ramp"
        " gets two slopes. Bent waves lose their DC part, so they get a little quieter towards the ends, as a"
        " narrow pulse does.",
        "Level: audio taper; 100 % peaks at -12 dBFS, the default 70 % at -18 dBFS. Tune: 0 % = -6"
        " semitones, 50 % = in tune, 100 % = +6. Fine: +-50 cents. Pulse W: 50 % in the middle, 5 % to"
        " 95 % across the knob.",
        "OSC: the oscillator is added to the voice before Fidelity and the filter, so it plays through the"
        " filter, Level, Pan, the amp envelope and the effects like the sample. Routes from OSC do nothing"
        " in OSC mode.",
        "MOD: the oscillator is silent and becomes modulation source OSC (Mod tab), for Filter and Level"
        " only (Level sets its depth). OSC -> Filter moves the cutoff every 8 frames (100 % = the knob's"
        " whole travel each way); OSC -> Level is per sample (amplitude modulation; past 100 % it rings).",
        "Pulse W, Level and Tune are modulation destinations (any source; Wave is not): a route at 100 % moves"
        " Pulse W the knob's whole travel each way, 3 % to 97 % at most (pulse-width modulation). Every slot"
        " of Morph, Pulse W, Level, Tune, Filter and Level can be used at once (18 routes).",
        "No DSP when the oscillator is off, or in MOD mode with no route from OSC. It does not run on a"
        " pad with no sample; it ends with the voice (the amp envelope's release).",
        "Filter Type on the Conf tab of every pad mode: SEM or Polivoks, per pad (default SEM). (The Stock"
        " filter type of earlier test builds is gone: it went unstable when the oscillator moved its"
        " cutoff. Saved as filtermodel: presets from those builds open with SEM.)",
        "No Room reverb (the Reverb is the stock Plate) and no master compressor models (the Tools"
        " Compressor is the stock On / Off again, Comp Thresh is gone; a setting saved with a model: set"
        " Compressor again). Removed to make room for the oscillator and the three filters.",
        "Known: low notes take up to ~0.4 s to build up self-oscillation from silence (SEM)."]
        + KNOWN_GRAN,
        filt=("Two filters, chosen per pad with Filter Type (Conf tab): SEM = 24 dB/oct state-variable"
              " filter, two stages (after Mutable Instruments' stmlib SVF); Polivoks = 12 dB/oct state-variable"
              " filter with slew-limited, rail-clipping integrators (after the Formanta Polivoks). Each has Morph: LP (0 %) -> notch"
              " (50 %) -> HP (100 %) as a crossfade, a modulation destination. A voice runs only its pad's"
              " filter."),
        own_filter=True, no_room=True, no_comp=True, no_munchi=True,
        opt_extra=[CPU_V1,
                   "Audio-rate filter modulation (MOD, OSC -> Filter) is cheaper: the filter keeps its 32-frame steps"
                   " and only its cutoff moves every 8 frames, from the oscillator's value there: about 15,000 cycles"
                   " per voice per block on top of the filter (was about 25,000); every voice doing it: about 35"
                   " voices at 480 MHz (was 30). A square or pulse now switches the cutoff hard instead of being"
                   " averaged over the 8 frames.",
                   "Oscillator CPU per stereo voice per block (emulator count): sine about 11,200, triangle 11,200,"
                   " square 12,200, saw 10,900, whatever the width; off: about 290 (reading its settings)."])),
}

def wrap(prefix, text):
    return textwrap.fill(text, 100, initial_indent=prefix, subsequent_indent=" " * len(prefix))

for folder, (ver, status, (filt, changes, feats, fixes, opts)) in builds.items():
    path = os.path.join(ROOT, folder)
    if not os.path.isdir(path):
        print("missing", folder); continue
    sha = hashlib.sha256(open(os.path.join(path, "BLACKBOX.bin"), "rb").read()).hexdigest()
    title = f"SYNB0X {ver} - {status}" + (" (not published, for hardware testing)" if status == "Test build" else
                                           " (not published yet)" if status == "Build" else "")
    out = [title, "=" * len(title), "",
           f"File:    BLACKBOX.bin in this folder", f"SHA-256: {sha}",
           f"Made from stock Blackbox 3.1.9 (SHA-256 {STOCK[:16]}...).", "",
           "FILTER", wrap("  ", filt), ""]
    if changes:
        line = "3.1.s" if ver.startswith("3.1.s") else "3.1.t"
        head = ("CHANGES" if status == "Release" else
                "CHANGES COMPARED WITH THE PUBLISHED 3.1.t (SHA-256 4fe8f429...)" if ver == "3.1.t" else
                f"CHANGES COMPARED WITH THE {line} RELEASE")
        out += [head] + [wrap("- ", c) for c in changes] + [""]
    out += ["ALSO IN THIS FIRMWARE" if changes else "IN THIS FIRMWARE"] + [wrap("- ", c) for c in feats] + [""]
    out += ["FIXES"] + [wrap("- ", c) for c in fixes] + [""]
    out += ["OPTIMIZATIONS"] + [wrap("- ", c) for c in opts] + [""]
    open(os.path.join(path, "CHANGELOG.txt"), "w").write("\n".join(out))
    print("wrote", folder, sha[:8])
