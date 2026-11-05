"""Builds the optimised logo files used by the site from design/rc-logo-original.jpg.
Prints a JSON summary (sampled colours and sizes) as its last line."""
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "design" / "rc-logo-original.jpg"
OUT = ROOT / "static" / "images"
FALLBACK_NAVY = (11, 31, 79)


def to_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def luminance(rgb):
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def median_color(pixels):
    pixels = list(pixels)
    return tuple(sorted(p[i] for p in pixels)[len(pixels) // 2] for i in range(3))


def sample_background(img):
    w, h = img.size
    patch = max(4, min(w, h) // 100)
    samples = []
    for x, y in ((0, 0), (w - patch, 0), (0, h - patch), (w - patch, h - patch)):
        samples.extend(img.crop((x, y, x + patch, y + patch)).getdata())
    return median_color(samples)


def sample_navy(img):
    """Average the dark blue pixels of the 'ROYAL CREAM' lettering."""
    w, h = img.size
    band = img.crop((int(w * 0.08), int(h * 0.52), int(w * 0.92), int(h * 0.70)))
    dark = [p for p in band.getdata() if p[0] < 45 and p[1] < 70 and p[2] > p[1] and 50 < p[2] < 150]
    if len(dark) < 300:
        return FALLBACK_NAVY
    avg = tuple(sum(p[i] for p in dark) // len(dark) for i in range(3))
    if avg[2] < 60 or luminance(avg) > 0.09:
        return FALLBACK_NAVY
    return avg


def main():
    if not SRC.exists():
        raise SystemExit(f"Logo not found: {SRC}")
    resample = Image.Resampling.LANCZOS
    img = Image.open(SRC).convert("RGB")
    w, h = img.size
    bg = sample_background(img)
    navy = sample_navy(img)
    OUT.mkdir(parents=True, exist_ok=True)

    header_h = 128  # 2x of the 64px display height
    header_w = round(w * header_h / h)
    img.resize((header_w, header_h), resample).save(OUT / "logo-header.webp", "WEBP", quality=90, method=6)

    og = Image.new("RGB", (1200, 630), bg)
    logo = img.resize((round(w * 590 / h), 590), resample)
    og.paste(logo, ((1200 - logo.width) // 2, 20))
    og.save(OUT / "og-default.jpg", "JPEG", quality=88, optimize=True)

    icon = Image.new("RGB", (180, 180), bg)
    scale = min(156 / w, 156 / h)
    small = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), resample)
    icon.paste(small, ((180 - small.width) // 2, (180 - small.height) // 2))
    icon.save(OUT / "icon-180.png", "PNG", optimize=True)

    print(json.dumps({
        "bg": to_hex(bg),
        "navy": to_hex(navy),
        "source_size": [w, h],
        "header_w_1x": round(w * 64 / h),
    }))


if __name__ == "__main__":
    main()