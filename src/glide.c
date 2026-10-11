/*
 * Portamento (glide) for sample and multisample pads. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Two new pad parameters on the Conf tab, after Poly Mode: "Glide:" Off / Always / Legato, and "Glide Time:" 0..100
 * (10 x^3 seconds: 80 ms at 20, 640 ms at 40, 10 s at 100). A slide always takes the Glide Time, whatever the interval.
 *   Always  every new note slides from the pitch the pad last played (still sliding, if it was).
 *   Legato  only while another note of the pad is held (amp envelope in attack / decay / sustain at the note-on).
 *
 * Stock (sample voices, FUN_08058548 note-on): a new voice's base rate is set once from its note
 * (voice +0x18 = 2^((note - root) / 12) * sample rate / 48000, via FUN_0805f6b8 @0x0805892a); with Legato on and a
 * voice sounding, the note retunes that voice in place instead (same call @0x0805864c, no retrigger). Every block the
 * reader's rate is base x 2^(Pitch + modulation) through FUN_0805f728 (2^x, x in octaves) @0x080570b2 (loop) and
 * @0x0805743a (one shot). Glide adds its offset there, in semitones, and filter.c moves it toward 0 once per block.
 * Nothing in stock remembers a pad's last note, so a small table in backup SRAM does.
 * Clip / slicer voices never get an offset (their filter objects are zeroed at voice start like any other).
 */
#include <stdint.h>
#include "fenv.h"

#define FN(addr) ((addr) | 1u)

typedef float (*exp2_fn)(float octaves);
typedef int (*setting_fn)(const void *store, unsigned param);
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);

#define fw_exp2       ((exp2_fn)FN(0x0805f728))
#define fw_setting    ((setting_fn)FN(0x08093e9c))
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define APP_PADS      (0x24020088u + 0x1840u)

void bkp_enable(void);

enum { GLIDE_OFF, GLIDE_ALWAYS, GLIDE_LEGATO, GLIDE_MODES };
const char *const glide_mode_names[GLIDE_MODES] = {"Off", "Always", "Legato"};

void glide_register(void *table)
{
    fw_register_list(table, P_GLIDE, "Glide:", glide_mode_names, GLIDE_MODES, "glidemode");
    fw_register_num(table, P_GLIDETIME, 8, "Glide Time:", 0, 1000, "glidetime");
}

/* Per voice, in the filter object (voice + 0xa8) at +0x58..+0x5f: zeroed by the stock voice start (FUN_08076704) before
   the note-on hooks run, so a voice that is not told to glide plays at pitch. */
struct glide_voice {
    float offset;                /* semitones from the voice's own note, moving to 0 */
    float step;                  /* semitones per frame */
};
#define GV(voice) ((volatile struct glide_voice *)((voice) + 0xa8 + 0x58))

/* Per pad (4 x 5 grid), backup SRAM 0x38800700 (free since the sequencer fix went) */
struct glide_pad {
    float note;                  /* the last note's own pitch */
    uint8_t *voice;              /* the voice that played it (its offset is where the pad's pitch is now) */
    uint8_t valid, held, fresh, pad;
    float from;                  /* the pad's pitch just before this note-on (glide_pre), if fresh */
};
struct glide_ram {
    uint32_t magic;
    struct glide_pad pad[20];
};
#define G     ((volatile struct glide_ram *)0x38800700u)
#define MAGIC 0x474c4432u        /* "GLD2": bumped with the layout */

static volatile struct glide_pad *pad_slot(const uint8_t *pad)
{
    uint32_t id = *(const uint32_t *)(pad + 0x18);
    unsigned row = (id >> 8) & 0xff, col = id & 0xff;
    if (row >= 4 || col >= 5)
        return 0;
    bkp_enable();
    if (G->magic != MAGIC) {
        for (unsigned i = 0; i < 20; i++) {
            G->pad[i].valid = 0;
            G->pad[i].held = 0;
            G->pad[i].fresh = 0;
            G->pad[i].voice = 0;
        }
        G->magic = MAGIC;
    }
    return &G->pad[row * 5 + col];
}

static const void *pad_store(const uint8_t *pad)
{
    uint32_t id = *(const uint32_t *)(pad + 0x18);
    return (const void *)(APP_PADS + ((id >> 8) & 0xff) * 0xf0u + (id & 0xff) * 0x30u);
}

