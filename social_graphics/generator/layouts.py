"""Fixed 1080 × 1080 layouts with measured text and explicit overflow errors."""

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .icons import icon_image
from .models import CouncilSummary, InputError, WasteChange
from .theme import (BACKGROUND, BLUE, DIVIDER, FONT_PATH, LOGO_PATH, MARGIN,
                    MUTED, PALE_BLUE, SIZE, TEXT, TYPE)


@lru_cache(maxsize=64)
def font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    result = ImageFont.truetype(str(FONT_PATH), size)
    result.set_variation_by_axes([14, weight])
    return result


def width(value: str, face: ImageFont.FreeTypeFont) -> float:
    return face.getlength(value)


def single_line(value: str, face: ImageFont.FreeTypeFont, max_width: int, field: str) -> None:
    if width(value, face) > max_width:
        raise InputError(f"{field}: text se nevejde na jeden řádek ({max_width} px). Zkraťte ho.")


def wrap(value: str, face: ImageFont.FreeTypeFont, max_width: int, max_lines: int, field: str) -> list[str]:
    lines: list[str] = []
    for paragraph in value.split("\n"):
        line = ""
        for word in paragraph.split():
            if width(word, face) > max_width:
                raise InputError(f"{field}: slovo '{word}' je širší než dostupný prostor.")
            candidate = f"{line} {word}" if line else word
            if width(candidate, face) <= max_width:
                line = candidate
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
    if len(lines) > max_lines:
        raise InputError(f"{field}: text se vejde nejvýše na {max_lines} řádky; nyní potřebuje {len(lines)}. Zkraťte ho.")
    return lines


def draw_lines(draw: ImageDraw.ImageDraw, lines: list[str], x: int, y: int,
               face: ImageFont.FreeTypeFont, color: str, step: int) -> None:
    for index, line in enumerate(lines):
        draw.text((x, y + index * step), line, font=face, fill=color, anchor="lt")


def add_logo(canvas: Image.Image) -> None:
    try:
        with Image.open(LOGO_PATH) as source:
            logo = source.convert("RGBA")
    except OSError as exc:
        raise InputError(f"Chybí původní PNG logo: {LOGO_PATH}") from exc
    logo.thumbnail((260, 58), Image.Resampling.LANCZOS)
    canvas.paste(logo, (SIZE - MARGIN - logo.width, 978), logo)


