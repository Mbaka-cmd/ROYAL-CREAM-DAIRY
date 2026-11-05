import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from PIL import Image

BASE = Path(settings.BASE_DIR)
STATIC = BASE / "static"
TEMPLATES = BASE / "templates"


def css(name):
    return (STATIC / "css" / name).read_text(encoding="utf-8")


def tokens():
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\s*;", css("site.css")))


def luminance(hex_color):
    h = hex_color.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def ratio(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def template_classes():
    found = {}
    files = [TEMPLATES / "base.html", TEMPLATES / "403.html", TEMPLATES / "404.html"]
    for folder in ("storefront", "catalogue", "checkout", "dashboard"):
        files += sorted((TEMPLATES / folder).glob("*.html"))
    for path in files:
        text = path.read_text(encoding="utf-8")
        for attr in re.findall(r'class="([^"]*)"', text):
            cleaned = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", attr)
            for token in cleaned.split():
                if token.endswith("-"):  # dynamic fragment such as st-{{ status }}
                    continue
                found.setdefault(token, path.name)
    return found


class LogoAssetTests(TestCase):
    def test_generated_assets_exist_with_expected_sizes(self):
        header = Image.open(STATIC / "images" / "logo-header.webp")
        self.assertEqual(header.height, 128)
        self.assertGreater(header.width, 60)
        self.assertEqual(Image.open(STATIC / "images" / "og-default.jpg").size, (1200, 630))
        self.assertEqual(Image.open(STATIC / "images" / "icon-180.png").size, (180, 180))

    def test_original_is_kept_out_of_the_served_static_folder(self):
        self.assertTrue((BASE / "design" / "rc-logo-original.jpg").exists())
        self.assertFalse((STATIC / "images" / "rc-logo-original.jpg").exists())

    def test_header_files_are_small(self):
        self.assertLess((STATIC / "images" / "logo-header.webp").stat().st_size, 40_000)
        self.assertLess((STATIC / "images" / "og-default.jpg").stat().st_size, 250_000)


class HeaderTests(TestCase):
    def test_logo_is_the_first_thing_in_the_header(self):
        html = self.client.get("/").content.decode()
        self.assertRegex(html, r'<a class="brand"[^>]*aria-label="Royal Cream Dairy home">\s*<img class="brand-logo"')
        self.assertIn("images/logo-header.webp", html)
        self.assertIn("images/icon-180.png", html)

    def test_logo_is_decorative_because_the_link_has_a_name(self):
        html = self.client.get("/").content.decode()
        self.assertRegex(html, r'<img class="brand-logo"[^>]*alt=""')
        self.assertIn('width="', html)
        self.assertIn('height="64"', html)

    def test_logo_appears_on_other_pages_and_the_dashboard(self):
        for path in ["/products/", "/checkout/", "/privacy/", "/owner/login/"]:
            with self.subTest(path=path):
                self.assertContains(self.client.get(path), 'class="brand-logo"')

    def test_theme_color_matches_the_navy(self):
        html = self.client.get("/").content.decode()
        self.assertIn(f'<meta name="theme-color" content="{tokens()["navy"]}">', html)

    @override_settings(DEFAULT_OG_IMAGE="images/og-default.jpg", SITE_URL="https://shop.test")
    def test_social_preview_uses_the_logo_image(self):
        self.assertContains(self.client.get("/"), 'content="https://shop.test/static/images/og-default.jpg"')


class StylesheetTests(TestCase):
    def test_brand_tokens_exist(self):
        found = tokens()
        for name in ["ivory", "navy", "gold", "gold-ink", "ink", "muted", "danger", "paper"]:
            self.assertIn(name, found)

    def test_every_variable_used_is_defined(self):
        site = css("site.css")
        defined = set(re.findall(r"--([a-z0-9-]+)\s*:", site))
        for name in ("site.css", "dashboard.css"):
            used = set(re.findall(r"var\(--([a-z0-9-]+)", css(name)))
            self.assertEqual(used - defined, set(), f"undefined variables in {name}")

    def test_no_leftover_variables_from_the_old_theme(self):
        for name in ("site.css", "dashboard.css"):
            text = css(name)
            self.assertNotIn("var(--green)", text)
            self.assertNotIn("var(--cream)", text)

    def test_colour_pairs_meet_wcag_aa_contrast(self):
        t = tokens()
        pairs = [
            ("ink on ivory", t["ink"], t["ivory"]),
            ("navy on ivory", t["navy"], t["ivory"]),
            ("muted on ivory", t["muted"], t["ivory"]),
            ("gold-ink on ivory", t["gold-ink"], t["ivory"]),
            ("navy on white", t["navy"], t["paper"]),
            ("white on navy", "#ffffff", t["navy"]),
            ("gold on navy", t["gold"], t["navy"]),
            ("navy on gold (gold button)", t["navy"], t["gold"]),
            ("danger on white", t["danger"], t["paper"]),
        ]
        for label, fg, bg in pairs:
            with self.subTest(pair=label):
                self.assertGreaterEqual(ratio(fg, bg), 4.5, f"{label}: {ratio(fg, bg):.2f}")

    def test_every_class_used_in_templates_is_styled(self):
        styles = css("site.css") + css("dashboard.css")
        hooks = {"js-add"}  # JavaScript hooks that are intentionally unstyled
        missing = {
            token: page
            for token, page in template_classes().items()
            if token not in hooks and not re.search(r"\." + re.escape(token) + r"(?![A-Za-z0-9_-])", styles)
        }
        self.assertEqual(missing, {}, f"classes without styles: {missing}")

    def test_motion_respects_reduced_motion_and_ribbon_exists(self):
        site = css("site.css")
        self.assertIn("prefers-reduced-motion:reduce", site)
        for selector in (".hero", ".marquee", ".btn-gold", ".brand-logo", ".site-footer"):
            self.assertIn(selector, site)

    def test_dashboard_pages_still_render(self):
        self.assertContains(self.client.get("/owner/login/"), "Owner login")