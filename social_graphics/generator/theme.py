from pathlib import Path

SIZE = 1080
MARGIN = 76
BACKGROUND = "#FFFFFF"
TEXT = "#101B2C"
MUTED = "#526176"
BLUE = "#1156B4"
PALE_BLUE = "#EAF3FF"
DIVIDER = "#DCE7F2"

ASSETS = Path(__file__).resolve().parents[1] / "assets"
FONT_PATH = ASSETS / "fonts" / "Inter.ttf"
LOGO_PATH = ASSETS / "litovle_logo.png"

# Size in pixels; all layouts use this shared scale.
TYPE = {
    "overline": 23,
    "hero": 100,
    "hero_accent": 100,
    "section_title": 30,
    "body": 24,
    "footer": 24,
}