def waste_change(data: WasteChange) -> Image.Image:
    canvas = Image.new("RGB", (SIZE, SIZE), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    overline = font(TYPE["overline"], 650)
    single_line(data.place.upper(), overline, SIZE - 2 * MARGIN, "place")
    draw.text((MARGIN, 89), data.place.upper(), font=overline, fill=BLUE, anchor="lt")

    available = SIZE - 2 * MARGIN
    count = len(data.title_lines)
    size = min(TYPE["hero"], int(447 / (count * 1.13)))
    while size >= 58:
        face = font(size, 780)
        if all(width(line, face) <= available for line in data.title_lines):
            break
        size -= 1
    else:
        raise InputError("title_lines: alespoň jeden řádek je příliš dlouhý. Rozdělte nebo zkraťte nadpis.")
    step = round(size * 1.13)
    top = 207 + max(0, 4 - count) * 34
    if top + count * step > 686:
        raise InputError("title_lines: nadpis je příliš vysoký pro tento layout.")
    for index, line in enumerate(data.title_lines, start=1):
        draw.text((MARGIN, top + (index - 1) * step), line,
                  font=face, fill=BLUE if index in data.accent_lines else TEXT, anchor="lt")

    draw.line((MARGIN, 729, SIZE - MARGIN, 729), fill=DIVIDER, width=2)
    body_face = font(29, 400)
    body_lines = wrap(data.body, body_face, available, 3, "body")
    draw_lines(draw, body_lines, MARGIN, 773, body_face, TEXT, 40)
    add_logo(canvas)
    return canvas


def council_summary(data: CouncilSummary) -> Image.Image:
    canvas = Image.new("RGB", (SIZE, SIZE), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    available = SIZE - 2 * MARGIN

    if data.top_label:
        face = font(TYPE["overline"], 650)
        single_line(data.top_label.upper(), face, available, "branding.top_label")
        draw.text((MARGIN, 55), data.top_label.upper(), font=face, fill=MUTED, anchor="lt")

    session = data.meeting.session_label
    first, separator, rest = session.partition(" ")
    session_face = font(78, 780)
    single_line(session, session_face, available, "meeting.session_label")
    # A shared baseline keeps the number and the word aligned despite their
    # different glyph heights (digits have no ascenders or accents).
    session_baseline = 151
    draw.text((MARGIN, session_baseline), first, font=session_face, fill=BLUE, anchor="ls")
    if separator:
        draw.text((MARGIN + round(width(first + " ", session_face)), session_baseline), rest,
                  font=session_face, fill=TEXT, anchor="ls")

    body_face = font(34, 600)
    single_line(data.meeting.body, body_face, available, "meeting.body")
    draw.text((MARGIN, 179), data.meeting.body, font=body_face, fill=TEXT, anchor="lt")
    subtitle_face = font(31, 650)
    single_line(data.meeting.subtitle, subtitle_face, available, "meeting.subtitle")
    draw.text((MARGIN, 237), data.meeting.subtitle, font=subtitle_face, fill=BLUE, anchor="lt")

    start = 305 if len(data.items) == 4 else 302
    row_height = 143 if len(data.items) == 4 else 178
    text_x = 188
    text_width = SIZE - MARGIN - text_x
    title_face = font(TYPE["section_title"], 720)
    detail_face = font(TYPE["body"], 400)
    for index, item in enumerate(data.items):
        y = start + index * row_height
        title = wrap(item.title, title_face, text_width, 2, f"items[{index}].title")
        detail = wrap(item.text, detail_face, text_width, 2, f"items[{index}].text")
        detail_offset = len(title) * 36 + 3
        text_bounds = [draw.textbbox((0, line_index * 36), line, font=title_face, anchor="lt")
                       for line_index, line in enumerate(title)]
        text_bounds += [draw.textbbox((0, detail_offset + line_index * 31), line,
                                     font=detail_face, anchor="lt")
                        for line_index, line in enumerate(detail)]
        text_top = min(box[1] for box in text_bounds)
        text_bottom = max(box[3] for box in text_bounds)
        text_height = text_bottom - text_top
        if text_height > row_height - 12:
            raise InputError(f"items[{index}]: nadpis a vysvětlení se společně nevejdou. Zkraťte text.")
        center_y = y + row_height / 2
        text_y = round(center_y - text_height / 2 - text_top)
        circle_top = round(center_y - 39)
        draw.ellipse((MARGIN, circle_top, MARGIN + 78, circle_top + 78), fill=PALE_BLUE)
        icon = icon_image(item.icon, 43)
        canvas.paste(icon, (MARGIN + 18, circle_top + 18), icon)
        draw_lines(draw, title, text_x, text_y, title_face, TEXT, 36)
        draw_lines(draw, detail, text_x, text_y + detail_offset,
                   detail_face, MUTED, 31)
    footer_face = font(TYPE["footer"], 400)
    footer_lines = wrap(data.meeting.footer, footer_face, available - 38, 2, "meeting.footer")
    footer_top, footer_bottom = 895, 953
    draw.rounded_rectangle((MARGIN, footer_top, SIZE - MARGIN, footer_bottom), radius=10, fill=PALE_BLUE)
    line_step = 26
    bounds = [draw.textbbox((0, index * line_step), line, font=footer_face, anchor="lt")
              for index, line in enumerate(footer_lines)]
    content_top = min(box[1] for box in bounds)
    content_bottom = max(box[3] for box in bounds)
    footer_y = round((footer_top + footer_bottom - (content_bottom - content_top)) / 2 - content_top)
    draw_lines(draw, footer_lines, MARGIN + 19, footer_y, footer_face, TEXT, line_step)
    add_logo(canvas)
    return canvas
