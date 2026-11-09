/*
 * Pad edit screen: a sixth tab, "Filt", right after Main, holding Filter, Res, Type and the filter envelope
 * (Depth, Attack, Decay, Sustain, Release). Filter and Res leave the Main tab. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock (pad screen FUN_080b8c0c): five tabs, Main / Pos / LFO / Gran / Conf = tab 0..4, button ids 0x12f..0x133.
 * Three prebuilt tab bars (screen + 0xf6d0 + bar * 0x378), chosen by pad mode: bar 0 Main/Pos/LFO/Conf, bar 1 (granular)
 * all five, bar 2 (multisample) Main/LFO/Conf. Each bar has six button slots (0xa0 each, the sixth unused); a bar lays
 * its buttons out right to left in insertion order, with width from its count (+0x36). The current tab (screen +
 * 0xf6cc) is the page number handed to the page-list function (FUN_08098d40, five pages of up to 36 ids per pad mode).
 * Filt is tab 5 (button id 0x134, app state 0x1d), so no stock tab is renumbered; already six wide in stock: the tab ->
 * app state map (FUN_0809f218), the state handler (0x18..0x1d), the button highlight loop and the slots.
 * patches/filttab.py does the rest: tab press range, grid-or-list checks, re-entry clamp, Main page tables.
 */
#include <stdint.h>
#include "fenv.h"

#define FN(addr) ((addr) | 1u)

typedef void (*set_id_fn)(void *button, unsigned id);
typedef void (*set_label_fn)(void *button, const char *label);
typedef void (*bar_add_fn)(void *bar, void *button);
typedef int (*page_fn)(void *app, const uint8_t *ref, void *list, int tab);
typedef void (*list_clear_fn)(void *list);
typedef void (*list_add_fn)(void *list, unsigned id, int value);
typedef void *(*pad_store_fn)(void *app, const uint8_t *ref);
typedef int (*setting_fn)(const void *store, unsigned param);

#define fw_set_label  ((set_label_fn)FN(0x080a3dec))
#define fw_bar_add    ((bar_add_fn)FN(0x080c4ed8))
#define fw_page       ((page_fn)FN(0x08098d40))
#define fw_list_clear ((list_clear_fn)FN(0x080a4fc2))
#define fw_list_add   ((list_add_fn)FN(0x080a5038))
#define fw_pad_store  ((pad_store_fn)FN(0x08098d0c))
#define fw_setting    ((setting_fn)FN(0x08093e9c))

/* A pad record's modulation routes: 12-byte entries, read one at a time by FUN_08094a30 */
struct route {
    uint32_t word0;
    uint16_t source, dest;
    int16_t slot;
    uint16_t pad;
};
typedef int (*route_fn)(const void *store, unsigned index, struct route *out);
typedef void (*list_route_fn)(void *list, unsigned dest, int slot, unsigned source);
#define fw_route      ((route_fn)FN(0x08094a30))
#define fw_list_route ((list_route_fn)FN(0x080a50c6))   /* mark the list entry of dest: slot has this source */

#define TABS     6
#define TAB_GRAN 3               /* granular pads: Gran; sample / multisample pads: Osc (3.1.uo), the same tab id */
#define TAB_POS  1
#define TAB_LFO  2               /* shown as "Mod": the LFO and the AD envelope */
#define TAB_FILT 5
#define TAB_IDS  0x12f           /* button id of tab 0; Filt = 0x134 */
#define LABELS   ((const char *const *)0x080f1300)   /* stock Main, Pos, LFO, Gran, Conf */
#define BAR_COUNT 0x36           /* u16: buttons in the bar */
#define BAR_ADDED 0x34           /* u16: buttons added so far (the next one's position) */
#define SLOT     0xa0

/* Insertion order: the bar places the first button rightmost. Granular reads Main Filt Pos Mod Gran Conf on screen;
   the others Main Osc Filt Pos Mod Conf (multisample: no Pos; clip / slicer: no Osc). */
