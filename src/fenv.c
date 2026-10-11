/*
 * Filter Type and filter envelope: the pad parameters. Original 1010music Blackbox, firmware 3.1.9.
 * The sound side is in filter.c; this registers the new pad parameters (and glide.c's two) and gives every pad record
 * their defaults.
 *
 * Pad records (the app's settings stores, FUN_08093f20 type 3 = sample pad, type 0x4c = empty pad) hold 64 entries
 * in stock and a sample pad already uses 59, so patches/fenv.py raises the capacity to 72 (the stores come from the
 * SDRAM pool, FUN_0804436c: 64 more bytes per store). The stock adder (FUN_08093ef6) drops entries past capacity.
 * Presets: the stock loader walks a pad's entries and reads each by its xml name, so the new values save and load
 * with the pad; presets from before this build keep the defaults. Stock firmware ignores the extra attributes.
 */
#include <stdint.h>
#include "fenv.h"

#define FN(addr) ((addr) | 1u)

typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);

#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))

#define TYPE_UNIPOLAR 8          /* 0..1000, shown 0.0..100.0 (the amp envelope's knobs) */
#define TYPE_BIPOLAR  9          /* -1000..1000, shown -100.0..100.0 (the Filter knob) */

void glide_register(void *table);   /* glide.c: Glide and Glide Time, registered with the filter parameters */

const char *const fenv_type_names[3] = {"LP", "HP", "BP"};

/* Replaces the Filter registration (bl @0x0808d59c): Filter as stock, then the new parameters. */
void fenv_register(void *table, int param, int type, const char *label, int min, int max, const char *xml)
{
    fw_register_num(table, param, type, label, min, max, xml);
    fw_register_list(table, P_FTYPE, "Type:", fenv_type_names, 3, "fenvtype");
    fw_register_num(table, P_FATTACK, TYPE_UNIPOLAR, "Attack:", 0, 1000, "fenvattack");
    fw_register_num(table, P_FDECAY, TYPE_UNIPOLAR, "Decay:", 0, 1000, "fenvdecay");
    fw_register_num(table, P_FSUSTAIN, TYPE_UNIPOLAR, "Sustain:", 0, 1000, "fenvsus");
    fw_register_num(table, P_FRELEASE, TYPE_UNIPOLAR, "Release:", 0, 1000, "fenvrel");
    fw_register_num(table, P_FDEPTH, TYPE_BIPOLAR, "Depth:", -1000, 1000, "fenvdepth");
    glide_register(table);
}

/* Replaces the "Filter defaults to 0" entry of both pad record types (bl @0x080940de type 3, @0x08094312 type 0x4c):
   Filter now defaults fully open (0 would be the lowest cutoff), then the new parameters. */
void fenv_defaults(void *store, int param, int value)
{
    (void)value;
    fw_store_add(store, param, DEF_FILTER);
    fw_store_add(store, P_FTYPE, DEF_FTYPE);
    fw_store_add(store, P_FATTACK, DEF_FATTACK);
    fw_store_add(store, P_FDECAY, DEF_FDECAY);
    fw_store_add(store, P_FSUSTAIN, DEF_FSUSTAIN);
    fw_store_add(store, P_FRELEASE, DEF_FRELEASE);
    fw_store_add(store, P_FDEPTH, DEF_FDEPTH);
    fw_store_add(store, P_GLIDE, DEF_GLIDE);
    fw_store_add(store, P_GLIDETIME, DEF_GLIDETIME);
}

/*
 * Modulation sources KEY and FENV in the pad modulation Source list (param 0x53).
 *
 * KEY is stock engine source 0xe ("key" in presets): per voice, (note - 60) / 60, already routed for both pad classes;
 * stock only leaves it out of the list. FENV is engine source code 1 ("env1" in presets), which no Blackbox pad routes:
 * here it routes to the voice's filter envelope, whose source object sits in the filter object at +0x44 (value at
 * +0x48, see filter.c). Both are appended after the stock eight, so saved list positions keep their meaning.
 *
 * A modulation route is message 0x3a: +0xc destination param (u16), +0x10 slot (0..2), +0x14 source code (u16),
 * +0x16 amount (s16, / 1000).
 */
const char *const fenv_source_names[10] = {
    (const char *)0x080cea68, /* none */ (const char *)0x080cea94, /* VEL  */
    (const char *)0x080ce644, /* LFO  */ (const char *)0x080cea70, /* PTCH */
    (const char *)0x080cea78, /* MODW */ (const char *)0x080cea80, /* MVOL */
    (const char *)0x080cea88, /* MPAN */ (const char *)0x080cea90, /* CC   */
    "KEY", "FENV",
};
const uint16_t fenv_source_codes[10] = {0, 0xd, 4, 0x19, 0x1a, 0x1c, 0x1d, 0x8000, 0xe, 1};

#define SRC_KEY  0xe
#define SRC_FENV 1
#define FENV_SRC_OFF (0x44)      /* in the filter object */

struct mod_msg {
    uint8_t head[0xc];
    uint32_t dest;
    uint32_t slot;
    uint16_t src;
    int16_t amount;
};

