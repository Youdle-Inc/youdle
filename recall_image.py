"""No-cost, article-specific recall illustration encoded for the existing ImgBB uploader.

This is a simple editorial safety graphic, not an imitation of an actual
recalled package. No paid image model, image library, or new service is used.
"""
import base64
import hashlib
import struct
import zlib


def make_recall_image(article, width=720, height=405):
    """Generate an original PNG with an unmistakable alert symbol.

    Different official recall roundups get different color palettes and
    arrangements. Images deliberately contain no false product depictions,
    text or logos.
    """
    # Weekly headlines are often identical, so include the actual sources.
    # A new set of recalls must never accidentally reuse last week\'s image.
    identity = "\n".join(str(article.get(field) or "") for field in (
        "title", "link", "content", "description"
    ))
    seed = hashlib.sha256(identity.encode("utf-8")).digest()
    palettes = [
        ((241, 247, 243), (30, 88, 64), (223, 163, 57)),
        ((250, 245, 234), (91, 66, 47), (186, 95, 49)),
        ((239, 246, 249), (34, 79, 106), (224, 164, 64)),
        ((247, 241, 248), (87, 61, 101), (213, 142, 55)),
    ]
    bg, accent, warning = palettes[seed[0] % len(palettes)]
    mid_x = width // 2
    mid_y = height // 2
    rows = []

    # Triangular alert, thick circular backdrop, unique side-column bars.
    circle_radius = 126
    stripe_width = 18 + seed[1] % 28
    for y in range(height):
        row = bytearray()
        for x in range(width):
            color = bg
            if x < stripe_width or x >= width - stripe_width:
                color = accent
            if abs(x - mid_x) < 210 and abs(y - mid_y) < 150:
                color = tuple(min(255, channel + 7) for channel in bg)
            dx, dy = x - mid_x, y - mid_y
            if dx * dx + dy * dy <= circle_radius * circle_radius:
                color = accent
            # Upright warning triangle
            local_y = y - (mid_y - 85)
            if 0 <= local_y <= 175:
                half_width = int(local_y * 0.60)
                if abs(dx) <= half_width:
                    color = warning
            # Exclamation mark and bottom dot in dark accent
            if mid_y - 3 <= y <= mid_y + 52 and abs(dx) <= 11:
                color = accent
            if (dx * dx + (y - (mid_y + 79)) ** 2) <= 12 ** 2:
                color = accent
            row.extend(color)
        rows.append(b"\x00" + bytes(row))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data +
                struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))

    pixels = b"".join(rows)
    png = (b"\x89PNG\r\n\x1a\n" +
           chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
           chunk(b"IDAT", zlib.compress(pixels, 6)) +
           chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")
