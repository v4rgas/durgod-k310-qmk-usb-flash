#!/bin/sh
set -e
cd "$(dirname "$0")"
arm-none-eabi-gcc -mcpu=cortex-m0 -mthumb -Os -ffreestanding -nostdlib -Wall -Wextra \
    -T link.ld -o stepstone.elf stepstone.c
arm-none-eabi-objcopy -O binary stepstone.elf stepstone.raw
python3 mkimage.py stepstone.raw stepstone.bin
rm stepstone.raw