static const uint8_t order_gran[TABS] = {4, TAB_GRAN, 2, 1, TAB_FILT, 0};
static const uint8_t order_osc[TABS] = {4, 2, 1, TAB_FILT, TAB_GRAN, 0};

/* bar 0 (sample, clip, slicer): osc = the Osc tab is on it (sample pads) */
static int on_bar(unsigned bar, unsigned tab, int osc)
{
    if (bar == 1)
        return 1;                                    /* granular: every tab */
    if (tab == TAB_GRAN)
        return bar == 2 || osc;                      /* Osc: multisample, and sample pads on bar 0 */
    return bar == 0 || tab != TAB_POS;               /* multisample: no Pos */
}

/* Lay out a bar's buttons: count first (the bar sizes them from it), then add in insertion order */
static void bar_fill(uint8_t *bar, uint8_t *slot4, unsigned index, int osc, int name)
{
    unsigned count = 0;
    for (unsigned t = 0; t < TABS; t++)
        count += on_bar(index, t, osc);
    *(uint16_t *)(bar + BAR_COUNT) = (uint16_t)count;
    *(uint16_t *)(bar + BAR_ADDED) = 0;
    const uint8_t *order = index == 1 ? order_gran : order_osc;
    for (unsigned i = 0; i < TABS; i++) {
        unsigned t = order[i];
        uint8_t *button = slot4 + ((int)t - 4) * SLOT;
        if (name) {
            set_id_fn set_id = *(set_id_fn *)(*(uint8_t **)button + 0x24);
            set_id(button, TAB_IDS + t);
            fw_set_label(button, t == TAB_FILT ? "Filt" : t == TAB_LFO ? "Mod" : t == TAB_GRAN && index != 1 ? "Osc"
                                                                                                   : LABELS[t]);
        }
        if (on_bar(index, t, osc))
            fw_bar_add(bar, button);
    }
}

/*
 * Replaces the stock per-bar loop body (0x080b919e): name all six buttons of this bar and add the ones it shows.
 * bar = the tab bar object, slot4 = its tab-4 button slot, index = 0..2. Returns into the stock end of the bar loop.
 */
void filt_tabs(uint8_t *bar, uint8_t *slot4, unsigned index)
{
    bar_fill(bar, slot4, index, 0, 1);               /* bar 0 starts without Osc; filt_bar_show adds it for samples */
}

/*
 * Replaces both calls of the pad screen's "show the tab bar for this pad" (FUN_080b8724(screen, bar), @0x080b8844 and
 * @0x080b8bcc): bar 0 serves sample, clip and slicer pads, so it is laid out again whenever the pad's mode asks for
 * the other layout (Osc only on sample pads). Bars live at screen + 0xf6d0 + bar * 0x378, their six button slots at
 * screen + 0x104f8 - 0x3c0 + bar * 0x3c0 + tab * 0xa0.
 */
typedef void (*bar_show_fn)(uint8_t *screen, int bar);
typedef void (*unlink_fn)(void *parent, void *child);
#define fw_bar_show ((bar_show_fn)FN(0x080b8724))
#define fw_unlink   ((unlink_fn)FN(0x080aec62))
#define SCREEN_BARS 0xf6d0
#define SCREEN_SLOTS (0x104f8 - 0x3c0)
#define BAR_SIZE    0x378
#define SLOTS_SIZE  0x3c0

void filt_bar_show(uint8_t *screen, int bar)
{
    if (bar == 0) {
        int osc = fw_setting(screen + 0x7d8, 0x8b) == 0;     /* the pad's mode: 0 sample (1 clip, 2 slicer) */
        uint8_t *b = screen + SCREEN_BARS, *slot0 = screen + SCREEN_SLOTS;
        uint8_t *osc_button = slot0 + TAB_GRAN * SLOT;
        int shown = *(void **)(osc_button + 0x2c) == b;      /* the Osc button's parent is the bar */
        if (shown != osc) {
            for (unsigned t = 0; t < TABS; t++) {
                uint8_t *button = slot0 + t * SLOT;
                if (*(void **)(button + 0x2c) == b) {
                    fw_unlink(b, button);
                    *(void **)(button + 0x2c) = 0;
                }
            }
            bar_fill(b, slot0 + 4 * SLOT, 0, osc, 0);
        }
    }
    fw_bar_show(screen, bar);
}