/* Voices of an engine pad: pointers at pad + 0x2c, count at pad + 0x6c (at most 16) */
static int pad_has_voice(const uint8_t *pad, const uint8_t *voice)
{
    unsigned n = *(const uint32_t *)(pad + 0x6c);
    for (unsigned i = 0; i < n && i < 16; i++)
        if (((uint8_t *const *)(pad + 0x2c))[i] == voice)
            return 1;
    return 0;
}

/* Where the pad's pitch is now, in semitones: the last note plus whatever is left of its slide */
static float pad_pitch(const uint8_t *pad, volatile struct glide_pad *g)
{
    float p = g->note;
    uint8_t *v = g->voice;
    if (v && pad_has_voice(pad, v) && v[0])
        p += GV(v)->offset;
    return p;
}

/* Called before every sample-pad note-on (glide_note_on in glide_thunk.S): is a note of this pad held right now?
   Taken before the note-on, because the mono path chokes the held voices before starting the new one. */
void glide_pre(const uint8_t *pad)
{
    volatile struct glide_pad *g = pad_slot(pad);
    if (!g)
        return;
    unsigned n = *(const uint32_t *)(pad + 0x6c), held = 0;
    for (unsigned i = 0; i < n && i < 16; i++) {
        const uint8_t *v = ((uint8_t *const *)(pad + 0x2c))[i];
        if (v && v[0] && !v[0x40] && (uint8_t)(v[0x2c] - 1) < 3)    /* active, not choked, amp gate on */
            held = 1;
    }
    g->held = (uint8_t)held;
    /* where the pitch is now, before the note-on can recycle (and zero) the voice that is sliding */
    g->from = g->valid ? pad_pitch(pad, g) : 0.0f;
    g->fresh = 1;
}

static void glide_to(uint8_t *voice, const uint8_t *pad, int note)
{
    volatile struct glide_pad *g = pad_slot(pad);
    if (!g)
        return;
    const void *store = pad_store(pad);
    int mode = fw_setting(store, P_GLIDE);
    int t = fw_setting(store, P_GLIDETIME);
    float x = (float)(t < 0 ? 0 : t > 1000 ? 1000 : t) * 0.001f;
    float seconds = 10.0f * x * x * x;
    float offset = 0.0f;
    if (g->valid && ((mode == GLIDE_ALWAYS) || (mode == GLIDE_LEGATO && g->held)))
        offset = (g->fresh ? g->from : pad_pitch(pad, g)) - (float)note;
    if (!(offset > -120.0f && offset < 120.0f))
        offset = 0.0f;                                   /* NaN or nonsense from a damaged backup SRAM */
    g->fresh = 0;
    volatile struct glide_voice *gv = GV(voice);
    if (offset != 0.0f && seconds > 0.0f) {
        gv->offset = offset;
        gv->step = (offset < 0.0f ? -offset : offset) / (seconds * 48000.0f);
    } else {
        gv->offset = 0.0f;
        gv->step = 0.0f;
    }
    g->note = (float)note;
    g->voice = voice;
    g->valid = 1;
}

/* New voice (bl @0x0805892a in glide_thunk.S): r5 voice, r4 pad, r7 note */
void glide_start(uint8_t *voice, const uint8_t *pad, int note)
{
    glide_to(voice, pad, note);
}

/* Legato retune of a sounding voice (bl @0x0805864c): r6 voice, r4 pad, r3 note. The voice's base rate is about to
   become the new note's, so its offset is reset from where it actually is. */
void glide_retune(uint8_t *voice, const uint8_t *pad, int note)
{
    glide_to(voice, pad, note);
}

/* Replaces the 2^x of the reader's rate (bl @0x080570b2 and @0x0805743a, voice in r4, passed in r0 by the thunk) */
float glide_rate(float octaves, const uint8_t *voice)
{
    return fw_exp2(octaves + GV(voice)->offset * (1.0f / 12.0f));
}

/* Once per voice per block, from filter_process: the slide moves toward 0 by step x frames */
void glide_advance(uint8_t *filter_obj, int frames)
{
    volatile struct glide_voice *gv = (volatile struct glide_voice *)(filter_obj + 0x58);
    float off = gv->offset;
    if (off == 0.0f || frames <= 0)
        return;
    float d = gv->step * (float)frames;
    if (off > d)
        gv->offset = off - d;
    else if (off < -d)
        gv->offset = off + d;
    else
        gv->offset = 0.0f;
}
