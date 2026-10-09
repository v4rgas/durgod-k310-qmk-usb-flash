#!/usr/bin/env python3
"""Remap keys on a stock-firmware Durgod Taurus K310 (2f68:0042) from Linux.

Writes the keyboard's on-board "custom profile" (the one toggled with Fn+F12)
over the vendor HID interface. Protocol from david0/durgod-keymapper, checked
against Durgod Zeus Engine 1.0.9.27 and the stock K310 firmware 1.06.

    durgod_remap.py info              query firmware version (read-only)
    durgod_remap.py show  [SWAP...]   print the keymap that would be written
    durgod_remap.py write [SWAP...]   write it to the keyboard
    durgod_remap.py write             (no swaps) restores the factory layout

A SWAP is two key names joined by a colon, e.g. caps:esc
"""

import glob
import os
import select
import sys

VENDOR_ID = 0x2F68
PRODUCT_ID = 0x0042
VENDOR_USAGE_PAGE = bytes.fromhex("06c2ff")
EXPECTED_HW_TYPE = 4  # STM32 boards; the keymap below is from their firmware

KEEPALIVE = bytes.fromhex("0307e3")
INFO = bytes.fromhex("03038f")
RESET = bytes.fromhex("03058004ff")
WRITE = bytes.fromhex("0305810f")
SAVE = bytes.fromhex("030582")
DISCONNECT = bytes.fromhex("031988")
MAGIC = bytes.fromhex("78563412")

ROWS, COLS = 6, 21
FN = 0x10000

# Factory layout, taken from the default table in durgod-k310_4.bin (fw 1.06).
# 6 rows x 21 columns of USB HID usage codes; 0 = no key at that position.
DEFAULT_KEYMAP = [
    0x29, 0x00, 0x3a, 0x3b, 0x3c, 0x3d, 0x3e, 0x3f, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x00, 0x00, 0x00, 0x00,
    0x35, 0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x2d, 0x2e, 0x2a, 0x49, 0x4a, 0x4b, 0x53, 0x54, 0x55, 0x56,
    0x2b, 0x14, 0x1a, 0x08, 0x15, 0x17, 0x1c, 0x18, 0x0c, 0x12, 0x13, 0x2f, 0x30, 0x31, 0x4c, 0x4d, 0x4e, 0x5f, 0x60, 0x61, 0x57,
    0x39, 0x04, 0x16, 0x07, 0x09, 0x0a, 0x0b, 0x0d, 0x0e, 0x0f, 0x33, 0x34, 0x32, 0x28, 0x00, 0x00, 0x00, 0x5c, 0x5d, 0x5e, 0x00,
    0xe1, 0x64, 0x1d, 0x1b, 0x06, 0x19, 0x05, 0x11, 0x10, 0x36, 0x37, 0x38, 0x00, 0xe5, 0x00, 0x52, 0x00, 0x59, 0x5a, 0x5b, 0x00,
    0xe0, 0xe3, 0xe2, 0x00, 0x00, 0x00, 0x2c, 0x00, 0x00, 0x00, 0xe6, FN,   0x65, 0xe4, 0x50, 0x51, 0x4f, 0x00, 0x62, 0x63, 0x58,
]

KEY_NAMES = {
    "esc": 0x29, "caps": 0x39, "tab": 0x2b, "grave": 0x35, "backspace": 0x2a,
    "enter": 0x28, "space": 0x2c, "menu": 0x65,
    "lctrl": 0xe0, "lshift": 0xe1, "lalt": 0xe2, "lwin": 0xe3,
    "rctrl": 0xe4, "rshift": 0xe5, "ralt": 0xe6,
    "insert": 0x49, "home": 0x4a, "pgup": 0x4b, "delete": 0x4c, "end": 0x4d,
    "pgdn": 0x4e, "right": 0x4f, "left": 0x50, "down": 0x51, "up": 0x52,
    "print": 0x46, "scroll": 0x47, "pause": 0x48,
}
KEY_NAMES.update({"f%d" % (i + 1): 0x3a + i for i in range(12)})
KEY_NAMES.update({chr(ord("a") + i): 0x04 + i for i in range(26)})
KEY_NAMES.update({str((i + 1) % 10): 0x1e + i for i in range(10)})
CODE_NAMES = {code: name for name, code in KEY_NAMES.items()}
CODE_NAMES[FN] = "FN"


