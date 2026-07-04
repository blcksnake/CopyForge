#!/usr/bin/env python3
"""Generate a simple multi-size ICO for CopyForge."""
from __future__ import annotations

import struct
from pathlib import Path


def _inside_rounded_rect(x: int, y: int, size: int, radius: int) -> bool:
    if radius <= 0:
        return True
    left = radius
    right = size - radius - 1
    top = radius
    bottom = size - radius - 1
    if left <= x <= right or top <= y <= bottom:
        return True
    cx = left if x < left else right
    cy = top if y < top else bottom
    dx = x - cx
    dy = y - cy
    return (dx * dx + dy * dy) <= (radius * radius)


def _pixel_rgba(x: int, y: int, size: int) -> tuple[int, int, int, int]:
    radius = max(2, size // 7)
    if not _inside_rounded_rect(x, y, size, radius):
        return (0, 0, 0, 0)

    t = y / max(1, size - 1)
    r = int(20 + 18 * t)
    g = int(44 + 26 * t)
    b = int(66 + 30 * t)
    a = 255

    border = max(1, size // 16)
    if (
        x < border
        or y < border
        or x >= size - border
        or y >= size - border
    ) and _inside_rounded_rect(x, y, size, radius):
        return (90, 185, 235, 255)

    # Stylized C on left
    c_left = int(size * 0.20)
    c_right = int(size * 0.50)
    c_top = int(size * 0.25)
    c_bottom = int(size * 0.75)
    c_thick = max(1, size // 10)
    in_c_box = c_left <= x <= c_right and c_top <= y <= c_bottom
    c_stroke = (
        (x <= c_left + c_thick)
        or (y <= c_top + c_thick)
        or (y >= c_bottom - c_thick)
    )
    c_open = x > int(size * 0.43)
    if in_c_box and c_stroke and not c_open:
        return (180, 235, 255, a)

    # Stylized F on right
    f_left = int(size * 0.55)
    f_right = int(size * 0.80)
    f_top = int(size * 0.25)
    f_bottom = int(size * 0.75)
    f_thick = max(1, size // 10)
    if f_left <= x <= f_right and f_top <= y <= f_bottom:
        if x <= f_left + f_thick:
            return (110, 220, 255, a)
        if y <= f_top + f_thick:
            return (110, 220, 255, a)
        mid_y = int(size * 0.50)
        if mid_y - f_thick // 2 <= y <= mid_y + f_thick // 2 and x <= int(size * 0.72):
            return (110, 220, 255, a)

    return (r, g, b, a)


def _bmp_image_for_ico(size: int) -> bytes:
    header_size = 40
    row_mask_bytes = ((size + 31) // 32) * 4
    xor_size = size * size * 4
    and_size = row_mask_bytes * size

    bmp_header = struct.pack(
        "<IIIHHIIIIII",
        header_size,
        size,
        size * 2,
        1,
        32,
        0,
        xor_size,
        0,
        0,
        0,
        0,
    )

    pixels = bytearray()
    for y in range(size - 1, -1, -1):
        for x in range(size):
            r, g, b, a = _pixel_rgba(x, y, size)
            pixels.extend((b, g, r, a))

    mask = bytes(and_size)
    return bmp_header + pixels + mask


def build_ico(path: Path) -> None:
    sizes = [16, 24, 32, 48, 64, 128]
    images = [_bmp_image_for_ico(size) for size in sizes]

    icon_dir = struct.pack("<HHH", 0, 1, len(images))
    entries = bytearray()

    offset = 6 + (16 * len(images))
    for size, img in zip(sizes, images):
        width = size if size < 256 else 0
        height = size if size < 256 else 0
        entry = struct.pack(
            "<BBBBHHII",
            width,
            height,
            0,
            0,
            1,
            32,
            len(img),
            offset,
        )
        entries.extend(entry)
        offset += len(img)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(icon_dir)
        f.write(entries)
        for img in images:
            f.write(img)


if __name__ == "__main__":
    output = Path(__file__).resolve().parent.parent / "assets" / "copyforge.ico"
    build_ico(output)
    print(f"Generated icon: {output}")