"""Build contact sheets for visual review of the Edge smoke screenshots."""

from pathlib import Path
from PIL import Image, ImageDraw

OUTPUT = Path(__file__).resolve().parents[1] / "reports/language-productization"
ROUTES = ["overview", "progress", "benchmarks", "study-session", "curriculum", "inbox",
          "reader", "vocabulary", "phrasebook", "reviews", "cloze", "generate", "listening",
          "grammar", "statistics", "goals", "settings", "topics",
          "reader-text-000000000000000000000000000186a1", "reader-hover",
          "reader-word-panel", "reader-full-detail", "dashboard-widget"]

for size in ("2048x1010", "1440x1000", "430x900", "390x844"):
    width, height = 276, 220
    sheet = Image.new("RGB", (width * 5, height * 5), "#111111")
    draw = ImageDraw.Draw(sheet)
    for index, route in enumerate(ROUTES):
        source = OUTPUT / f"{size}-{route}.png"
        if not source.exists():
            continue
        with Image.open(source) as screenshot:
            screenshot.thumbnail((width - 12, height - 30))
            x, y = index % 5 * width, index // 5 * height
            sheet.paste(screenshot, (x + 6, y + 25))
            draw.text((x + 6, y + 6), route[:33], fill="white")
    sheet.save(OUTPUT / f"contact-{size}.png")
