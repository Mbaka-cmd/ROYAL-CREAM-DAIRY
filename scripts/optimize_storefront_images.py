"""Builds web-ready images for the storefront from the original artwork.

Run from the project root:  .venv/Scripts/python.exe scripts/optimize_storefront_images.py

Reads the originals (project root, or design/originals if they were moved) and writes:
  static/images/hero.webp        1600 px wide, home hero (desktop)
  static/images/hero-sm.webp      800 px wide, home hero (phones)
  static/images/meadow.webp      1280 px wide, delivery band background
  design/product-photos/*.webp    900 px max, upload these as product images in the owner dashboard
Originals are never modified or deleted.
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SEARCH = [ROOT, ROOT / "design" / "originals"]
STATIC = ROOT / "static" / "images"
PHOTOS = ROOT / "design" / "product-photos"

JOBS = [
    ("background.png", STATIC / "hero.webp", 1600, 78),
    ("background.png", STATIC / "hero-sm.webp", 800, 74),
    ("transition background.jpg", STATIC / "meadow.webp", 1280, 76),
    ("milk 1L.jpg", PHOTOS / "milk-1l.webp", 900, 82),
    ("yoghurt 500g.jpg", PHOTOS / "yoghurt-500g.webp", 900, 82),
    ("butter.png", PHOTOS / "butter.webp", 900, 82),
]


def find(name):
    for folder in SEARCH:
        path = folder / name
        if path.exists():
            return path
    return None


def main():
    STATIC.mkdir(parents=True, exist_ok=True)
    PHOTOS.mkdir(parents=True, exist_ok=True)
    for src_name, dest, width, quality in JOBS:
        src = find(src_name)
        if src is None:
            print(f"SKIP   {src_name} not found")
            continue
        with Image.open(src) as im:
            im = im.convert("RGB")
            if im.width > width or im.height > width:
                im.thumbnail((width, width), Image.LANCZOS)
            dest.parent.mkdir(parents=True, exist_ok=True)
            im.save(dest, "WEBP", quality=quality, method=6)
        print(f"OK     {dest.relative_to(ROOT)}  {dest.stat().st_size // 1024} KB  ({src_name})")


if __name__ == "__main__":
    main()
