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
#define TAB_GRAN 3
#define TAB_POS  1
#define TAB_FILT 5
#define TAB_IDS  0x12f           /* button id of tab 0; Filt = 0x134 */
#define LABELS   ((const char *const *)0x080f1300)   /* stock Main, Pos, LFO, Gran, Conf */
#define BAR_COUNT 0x36           /* u16: buttons in the bar */
#define SLOT     0xa0

/* Insertion order: the bar places the first button rightmost, so this reads Main Filt Pos LFO Gran Conf on screen. */
static const uint8_t order[TABS] = {4, 3, 2, 1, TAB_FILT, 0};

static int on_bar(unsigned bar, unsigned tab)
{
    if (bar == 1)
        return 1;                                    /* granular: every tab */
    if (tab == TAB_GRAN)
        return 0;
    return bar == 0 || tab != TAB_POS;               /* multisample: no Pos */
}

/*
 * Replaces the stock per-bar loop body (0x080b919e): name all six buttons of this bar and add the ones it shows.
 * bar = the tab bar object, slot4 = its tab-4 button slot, index = 0..2. Returns into the stock end of the bar loop.
 */
void filt_tabs(uint8_t *bar, uint8_t *slot4, unsigned index)
{
    unsigned count = 0;
    for (unsigned t = 0; t < TABS; t++)
        count += on_bar(index, t);
    *(uint16_t *)(bar + BAR_COUNT) = (uint16_t)count;   /* before adding: the bar sizes its buttons from it */
    for (unsigned i = 0; i < TABS; i++) {
        unsigned t = order[i];
        uint8_t *button = slot4 + ((int)t - 4) * SLOT;
        set_id_fn set_id = *(set_id_fn *)(*(uint8_t **)button + 0x24);
        set_id(button, TAB_IDS + t);
        fw_set_label(button, t == TAB_FILT ? "Filt" : LABELS[t]);
        if (on_bar(index, t))
            fw_bar_add(bar, button);
    }
}

/* The Filt page: knob grid, two rows of four */
static const uint16_t filt_ids[8] = {
    P_FILTER, 0x11 /* Res */, P_FTYPE, P_FDEPTH,
    P_FATTACK, P_FDECAY, P_FSUSTAIN, P_FRELEASE,
};

/* Replaces the page-list calls (pad screen 0x080b8956 and the three other tabbed callers): tab 5 of a pad is the Filt
   page, from the pad's own record; everything else is stock. Like the stock pad pages, the list then gets the pad's
   modulation routes (they light the knobs' modulation indicators) and the record's two trailing words. */
int filt_page(void *app, const uint8_t *ref, void *list, int tab)
{
    unsigned kind = *(const uint16_t *)(ref + 4);
    if (tab != TAB_FILT || kind == 0x40 || kind == 0x41 || kind == 0x42 || ((kind >> 8) & 0x1f) != 0)
        return fw_page(app, ref, list, tab);
    fw_list_clear(list);
    const void *store = fw_pad_store(app, ref);
    for (unsigned i = 0; i < sizeof filt_ids / sizeof filt_ids[0]; i++)
        fw_list_add(list, filt_ids[i], fw_setting(store, filt_ids[i]));
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
    if (mode == 3)
        return state >= 0x18 && state < 0x18 + 5 ? state : 0x18;
    if (mode < 0 || mode > 3)
        return 0x18;
    if (state <= 0x1a)
        return state < 0x18 ? 0x18 : state;
    return state == 0x1c ? state : 0x18;
}
