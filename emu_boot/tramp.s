.syntax unified
.thumb
.arch armv7e-m
@ fake DMA IRQ handler at 0x00000100: FUN_08041534(0x24001f90, *(u32*)0x000001F0)
push {r4, lr}
ldr r0, =0x24001f90
ldr r1, =0x000001F0
ldr r1, [r1]
ldr r2, =0x08041535
blx r2
pop {r4, pc}
.ltorg
