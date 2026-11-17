"""Render pr-pulse logo option A (interference disc) to PNG, stdlib only.
Two circles (cyan #06B6D4, violet #8B5CF6) at 80% opacity, screen-blended on #0B0F19,
same geometry as the SVG (viewBox 100: centers (40,50) and (60,50), r=27). 4x4 supersampling."""
import struct, sys, zlib

def hexrgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))

def render(size, path, rounded=False):
    bg = hexrgb("#0B0F19"); c1 = hexrgb("#06B6D4"); c2 = hexrgb("#8B5CF6"); a = 0.8
    k = size / 100.0; ss = 4
    circles = [((40 * k, 50 * k), 27 * k, c1), ((60 * k, 50 * k), 27 * k, c2)]
    rx = 22 * k
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            acc = [0.0, 0.0, 0.0]; cover_bg = 0
            for sy in range(ss):
                py = y + (sy + 0.5) / ss
                for sx in range(ss):
                    px = x + (sx + 0.5) / ss
                    if rounded:   # optional rounded-square mask (transparent corners)
                        cx_ = min(max(px, rx), size - rx); cy_ = min(max(py, rx), size - rx)
                        if (px - cx_) ** 2 + (py - cy_) ** 2 > rx * rx:
                            continue
                    cover_bg += 1
                    col = list(bg)
                    for (ox, oy), r, c in circles:
                        if (px - ox) ** 2 + (py - oy) ** 2 <= r * r:
                            col = [b * (1 - a) + (1 - (1 - b) * (1 - cc)) * a for b, cc in zip(col, c)]
                    for i in range(3):
                        acc[i] += col[i]
            n = ss * ss
            if cover_bg == 0:
                row += bytes([0, 0, 0, 0])
            else:
                row += bytes([round(acc[i] / cover_bg * 255) for i in range(3)] + [round(cover_bg / n * 255)])
        rows.append(bytes(row))
    raw = b"".join(rows)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    open(path, "wb").write(png)
    print("wrote", path, size)

out = sys.argv[1]
render(1024, f"{out}/pr-pulse-slack-icon-1024.png")
render(256, f"{out}/pr-pulse-notification-icon-256.png", rounded=True)
