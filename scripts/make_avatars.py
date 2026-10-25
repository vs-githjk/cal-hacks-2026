"""Agentverse avatars for the Tech Bazaar agents (#259): one theme, stdlib only (no Pillow).

    python3 -m scripts.make_avatars        # writes agents/avatars/<role>.png (256 x 256)

Each avatar is a navy tile with the agent's colour ring and its initials in white block letters. The caller, the
agent that places the approval phone call, is the one pink tile. Upload steps: agents/avatars/README.md.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "agents" / "avatars"
SIZE = 256
NAVY = (22, 33, 62)
WHITE = (255, 255, 255)
PINK = (255, 79, 163)
AGENTS = {   # role: (initials, ring colour, tile colour)
    "buyer": ("BU", (61, 139, 211), NAVY),
    "advocate": ("AD", (46, 173, 107), NAVY),
    "shield": ("SH", (245, 166, 35), NAVY),
    "caller": ("CA", WHITE, PINK),
    "pulse": ("PU", (20, 184, 166), NAVY),
    **{f"seller_{i}": (f"S{i}", (139, 92, 246), NAVY) for i in range(1, 7)},
}
FONT = {   # 5 x 7 block letters, one string per row
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
}
CELL = 14   # pixels per font cell


def render(initials: str, ring: tuple, tile: tuple) -> list[list[tuple]]:
    px = [[tile] * SIZE for _ in range(SIZE)]
    c, r_out, r_in = SIZE / 2, SIZE * 0.46, SIZE * 0.40
    for y in range(SIZE):
        for x in range(SIZE):
            d2 = (x + 0.5 - c) ** 2 + (y + 0.5 - c) ** 2
            if r_in ** 2 <= d2 <= r_out ** 2:
                px[y][x] = ring
    gap = CELL
    width = len(initials) * 5 * CELL + (len(initials) - 1) * gap
    x0, y0 = (SIZE - width) // 2, (SIZE - 7 * CELL) // 2
    for i, ch in enumerate(initials):
        gx = x0 + i * (5 * CELL + gap)
        for row, bits in enumerate(FONT[ch]):
            for col, bit in enumerate(bits):
                if bit == "1":
                    for yy in range(y0 + row * CELL, y0 + (row + 1) * CELL):
                        for xx in range(gx + col * CELL, gx + (col + 1) * CELL):
                            px[yy][xx] = WHITE
    return px


def png(px: list[list[tuple]]) -> bytes:
    raw = b"".join(b"\x00" + bytes(v for p in row for v in p) for row in px)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    head = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0)   # 8-bit RGB
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for role, (initials, ring, tile) in AGENTS.items():
        (OUT / f"{role}.png").write_bytes(png(render(initials, ring, tile)))
        print(f"wrote agents/avatars/{role}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