def build_keymap(swaps):
    keymap = list(DEFAULT_KEYMAP)
    for swap in swaps:
        try:
            a, b = (KEY_NAMES[name.lower()] for name in swap.split(":"))
        except (KeyError, ValueError):
            sys.exit("bad swap %r; use NAME:NAME with names from: %s"
                     % (swap, " ".join(sorted(KEY_NAMES))))
        ia, ib = DEFAULT_KEYMAP.index(a), DEFAULT_KEYMAP.index(b)
        keymap[ia], keymap[ib] = keymap[ib], keymap[ia]
    return keymap


def keymap_packets(keymap):
    assert len(keymap) == ROWS * COLS
    data = b"".join(code.to_bytes(4, "big") for code in keymap) + MAGIC
    chunks = [data[i:i + 32] for i in range(0, len(data), 32)]
    return [WRITE + bytes([i, 0, 0]) + chunk for i, chunk in enumerate(chunks)]


def print_keymap(keymap):
    for row in range(ROWS):
        cells = keymap[row * COLS:(row + 1) * COLS]
        print(" ".join("%5s" % (CODE_NAMES.get(c, "%02x" % c) if c else ".")[:5]
                       for c in cells))


def find_device():
    wanted = "HID_ID=0003:%08X:%08X" % (VENDOR_ID, PRODUCT_ID)
    for sysdir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        with open(sysdir + "/device/uevent") as f:
            if wanted not in f.read():
                continue
        with open(sysdir + "/device/report_descriptor", "rb") as f:
            if f.read(3) == VENDOR_USAGE_PAGE:
                return "/dev/" + os.path.basename(sysdir)
    sys.exit("Durgod K310 vendor interface not found; is the keyboard plugged in?")


class Keyboard:
    def __init__(self, path):
        try:
            self.fd = os.open(path, os.O_RDWR)
        except PermissionError:
            sys.exit("no permission to open %s; run with sudo" % path)

    def send(self, payload, timeout=1.0):
        while select.select([self.fd], [], [], 0)[0]:
            os.read(self.fd, 64)  # drop stale input
        os.write(self.fd, b"\x00" + payload.ljust(64, b"\x00"))
        if not select.select([self.fd], [], [], timeout)[0]:
            return b""
        return os.read(self.fd, 64)

    def info(self):
        resp = self.send(INFO)
        if resp[:3] != bytes.fromhex("83038f"):
            sys.exit("unexpected reply to version query: %s" % resp.hex())
        return {"version": "%d.%02x" % (resp[4], resp[3]), "hw_type": resp[5]}


def main(argv):
    if len(argv) < 2 or argv[1] not in ("info", "show", "write"):
        sys.exit(__doc__)
    command, swaps = argv[1], argv[2:]

    if command == "show":
        keymap = build_keymap(swaps)
        print_keymap(keymap)
        for packet in keymap_packets(keymap):
            print(packet.hex())
        return

    keyboard = Keyboard(find_device())
    info = keyboard.info()
    print("firmware %(version)s, hardware type %(hw_type)d" % info)
    if command == "info":
        return
    if info["hw_type"] != EXPECTED_HW_TYPE:
        sys.exit("refusing to write: this keymap is for hardware type %d"
                 % EXPECTED_HW_TYPE)

    keymap = build_keymap(swaps)
    keyboard.send(KEEPALIVE)
    keyboard.send(RESET)
    for packet in keymap_packets(keymap):
        resp = keyboard.send(packet)
        if resp[:4] != bytes.fromhex("8305810f"):
            sys.exit("write of chunk %d rejected (%s); custom profile is "
                     "incomplete, re-run to retry" % (packet[4], resp.hex()))
    keyboard.send(SAVE)
    keyboard.send(KEEPALIVE)
    keyboard.send(DISCONNECT)
    print("custom profile written; toggle it with Fn+F12")


if __name__ == "__main__":
    main(sys.argv)
