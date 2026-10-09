#!/usr/bin/env python3
"""Flash a Durgod Taurus K310 (hardware type 4) through Durgod's USB bootloader.

Protocol taken from Durgod Zeus Engine 1.0.9.27 and the stock firmware 1.06.

    durgod_flash.py enter          reboot the stock firmware into the bootloader
    durgod_flash.py bootinfo       query the bootloader (read-only)
    durgod_flash.py flash IMAGE    erase, write and verify IMAGE, then start it
    durgod_flash.py finish         leave the bootloader and start the firmware

"flash" stops before starting the image if anything fails; the keyboard then
stays in the bootloader and the command can simply be run again.
"""

import glob
import os
import select
import struct
import sys
import time

VENDOR_ID = 0x2F68
APP_PRODUCT_ID = 0x0042
BOOT_PRODUCT_ID = 0x80FF
VENDOR_USAGE_PAGE = bytes.fromhex("06c2ff")

HW_TYPE = 4
IMAGE_HEADER = bytes.fromhex("682f42000400")  # at 0xC0: VID, PID, hw type
MAX_IMAGE_SIZE = 0xD000  # stock firmware keeps its settings above this
SECTOR_SIZE = 512
PAGE_SIZE = 32
PAGES_PER_SECTOR = SECTOR_SIZE // PAGE_SIZE

APP_INFO = bytes.fromhex("03038f")
APP_ENTER_BOOTLOADER = bytes.fromhex("038f")
BOOT_INFO = bytes.fromhex("800008")
BOOT_ERASE = bytes.fromhex("000108")
BOOT_WRITE = bytes.fromhex("000225")
BOOT_VERIFY = bytes.fromhex("000308")
BOOT_VERIFY_ACK = bytes.fromhex("80030800")
BOOT_FINISH = bytes.fromhex("000408")


def find_hidraw(product_id):
    wanted = "HID_ID=0003:%08X:%08X" % (VENDOR_ID, product_id)
    for sysdir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(sysdir + "/device/uevent") as f:
                if wanted not in f.read():
                    continue
            with open(sysdir + "/device/report_descriptor", "rb") as f:
                if f.read(3) != VENDOR_USAGE_PAGE:
                    continue
        except OSError:
            continue  # device went away while we were looking
        return "/dev/" + os.path.basename(sysdir)
    return None


class Hid:
    def __init__(self, path):
        try:
            self.fd = os.open(path, os.O_RDWR)
        except PermissionError:
            sys.exit("no permission to open %s; run with sudo" % path)

    def write(self, payload):
        os.write(self.fd, b"\x00" + payload.ljust(64, b"\x00"))

    def read(self, timeout):
        if not select.select([self.fd], [], [], timeout)[0]:
            return b""
        return os.read(self.fd, 64)

    def drain(self):
        while select.select([self.fd], [], [], 0)[0]:
            os.read(self.fd, 64)


def open_bootloader():
    path = find_hidraw(BOOT_PRODUCT_ID)
    if path is None:
        sys.exit("bootloader (2f68:80ff) not found; run 'enter' first")
    return Hid(path)


def boot_info(boot):
    boot.drain()
    boot.write(BOOT_INFO)
    resp = boot.read(5)
    if not resp:
        sys.exit("no reply from the bootloader")
    print("bootloader info: %s" % resp[:16].hex(" "))
    return resp


def enter():
    if find_hidraw(BOOT_PRODUCT_ID):
        print("already in the bootloader")
        return
    path = find_hidraw(APP_PRODUCT_ID)
    if path is None:
        sys.exit("keyboard (2f68:0042) not found")
    app = Hid(path)
    app.drain()
    app.write(APP_INFO)
    resp = app.read(1)
    if resp[:3] != bytes.fromhex("83038f") or resp[5] != HW_TYPE:
        sys.exit("unexpected firmware reply, not entering the bootloader: %s"
                 % resp.hex())
    print("stock firmware %d.%02x, hardware type %d" % (resp[4], resp[3], resp[5]))
    app.write(APP_ENTER_BOOTLOADER)
    for _ in range(100):
        time.sleep(0.2)
        if find_hidraw(BOOT_PRODUCT_ID):
            print("bootloader is up (2f68:80ff)")
            return
    sys.exit("bootloader did not appear within 20 s; check lsusb")


def load_image(path):
    with open(path, "rb") as f:
        image = f.read()
    if len(image) > MAX_IMAGE_SIZE:
        sys.exit("image is too large")
    if image[0xC0:0xC6] != IMAGE_HEADER:
        sys.exit("image has no K310 type-4 header at 0xC0")
    if sum(struct.unpack_from("<8I", image, 0)) & 0xFFFFFFFF:
        sys.exit("image vector checksum is wrong")
    sectors = -(-len(image) // SECTOR_SIZE)
    return image.ljust(sectors * SECTOR_SIZE, b"\x00"), sectors


def pages(image, sectors):
    for sector in range(sectors):
        for page in range(PAGES_PER_SECTOR):
            offset = sector * SECTOR_SIZE + page * PAGE_SIZE
            yield sector, page, image[offset:offset + PAGE_SIZE]


def flash(path):
    image, sectors = load_image(path)
    boot = open_bootloader()
    boot_info(boot)

    print("erasing")
    time.sleep(1)
    boot.drain()
    boot.write(BOOT_ERASE + bytes([HW_TYPE]))
    resp = boot.read(20)
    if len(resp) < 4 or resp[1] != 0x01 or resp[3] != 0x00:
        sys.exit("erase failed (%s); still in the bootloader, safe to retry"
                 % resp.hex())

    print("writing %d sectors" % sectors)
    time.sleep(1)
    for sector, page, data in pages(image, sectors):
        boot.write(BOOT_WRITE + bytes([sector, page]) + data)
        resp = boot.read(5)
        if len(resp) < 6 or resp[1] != 0x02 or resp[5] != 0x00:
            sys.exit("write failed at sector %d page %d (%s); still in the "
                     "bootloader, safe to retry" % (sector, page, resp.hex()))

    print("verifying")
    time.sleep(1)
    boot.write(BOOT_VERIFY + bytes([HW_TYPE]))
    for sector, page, data in pages(image, sectors):
        resp = boot.read(5)
        boot.write(BOOT_VERIFY_ACK)
        if (len(resp) < 37 or resp[0] != 0x80 or resp[1] != 0x03
                or resp[3] != sector or resp[4] != page or resp[5:37] != data):
            sys.exit("verify failed at sector %d page %d (%s); still in the "
                     "bootloader, safe to retry" % (sector, page, resp.hex()))
    print("verified")
    finish(boot)


def finish(boot=None):
    boot = boot or open_bootloader()
    time.sleep(0.5)
    boot.write(BOOT_FINISH)
    print("finish sent; the keyboard should restart into the new image")


def main(argv):
    command = argv[1] if len(argv) > 1 else ""
    if command == "enter" and len(argv) == 2:
        enter()
    elif command == "bootinfo" and len(argv) == 2:
        boot_info(open_bootloader())
    elif command == "flash" and len(argv) == 3:
        flash(argv[2])
    elif command == "finish" and len(argv) == 2:
        finish()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
