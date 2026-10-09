# QMK on a Durgod Taurus K310 without opening the case

The documented way to put QMK on a Durgod K310/K320 is to open the keyboard and
short two pads (BOOT0 to Vdd) to reach the STM32's ROM bootloader. This repo
does the same thing over USB, from Linux, with the case closed:

1. ask the stock firmware to reboot into Durgod's own USB bootloader;
2. use that bootloader to flash a tiny "stepping stone" image;
3. the stepping stone jumps to the ST ROM bootloader (`0483:df11`);
4. back up the chip and flash QMK with `dfu-util`, as in the QMK docs.

It also includes a tool that only remaps keys on the stock firmware, if that is
all you want.

**Use at your own risk.** This worked once, on one keyboard. If it goes wrong
the fallback is the documented procedure: open the case and short BOOT0.

## What it was tested on

| | |
|---|---|
| Keyboard | Durgod Taurus K310, no backlight, USB ID `2f68:0042` |
| MCU | STM32F070RB ("hardware type 4") |
| Stock firmware | 1.06 |
| Durgod bootloader | USB ID `2f68:80ff`, "Durgod BootLoad" |
| Host | Arch Linux, Python 3, dfu-util, QMK `durgod/k310/base` |

Not tested: K320, backlit variants (Corona, Nebula, Aurora), and K310 boards
with an NXP LPC controller (hardware types 1 and 2). The stepping stone carries
a K310 type-4 header and assumes an STM32F070xB, so do not flash it on anything
else. `durgod_flash.py enter` refuses to start unless the keyboard reports
hardware type 4.

## Requirements

- Linux with Python 3 (no extra modules; the tools talk to `/dev/hidraw*` directly)
- `dfu-util`, and a working QMK setup for `durgod/k310/base`
- a second keyboard, in case you have to type while this one is in a bootloader
- optional: `arm-none-eabi-gcc` to rebuild the stepping stone

The tools need access to the keyboard's hidraw device. Either run them with
`sudo`, or install a udev rule and replug the keyboard:

```sh
echo 'KERNEL=="hidraw*", ATTRS{idVendor}=="2f68", TAG+="uaccess"' \
  | sudo tee /etc/udev/rules.d/70-durgod.rules
```

## Steps

### 1. Check the keyboard

```sh
./durgod_remap.py info
```

It must print `firmware 1.06, hardware type 4`. Stop if the hardware type is
anything else.

### 2. Get the stock firmware image

Durgod ships it inside Zeus Engine. Download the installer from
<https://www.durgod.com/softwares/> and unpack it without running it:

```sh
7z x Durgod_Zeus_Engine_1.0.9.27.exe -ozeus
cp 'zeus/$APPDATA/Durgod Zeus Engine/bin/durgod-k310_4.bin' .
```

`durgod-k310_4.bin` is firmware 1.06 for hardware type 4. You need it for the
round-trip test below and for any recovery through Durgod's bootloader. It is
not included here because it is Durgod's code.

### 3. Round-trip test with the stock image

```sh
./durgod_flash.py enter
./durgod_flash.py bootinfo
./durgod_flash.py flash durgod-k310_4.bin
```

`enter` makes the keyboard reappear as `2f68:80ff`; it stops typing until a
flash finishes. `bootinfo` should print `08 00 08 42 00 04 ...` (product 0042,
hardware type 4). `flash` erases, writes, verifies and restarts the keyboard,
which should come back as a normal stock K310. This proves the flasher works on
your board before anything unusual is written.

If `flash` fails before the end, the keyboard stays in the bootloader and the
command can be run again.

### 4. Flash the stepping stone

```sh
./durgod_flash.py enter
./durgod_flash.py flash stepstone/stepstone.bin
dfu-util --list
```

Within a few seconds `dfu-util` should show `Found DFU: [0483:df11]`.

### 5. Back up the chip

```sh
dfu-util -a 0 -d 0483:df11 -s 0x08000000:0x20000 -U k310_full_flash.bin
```

This saves all 128 KB, including Durgod's bootloader, which the next step
overwrites.

### 6. Flash QMK

```sh
qmk flash -kb durgod/k310/base -km default
```

The keyboard restarts as "DURGOD Taurus K310 (QMK)". From now on, hold the
top-left key while plugging in to reach the ST bootloader again.

## If something goes wrong

- **A flash fails during erase, write or verify.** The keyboard is still in
  Durgod's bootloader. Run `flash` again, with the stock image if you want to
  go back.
- **The stepping stone is flashed but `0483:df11` never appears.** Before
  jumping to the ROM bootloader the stepping stone re-arms Durgod's "stay in
  bootloader" flag. Replug the keyboard: it should come up as `2f68:80ff`, and
  the stock image can be flashed again. This path was not needed in the one
  real run, so it is untested.