typedef void (*mod_set_fn)(float amount, void *param, void *src, unsigned slot);
typedef void (*msg_fn)(uint8_t *pad, struct mod_msg *msg);
typedef void (*copy_fn)(uint8_t *pad, uint8_t *voice);
#define fw_mod_set    ((mod_set_fn)FN(0x0806fcd4))   /* set one modulation slot of a parameter object */
#define fw_mod_msg_a  ((msg_fn)FN(0x08056810))       /* sample pads: route message */
#define fw_voice_copy ((copy_fn)FN(0x0805623c))      /* sample pads: pad parameters + voice-source rows -> voice */
#define fw_mod_msg_b  ((msg_fn)FN(0x08067018))       /* clip / slicer pads: route message, both voices */

/* Sample pads keep per-voice routes as rows on the pad: pad + 0x4ec + i * 12 = {float amount, u16 dest, u16 src,
   u8 slot}, count at pad + 0x54c, at most 8. */
struct mod_row {
    float amount;
    uint16_t dest, src;
    uint8_t slot, pad[3];
};
#define ROWS(pad)  ((struct mod_row *)((pad) + 0x4ec))
#define NROWS(pad) (*(uint32_t *)((pad) + 0x54c))

/* Destination -> parameter object, as the stock voice copy (FUN_0805623c) and clip handler (FUN_08067018) do it */
struct dest_map {
    uint16_t dest;
    uint16_t a, b;               /* offset in a sample-pad voice / in a clip pad (voice 0; voice 1 is + 0x410) */
    uint8_t scale_a, scale_b;    /* amount multiplier */
};
static const struct dest_map dests[] = {
    {2, 0x150, 0x2b8, 1, 1},     {4, 0x150, 0x2b8, 1, 1},     {9, 0x47c, 0, 1, 0},
    {10, 0x4b0, 0, 14, 0},       {0xb, 0x448, 0, 1, 0},       {0x11, 0x334, 0x484, 1, 1},
    {0x3c, 0x388, 0x514, 1, 1},  {0x3e, 0x3bc, 0x548, 1, 1},  {0x40, 0x3f0, 0x57c, 1, 1},
    {0x5c, 0x288, 0x2f4, 1, 1},  {0x5d, 0x2bc, 0, 1, 0},      {0x62, 0x184, 0x26c, 1, 2},
    {0x8f, 0x1b8, 0, 1, 0},      {0x90, 0x1ec, 0, 1, 0},      {0x91, 0x220, 0, 1, 0},
    {0x92, 0x254, 0, 1, 0},      {200, 0x2f8, 0x448, 1, 1},
};

static const struct dest_map *dest_of(unsigned dest)
{
    for (unsigned i = 0; i < sizeof dests / sizeof dests[0]; i++)
        if (dests[i].dest == dest)
            return &dests[i];
    return 0;
}

/* Replaces the sample-pad route call (bl @0x0805a138). FENV goes through the stock row bookkeeping as if it were KEY
   (insert / update / at most 8), then the row is marked FENV, which the stock voice copy skips. */
void fenv_mod_msg_a(uint8_t *pad, struct mod_msg *msg)
{
    if (msg->src != SRC_FENV) {
        fw_mod_msg_a(pad, msg);
        return;
    }
    msg->src = SRC_KEY;
    fw_mod_msg_a(pad, msg);
    msg->src = SRC_FENV;
    struct mod_row *row = ROWS(pad);
    for (unsigned i = 0, n = NROWS(pad); i < n && i < 8; i++)
        if (row[i].dest == (uint16_t)msg->dest && row[i].slot == (uint8_t)msg->slot && row[i].src == SRC_KEY)
            row[i].src = SRC_FENV;
}

/* Replaces both calls of the sample-pad voice copy (bl @0x08058c34 at note start, @0x0805a8da for live voices when
   the pad changed): stock first, then the FENV rows into the voice's parameter objects. */
void fenv_voice_copy(uint8_t *pad, uint8_t *voice)
{
    fw_voice_copy(pad, voice);
    struct mod_row *row = ROWS(pad);
    for (unsigned i = 0, n = NROWS(pad); i < n && i < 8; i++) {
        if (row[i].src != SRC_FENV)
            continue;
        const struct dest_map *d = dest_of(row[i].dest);
        if (d && d->a)
            fw_mod_set(row[i].amount * (float)d->scale_a, voice + d->a, voice + 0xa8 + FENV_SRC_OFF, row[i].slot);
    }
}

/* Replaces the clip / slicer route call (bl @0x080685c4). Stock ignores source 1, so FENV is set on both voices here. */
void fenv_mod_msg_b(uint8_t *pad, struct mod_msg *msg)
{
    fw_mod_msg_b(pad, msg);
    if (msg->src != SRC_FENV)
        return;
    const struct dest_map *d = dest_of((uint16_t)msg->dest);
    if (!d || !d->b)
        return;
    float amount = (float)msg->amount * 0.001f * (float)d->scale_b;
    for (unsigned v = 0; v < 2; v++)
        fw_mod_set(amount, pad + d->b + v * 0x410, pad + 0x3ac + v * 0x410 + FENV_SRC_OFF, (uint16_t)msg->slot);
}
