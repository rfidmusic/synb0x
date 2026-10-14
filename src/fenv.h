/* Filter Type and filter envelope: pad parameters shared by fenv.c (registration, defaults) and filter.c (engine). */
#ifndef FENV_H
#define FENV_H

/* New pad parameters: unregistered in stock (ids < 500 are table slots; the mod uses 0x1d0..0x1da elsewhere) */
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
#define P_LFOMODE  0x1ee         /* LFO 1-Shot button (0 Loop, 1 one cycle per note, then it holds); stored after AD Decay */

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
#define DEF_LFOMODE  0           /* Loop: the stock LFO */

/* Modulation source codes (engine): KEY is stock, FENV and AD use the envelope codes no Blackbox pad routes ("env1",
   "env2" in presets). Their source objects live in the voice's filter object: the engine reads a source's value at
   pointer + 4. */
#define SRC_KEY  0xe
#define SRC_FENV 1
#define SRC_AD   2
#define FENV_SRC_OFF 0x44        /* FENV: pointer filter object + 0x44, value at + 0x48 (filter.c's envelope level) */
#define AD_SRC_OFF   0x40        /* AD: pointer filter object + 0x40, value at + 0x44 (the FENV object's unused word 0) */

#endif