- **Nothing enumerates at all.** Open the case and use the BOOT0 short from the
  [QMK K3x0 readme](https://github.com/qmk/qmk_firmware/blob/master/keyboards/durgod/k3x0/readme.md).
  The ROM bootloader cannot be erased, so the board is not bricked.
- **Going back to stock after QMK.** Write the backup from step 5 over DFU,
  then flash the stock image with `durgod_flash.py`. The backup holds Durgod's
  bootloader and the stepping stone with the bootloader flag set, so the
  keyboard should come up in Durgod's bootloader. Untested.

## Remapping keys on the stock firmware

If you only want to move keys and keep Durgod's firmware:

```sh
./durgod_remap.py show caps:esc     # dry run: print the layout and packets
./durgod_remap.py write caps:esc    # write it to the keyboard
```

This writes the on-board custom profile, which is switched on and off with
Fn+F12. The stock firmware does not allow changing the default layout itself.
`write` with no arguments puts the factory layout back in the custom profile.

## How it works

All of this goes over the keyboard's vendor HID interface (usage page 0xFFC2,
64-byte reports, report ID 0). Flash layout on a type-4 board:

| Address | Contents |
|---|---|
| `0x08000000` | Durgod's bootloader (12 KB) |
| `0x08003000` | application (stock firmware, or the stepping stone) |
| `0x08010000` | custom key profile |
| `0x0801C800` | boot flag: `0x12345678` means "stay in the bootloader" |

### Stock firmware commands

| Payload | Meaning |
|---|---|
| `03 03 8F` | version query; reply `83 03 8F`, byte 3 = minor, byte 4 = major, byte 5 = hardware type |
| `03 8F` | write the boot flag and reset into Durgod's bootloader |
| `03 07 E3` | keepalive |
| `03 05 80 04 FF` | start writing the custom profile |
| `03 05 81 0F <n> 00 00 <32 bytes>` | profile chunk `n` (0..15); reply starts `83 05 81 0F` |
| `03 05 82` | save the custom profile |
| `03 19 88` | sent when Durgod's software disconnects |

The profile is 126 big-endian 32-bit HID usage codes (6 rows by 21 columns,
`0x00010000` = Fn) followed by `78 56 34 12`.

### Bootloader commands

| Payload | Meaning | Reply |
|---|---|---|
| `80 00 08` | device info | bytes 3-4 = product ID, byte 5 = hardware type |
| `00 01 08 <type>` | erase the application | byte 1 = `01`, byte 3 = `00` |
| `00 02 25 <sector> <page> <32 bytes>` | write one page | byte 1 = `02`, byte 5 = `00` |
| `00 03 08 <type>` | start verify; the device then sends every page | `80 03 .. <sector> <page> <32 bytes>` |
| `80 03 08 00` | acknowledge one verify page | next page |
| `00 04 08` | finish: restart into the application | none |

A sector is 512 bytes, made of 16 pages of 32 bytes. The image is padded with
zeros to a whole number of sectors.

### Image format

An image is linked at `0x08003000` and starts with a normal Cortex-M0 vector
table. Two things were copied from the stock image without knowing whether the
bootloader checks them:

- the word at offset `0x1C` makes the first eight words sum to zero;
- eight bytes at offset `0xC0`: `68 2F 42 00 04 00 06 01` (vendor ID, product
  ID, hardware type, version 1.06).

### The stepping stone

`stepstone/stepstone.c` is about 750 bytes and uses no interrupts. It:

1. masks interrupts and clears SysTick and the NVIC;
2. switches the clock back to the internal oscillator;
3. re-arms the boot flag at `0x0801C800`;
4. resets every peripheral, which also drops the USB connection;
5. maps system memory at address 0 and jumps to the ROM bootloader at
   `0x1FFFC800`.

Every wait loop is bounded, and a fault resets the chip.

Rebuild with `stepstone/build.sh`. The included `stepstone.bin` is the exact
binary that was used (SHA-256
`62c0423e20c0eb09fa5a59b3aa60bdfe3f325fcbf3f3a41351187d46a7588d83`).

## Credits

- [david0/durgod-keymapper](https://github.com/david0/durgod-keymapper) for the
  key remap protocol, which `durgod_remap.py` follows.
- [iliazeus/durgod](https://github.com/iliazeus/durgod) for earlier protocol
  notes on the K320 Nebula.
- The QMK maintainers of `durgod/k3x0` (dkjer, tylert) for the port and the
  BOOT0 procedure.
- The bootloader protocol was worked out by static analysis of Durgod Zeus
  Engine 1.0.9.27 and the stock firmware.

Licensed under the GPL, version 3 (see `LICENSE`).
