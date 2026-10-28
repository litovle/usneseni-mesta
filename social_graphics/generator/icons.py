"""Local Lucide SVG assets, rasterized with a single stroke style."""

from io import BytesIO
from xml.etree import ElementTree as ET

import cairosvg
from PIL import Image

from .models import InputError
from .theme import ASSETS, BLUE

ICON_FILES = {
    "construction": "hard-hat.svg",
    "coins": "coins.svg",
    "water": "droplets.svg",
    "waves": "droplets.svg",
    "road": "route.svg",
    "school": "school.svg",
    "bridge": "bridge.svg",
    "sport": "trophy.svg",
    "property": "land-plot.svg",
    "housing": "house.svg",
    "energy": "zap.svg",
    "culture": "palette.svg",
    "committee": "users-round.svg",
    "social": "heart-handshake.svg",
    "security": "shield-check.svg",
    "waste": "recycle.svg",
    "equipment": "wrench.svg",
    "environment": "trees.svg",
    "strategy": "compass.svg",
    "business": "store.svg",
    "contract": "handshake.svg",
}


def icon_image(name: str, size: int) -> Image.Image:
    filename = ICON_FILES.get(name)
    if filename is None:
        raise InputError(f"Neznámá ikona '{name}'. Dostupné: {', '.join(ICON_FILES)}.")
    root = ET.parse(ASSETS / "icons" / filename).getroot()
    root.set("stroke", BLUE)
    root.set("stroke-width", "1.9")
    payload = ET.tostring(root, encoding="utf-8")
    png = cairosvg.svg2png(bytestring=payload, output_width=size * 3, output_height=size * 3)
    return Image.open(BytesIO(png)).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
