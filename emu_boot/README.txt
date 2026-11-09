Full-firmware boot under Unicorn (stock 3.1.9 or any build): the real FreeRTOS, HAL init, FatFS, preset loading and
the audio task rendering blocks, for end-to-end profiles.

  m7.py      Cortex-M shim (MRS/MSR/CPS, exception entry/return with FP frames, SVC/PendSV/SysTick, BASEPRI) and
             peripheral models (RCC ready bits, fixed status registers, poll-loop breaking). FW = the image to boot.
  boot.py    reset -> osKernelStart (snap_kstart.pkl); sd.py: the SD card as a FAT32 image (sdcard.img) built from
             a preset folder in ~/Documents/Blackbox (read only); audio.py: injected SAI DMA / LTDC interrupts.
  make_snapshots.py   boot + SD mount + preset load -> snap_loaded.pkl (several minutes)
  profile.py <warm> <blocks> [snap] [notes lo-hi]   instructions per audio block by function (self / inclusive)
  funcs.txt  function names (Ghidra; append a build's `arm-none-eabi-nm out/cave.elf` symbols for its cave)

Not committed: sdcard.img (holds the user's preset), *.pkl snapshots (large). Counts are instructions, not cycles.
Written by a helper agent, 2026-10-15; log hook range fixed for modded images.
