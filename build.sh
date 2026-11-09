#!/bin/sh
# Compile src/*.c into the code cave: out/cave.elf + out/cave.bin
set -e
cd "$(dirname "$0")"
mkdir -p out
arm-none-eabi-gcc -mcpu=cortex-m7 -mthumb -mfloat-abi=hard -mfpu=fpv5-d16 -Os -ffreestanding -nostdlib \
  -fno-builtin -Wall -Wextra -Werror ${CPU_DIAG:+-DCPU_DIAG} -T src/cave.ld -Wl,-e,0 -o out/cave.elf src/solo.c src/slice.c  src/filter.c src/filter_thunk.S src/fenv.c src/filt_tab.c src/filt_tab_thunk.S src/glide.c src/glide_thunk.S src/cpu.c src/od.c src/clock.c src/delay.c src/grain.c src/cache.c src/cache_thunk.S src/grainmix_thunk.S
arm-none-eabi-objcopy -O binary -j .cave out/cave.elf out/cave.bin
arm-none-eabi-size -A out/cave.elf | grep -E 'cave|data|bss'
