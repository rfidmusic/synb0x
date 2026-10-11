/*
 * Glide call sites (see glide.c).
 */
    .syntax unified
    .thumb
    .text

/* In place of the eight sample-pad note-on calls (bl FUN_08058548 in FUN_080596b0): r0 = engine pad. Note whether a
   note of the pad is held, then continue into the stock note-on with every register, s0-s15 and the stack (its
   arguments 5-7) exactly as they were. */
    .global glide_note_on
    .thumb_func
    .type glide_note_on, %function
glide_note_on:
    push    {r0, r1, r2, r3, r4, r5, r12, lr}
    vpush   {s0-s15}
    bl      glide_pre
    vpop    {s0-s15}
    pop     {r0, r1, r2, r3, r4, r5, r12, lr}
    ldr     r12, =0x08058548 + 1
    bx      r12

/* In place of bl FUN_0805f6b8 (2^(semitones / 12), argument r0) at the new-voice note-on (0x0805892a: r5 voice,
   r4 pad, r7 note) and the legato retune (0x0805864c: r6 voice, r4 pad, r3 note). */
    .global glide_start_thunk
    .thumb_func
    .type glide_start_thunk, %function
glide_start_thunk:
    push    {r0, lr}
    mov     r0, r5
    mov     r1, r4
    mov     r2, r7
    bl      glide_start
    pop     {r0, lr}
    ldr     r12, =0x0805f6b8 + 1
    bx      r12

    .global glide_retune_thunk
    .thumb_func
    .type glide_retune_thunk, %function
glide_retune_thunk:
    push    {r0, lr}
    mov     r2, r3
    mov     r0, r6
    mov     r1, r4
    bl      glide_retune
    pop     {r0, lr}
    ldr     r12, =0x0805f6b8 + 1
    bx      r12

/* In place of bl FUN_0805f728 (2^x, x in s0) in the voice process (0x080570b2, 0x0805743a): voice in r4. */
    .global glide_rate_thunk
    .thumb_func
    .type glide_rate_thunk, %function
glide_rate_thunk:
    mov     r0, r4
    b.w     glide_rate
    .ltorg
