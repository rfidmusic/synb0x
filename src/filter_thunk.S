/*
 * Per-voice filter call sites. r0 = filter object, r1 = audio buffer; filter_process also gets r2 = the pad object the
 * voice belongs to and r3 = the voice's amp envelope stage byte (the envelope object's +4).
 * Sample pads (class A, 0x08055c60): voice = obj - 0xa8, amp envelope at voice + 0x28, pad in r6 (FUN_08056fd0).
 * Clip / slicer pads (class B, 0x080669d6): two voice blocks per pad (pad + 0x260 + v * 0x410), filter object at
 * block + 0x14c, amp envelope at block + 0x258, pad in r6 (FUN_080667b8 sets it once, at 0x080667dc). Before this
 * build the pad was taken as obj - 0x3ac, which is right only for the first voice.
 */
    .syntax unified
    .thumb
    .text

    .global filter_voice_a
    .thumb_func
    .type filter_voice_a, %function
filter_voice_a:
    mov     r2, r6
    sub.w   r3, r0, #0x7c               /* voice + 0x2c = obj - 0xa8 + 0x2c */
    b.w     filter_process

    .global filter_voice_b
    .thumb_func
    .type filter_voice_b, %function
filter_voice_b:
    mov     r2, r6
    add.w   r3, r0, #0x110              /* block + 0x25c = obj - 0x14c + 0x25c */
    b.w     filter_process