/* The Osc page (sample / multisample pads, tab 3): knob grid, two rows of four, the six knobs first and the two buttons
   last. After every value change the grid (FUN_080a87b6) leaves the top row when slots 0-1 hold no knob, and a button
   (type 4) is not a knob: with Osc and OSC/MOD in slots 0-1, Wave and Level could not be turned (3.1.v). */
static const uint16_t osc_ids[8] = {             /* (3.1.v1: no OSC/MOD button, the oscillator only modulates) */
    P_OSC_WAVE, P_OSC_LEVEL, P_OSC_OCT, P_OSC_TUNE,
    P_OSC_FINE, P_OSC_PW, P_OSC_ON, P_OSC_TRACK,    /* (S.1: Osc Track here, was on the Conf tab) */
};

/* The Filt page: knob grid, two rows of four */
static const uint16_t filt_ids[8] = {
    P_FILTER, 0x11 /* Res */, P_FMORPH, P_FDEPTH,
    P_FATTACK, P_FDECAY, P_FSUSTAIN, P_FRELEASE,
};

/* Replaces the page-list calls (pad screen 0x080b8956 and the three other tabbed callers): tab 5 of a pad is the Filt
   page, from the pad's own record; everything else is stock. Like the stock pad pages, the list then gets the pad's
   modulation routes (they light the knobs' modulation indicators) and the record's two trailing words. */
int filt_page(void *app, const uint8_t *ref, void *list, int tab)
{
    unsigned kind = *(const uint16_t *)(ref + 4);
    int pad = !(kind == 0x40 || kind == 0x41 || kind == 0x42 || ((kind >> 8) & 0x1f) != 0);
    if (tab == TAB_LFO && pad) {
        /* the Mod tab (3.1.v7), shown column by column: Waveform / Trig, Rate / Beat, AD Atk / AD Decay, Atk Slope /
           Dec Slope. From the stock LFO page's entries (Waveform 8, Rate 9 or the synced rate 10, Depth 0xb, Beat
           Sync 0xc, Key Trig 0xd, with their modulation marks), reordered, Depth left out (fixed at 100 %), then the
           AD envelope's four. (Each of the first two columns keeps a knob: the knob grid's rule, FUN_080a87b6.) */
        int r = fw_page(app, ref, list, tab);
        if (r) {
            uint8_t *l = (uint8_t *)list;
            uint32_t n = *(uint32_t *)l;
            uint8_t keep[4][12];
            unsigned got = 0;
            static const uint16_t order[4] = {8, 0xd, 9, 0xc};      /* (9 stands for 9 or 10: the rate shown) */
            for (unsigned o = 0; o < 4; o++)
                for (uint32_t i = 0; i < n && i < 0x30; i++) {
                    uint16_t id = *(uint16_t *)(l + 4 + 12 * i);
                    if (id == order[o] || (order[o] == 9 && id == 10)) {
                        for (unsigned b = 0; b < 12; b++)
                            keep[got][b] = l[4 + 12 * i + b];
                        got++;
                        break;
                    }
                }
            for (unsigned g = 0; g < got; g++)
                for (unsigned b = 0; b < 12; b++)
                    l[4 + 12 * g + b] = keep[g][b];
            *(uint32_t *)l = got;
            const void *store = fw_pad_store(app, ref);
            static const uint16_t ad[4] = {P_ADATTACK, P_ADDECAY, P_ADATKSLOPE, P_ADDECSLOPE};
            for (unsigned i = 0; i < 4; i++)
                fw_list_add(list, ad[i], fw_setting(store, ad[i]));
        }
        return r;
    }
    int osc_page = tab == TAB_GRAN && pad && fw_setting(fw_pad_store(app, ref), 0x8b) == 0;   /* sample mode */
    if ((tab != TAB_FILT && !osc_page) || !pad)
        return fw_page(app, ref, list, tab);
    fw_list_clear(list);
    const void *store = fw_pad_store(app, ref);
    const uint16_t *ids = osc_page ? osc_ids : filt_ids;
    for (unsigned i = 0; i < 8; i++)
        fw_list_add(list, ids[i], fw_setting(store, ids[i]));
    struct route r = {0, 0, 0, 0, 0};
    for (unsigned i = 0; fw_route(store, i, &r); i++)
        fw_list_route(list, r.dest, r.slot, r.source);
    *(uint32_t *)((uint8_t *)list + 0x248) = ((const uint32_t *)store)[8];
    *(uint32_t *)((uint8_t *)list + 0x24c) = ((const uint32_t *)store)[9];
    return 1;
}

