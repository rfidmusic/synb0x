/* Filter Type and filter envelope: pad parameters shared by fenv.c (registration, defaults) and filter.c (engine). */
#ifndef FENV_H
#define FENV_H

/* New pad parameters: unregistered in stock (ids < 500 are table slots; the mod uses 0x1d0..0x1da elsewhere) */
#define P_LEVEL    0x04          /* stock "Level:" (Main tab) */
#define P_FILTER   200           /* stock "Filter:", -1000..1000: now cutoff, far left lowest, far right highest */
#define P_FTYPE    0x1e1         /* 3.1.9-syn's Type (LP / HP / BP): hidden, read only to convert old presets */
#define P_FMORPH   0x1e9         /* Morph: 0..1000, LP (0) .. notch (500) .. HP (1000); modulatable (filter.c) */
#define P_FATTACK  0x1e2         /* 0..1000, 60 x^3 s */
#define P_FDECAY   0x1e3
#define P_FSUSTAIN 0x1e4         /* 0..1000 level */
#define P_FRELEASE 0x1eb         /* not 0x1e5: stock intercepts that id as a hidden Keys-screen switch (FUN_0809fa50 /
                                    FUN_08099504 set / get app + 0x8cc7 instead of the pad record), so the value never
                                    stored and turning the knob flipped that switch */
#define P_FDEPTH   0x1e6         /* -1000..1000: cutoff travel, 1000 = the knob's whole range */
#define P_GLIDE    0x1e7         /* Glide: Off / Always / Legato (glide.c) */
#define P_GLIDETIME 0x1e8        /* Glide Time: 0..1000, 10 x^3 s */
#define P_ADATTACK 0x1ec         /* AD envelope (modulation source AD, on the Mod tab): 0..1000, 60 x^3 s */
#define P_ADDECAY  0x1ed         /* stored right after AD Attack in every record (filter.c looks it up as a pair) */
/* (0x1ee was LFO 1-Shot, removed in 3.1.v7: the AD envelope replaces it; not registered, so presets' lfomode is ignored) */
#define P_ADATKSLOPE 0x1c0       /* (3.1.v7) AD Atk Slope 0..1000: 500 linear, below: slow then late, above: fast then
                                    easing in; stored after Osc Track (the record's 81st) */
#define P_ADDECSLOPE 0x1c1       /* (3.1.v7) AD Dec Slope 0..1000: 500 linear, below: fast drop then a tail, above:
                                    holds then falls late; 270 = the earlier builds' exponential decay; the 82nd */
#define P_FMODEL   0x1ef         /* Filter Type (Conf tab): 0 SEM, 1 Polivoks (xml filtermodel); stored after AD Decay */

/* Defaults for new and existing pads (presets saved before this build load with these) */
#define DEF_FILTER   1000        /* fully open: with LP and no depth, the filter is skipped */
#define DEF_FTYPE    0           /* LP: nothing to convert */
#define DEF_FMORPH   0           /* LP */
#define DEF_FATTACK  0
#define DEF_FDECAY   300         /* 1.6 s */
#define DEF_FSUSTAIN 0
#define DEF_FRELEASE 300
#define DEF_FDEPTH   0
#define DEF_GLIDE    0           /* Off */
#define DEF_GLIDETIME 200        /* 80 ms */
#define DEF_ADATTACK 0
#define DEF_ADDECAY  300         /* 1.6 s */
#define DEF_ADATKSLOPE 500       /* linear: the earlier builds' attack */
#define DEF_ADDECSLOPE 270       /* ~ the earlier builds' decay (exponential, 99 % at the Decay time) */
#define DEF_FMODEL   0           /* SEM: presets from before this build open with it (Stock was removed) */
#define FMODELS      2

/* Oscillator (Osc tab, Sample / Multisample pads), stored in this order right after Filter Type. Ids: the free ones
   below the 500-slot parameter table that stock never registers. */
#define P_OSC_ON    0x1f0        /* button: off / on */
#define P_OSC_MODE  0x1f1        /* (was the "OSC/MOD" button; 3.1.v1: kept registered and stored so presets keep their
                                    layout, not on the Osc page and ignored: the oscillator only modulates) */
#define P_OSC_WAVE  0x1f2        /* list: Sine, Square, Triangle, Saw (0..3; an older build's 0..1000 -> the nearest) */
#define P_OSC_LEVEL 0x1f3        /* 0..1000; modulation target */
#define P_OSC_OCT   0x1dc        /* list -3 .. +3 octaves (index 0..6, 3 = the played note) */
#define P_OSC_TUNE  0x1dd        /* 0..1000: -6 .. +6 semitones, 500 = 0; modulation target */
#define P_OSC_FINE  0x1de        /* -1000..1000: -50 .. +50 cents, 0 at the centre */
#define P_OSC_PW    0x1df        /* -1000..1000: every wave's width 50 % +- 45 % (5 .. 95 %), 0 = the plain wave; mod target */
#define OSC_SETTINGS 8          /* the Osc tab's eight */
#define P_OSC_TRACK 0x1e0        /* Osc Track (Osc tab since S.1, was Conf): 0 Off = fixed C4 (+ Octave / Tune / Fine), 1 On = follows the
                                    note, the pad's Pitch and Glide; stored after Pulse W */
#define DEF_OSC_TRACK 1          /* On: as 3.1.uo */
#define DEF_OSC_ON    0
#define DEF_OSC_MODE  0
#define DEF_OSC_WAVE  0
#define DEF_OSC_LEVEL 700
#define DEF_OSC_OCT   3
#define DEF_OSC_TUNE  500
#define DEF_OSC_FINE  0
#define DEF_OSC_PW    0

/* Modulation source codes (engine): KEY is stock, FENV and AD use the envelope codes no Blackbox pad routes ("env1",
   "env2" in presets). Their source objects live in the voice's filter object: the engine reads a source's value at
   pointer + 4. */
#define SRC_KEY  0xe
#define SRC_FENV 1
#define SRC_AD   2
#define SRC_OSC  3               /* the pad's oscillator ("env3"): applied by filter.c to Filter and Level */
#define FENV_SRC_OFF 0x44        /* FENV: pointer filter object + 0x44, value at + 0x48 (filter.c's envelope level) */
#define AD_SRC_OFF   0x40        /* AD: pointer filter object + 0x40, value at + 0x44 (the FENV object's unused word 0) */

#endif
