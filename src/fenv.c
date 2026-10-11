/*
 * Filter Type and filter envelope: the pad parameters. Original 1010music Blackbox, firmware 3.1.9.
 * The sound side is in filter.c; this registers the six new pad parameters and gives every pad record their defaults.
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
}