/*
 * Replaces the pad screen's re-entry clamp (FUN_080991a8, entered by a branch at its first instruction): which tab
 * state (0x18 + tab) the screen may reopen on. Stock: sample / clip / slicer keep Main, Pos, LFO or Conf, granular
 * keeps any of its five, anything else reopens on Main. Now Filt is kept for every pad mode too.
 */
int filt_clamp(void *app, int state, const uint8_t *ref)
{
    if (*(const uint16_t *)(ref + 4) & 0x1f00)
        return 0x18;
    int mode = fw_setting(fw_pad_store(app, ref), 0x8b);
    if (state == 0x18 + TAB_FILT && mode >= 0 && mode <= 3)
        return state;
    if (state == 0x18 + TAB_GRAN && mode == 0)
        return state;                                    /* Osc, on sample pads */
    if (mode == 3)
        return state >= 0x18 && state < 0x18 + 5 ? state : 0x18;
    if (mode < 0 || mode > 3)
        return 0x18;
    if (state <= 0x1a)
        return state < 0x18 ? 0x18 : state;
    return state == 0x1c ? state : 0x18;
}

/*
 * The Filter knob reads 0..100 % (far left 0, far right 100) instead of -100..100: display only. The stored value, the
 * preset value and the knob's travel stay -1000..1000. Knob cells (FUN_080a9120, called @0x080a957e, 0x080a965e,
 * 0x080a9704) keep the parameter id at +0x94, the display type at +0x96 and the value at +0x98; for Filter (type 9,
 * shown value / 10 with one decimal and %) the value is handed over as (value + 1000) / 2 and put back afterwards.
 */
typedef void (*knob_text_fn)(uint8_t *cell, int flag);
#define fw_knob_text ((knob_text_fn)FN(0x080a9120))

void filt_knob_text(uint8_t *cell, int flag)
{
    if (*(const uint16_t *)(cell + 0x94) != P_FILTER || cell[0x96] != 9) {
        fw_knob_text(cell, flag);
        return;
    }
    int32_t *value = (int32_t *)(cell + 0x98), v = *value;
    int shown = (v + 1000) / 2;
    *value = shown < 0 ? 0 : shown > 1000 ? 1000 : shown;
    fw_knob_text(cell, flag);
    *value = v;
}

/*
 * Parameters a pad's modulation can target (stock: 28 ids at 0x080f12bc, read by FUN_080b8898 to let the modulation
 * button open on the focused knob, and by FUN_080b892c to mark knobs and list rows): the stock list plus Morph and
 * the oscillator's Wave, Level and Tune.
 */
const uint16_t filt_mod_targets[32] = {
    0x04, 0x62, 0x5c, 0x8f, 0x90, 0x91, 0x92, 0x4e, 0xa2, 0xc8, 0x11, 0x33, 0x32, 0x38,
    0x37, 0x3a, 0x5d, 0x0b, 0x09, 0x0a, 0x3c, 0x3e, 0x40, 0x32, 0x33, 0x38, 0x37, 0x3a,
    P_FMORPH, P_OSC_PW, P_OSC_LEVEL, P_OSC_TUNE,
};
