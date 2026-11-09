/*
 * (S.1) The stock grain renderer's mix loop (FUN_08057db8 @0x08057ee2 .. 0x08057f1c, b.w here @0x08057ee2): the
 * window index (pos << 13) / len by a running quotient and remainder, not an sdiv every sample (3072 a block on
 * 4 granular pads). Exact: the same index, the same float ops in the same order. pos < 0, len <= 0 or an overflowing
 * pos: the stock loop as it was.
 * In (as stock): r0 src R, r1 pos << 13, r3 end of src R, r5 window table, r6 out R, r7 len, ip out L, lr src L,
 * s12 gain L, s0 gain R. Out: on at 0x08057f1e (r1, r2 dead there; r4, r8.. untouched).
 */
    .syntax unified
    .thumb
    .text

    .global grain_mix
    .thumb_func
    .type grain_mix, %function
grain_mix:
    cmp     r7, #0
    ble     9f
    cmp     r1, #0
    blt     9f
    subs    r2, r3, r0                  /* count * 4 */
    lsls    r2, r2, #11                 /* count * 0x2000 */
    adds    r2, r2, r1
    bvs     9f                          /* (pos << 13 would wrap: as stock) */
    push    {r8, r9, r10}
    sdiv    r8, r1, r7                  /* q */
    mls     r2, r8, r7, r1              /* rem */
    mov     r1, r8
    mov     r10, #0x2000
    sdiv    r8, r10, r7                 /* dq */
    mls     r9, r8, r7, r10             /* dr < len */
1:  vldmia  lr!, {s14}
    vldr    s15, [ip]
    add     r10, r5, r1, lsl #2
    vldr    s13, [r10]
    add     r1, r1, r8
    add     r2, r2, r9
    cmp     r2, r7
    itt     ge
    subge   r2, r2, r7
    addge   r1, r1, #1
    vmul.f32 s14, s14, s13
    vfma.f32 s15, s14, s12
    vstmia  ip!, {s15}
    vldmia  r0!, {s14}
    vldr    s15, [r6]
    vmul.f32 s14, s14, s13
    cmp     r3, r0
    vfma.f32 s15, s14, s0
    vstmia  r6!, {s15}
    bne     1b
    pop     {r8, r9, r10}
    ldr     pc, =0x08057f1f

9:  vldmia  lr!, {s14}                  /* the stock loop */
    vldr    s15, [ip]
    sdiv    r2, r1, r7
    add     r2, r5, r2, lsl #2
    add     r1, r1, #8192
    vldr    s13, [r2]
    vmul.f32 s14, s14, s13
    vfma.f32 s15, s14, s12
    vstmia  ip!, {s15}
    vldmia  r0!, {s14}
    vldr    s15, [r6]
    vmul.f32 s14, s14, s13
    cmp     r3, r0
    vfma.f32 s15, s14, s0
    vstmia  r6!, {s15}
    bne     9b
    ldr     pc, =0x08057f1f
