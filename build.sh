#!/bin/sh
# Compile src/*.c into the code cave: out/cave.elf + out/cave.bin
set -e
cd "$(dirname "$0")"
mkdir -p out
arm-none-eabi-g++ -mcpu=cortex-m7 -mthumb -mfloat-abi=hard -mfpu=fpv5-d16 -O2 -ffreestanding -nostdlib -fno-exceptions \
  -fno-rtti -fno-threadsafe-statics -fno-use-cxa-atexit -fno-math-errno -std=gnu++17 -Wall -Werror -Wno-unused-function \
  -Wno-class-memaccess -Wno-unused-but-set-variable -Wno-unused-variable -Wno-unused-parameter -isystem src/munchi/sys -c -o out/munchi.o src/munchi.cpp
arm-none-eabi-gcc -mcpu=cortex-m7 -mthumb -mfloat-abi=hard -mfpu=fpv5-d16 -Os -ffreestanding -nostdlib \
  -fno-builtin -Wall -Wextra -Werror -T src/cave.ld -Wl,-e,0 -o out/cave.elf src/solo.c src/slice.c  src/filter.c src/filter_thunk.S src/fenv.c src/filt_tab.c src/filt_tab_thunk.S src/cpu.c src/od.c src/comp.c src/fx2.c src/fx2_thunk.S out/munchi.o
arm-none-eabi-objcopy -O binary -j .cave out/cave.elf out/cave.bin
arm-none-eabi-size -A out/cave.elf | grep -E 'cave|data|bss'
