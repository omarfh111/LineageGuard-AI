"""Render polished, 3:2 Devpost gallery cards from verified local captures.

The source images remain untouched. Run this script after refreshing a source
capture to recreate cards 10–14 and the lightweight animated feature tour.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "submission" / "media"
WIDTH, HEIGHT = 1500, 1000
HEADER_HEIGHT = 155
FONT_REGULAR = "C:/Windows/Fonts/segoeui.ttf"
FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"


def fit_cover(image: Image.Image, width: int, height: int) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), (width, height), Image.Resampling.LANCZOS)


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *size), radius=radius, fill=255)
    return mask


def render_card(source: str, output: str, eyebrow: str, title: str, subtitle: str, accent: str) -> None:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "#081225")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, WIDTH, HEADER_HEIGHT), fill="#0C1933")
    draw.rectangle((0, HEADER_HEIGHT - 5, WIDTH, HEADER_HEIGHT), fill=accent)
    draw.text((52, 26), eyebrow.upper(), font=ImageFont.truetype(FONT_BOLD, 20), fill=accent)
    draw.text((52, 54), title, font=ImageFont.truetype(FONT_BOLD, 43), fill="#F7FAFF")
    draw.text((52, 108), subtitle, font=ImageFont.truetype(FONT_REGULAR, 23), fill="#B9C7DF")

    frame = fit_cover(Image.open(MEDIA / source), WIDTH - 80, HEIGHT - HEADER_HEIGHT - 60)
    x, y = 40, HEADER_HEIGHT + 30
    canvas.paste(frame, (x, y), rounded_mask(frame.size, 22))
    canvas.save(MEDIA / output, quality=92, optimize=True)


def render_gif() -> None:
    frames = []
    steps = [
        ("08-home-overview.jpg", "LineageGuard AI", "Evidence-first DataHub agents"),
        ("01-catalog-3d-ready.jpg", "Live 3D catalog", "Explore metadata and lineage"),
        ("02-agentic-rag-verified.jpg", "Verified assistant", "RAG context + live MCP proof"),
        ("05-independent-judge-disagreement.jpg", "Independent review", "Two judges can disagree safely"),
        ("04-impact-analysis-read-only.jpg", "Human-in-the-loop", "Only an approved analysis document can be written"),
    ]
    for source, title, subtitle in steps:
        image = Image.new("RGB", (1200, 800), "#081225")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 1200, 120), fill="#0C1933")
        draw.text((38, 20), "LINEAGEGUARD AI", font=ImageFont.truetype(FONT_BOLD, 18), fill="#7F93FF")
        draw.text((38, 44), title, font=ImageFont.truetype(FONT_BOLD, 34), fill="#F7FAFF")
        draw.text((38, 85), subtitle, font=ImageFont.truetype(FONT_REGULAR, 20), fill="#B9C7DF")
        frame = fit_cover(Image.open(MEDIA / source), 1120, 620)
        image.paste(frame, (40, 145), rounded_mask(frame.size, 18))
        frames.append(image)
    frames[0].save(
        MEDIA / "15-lineageguard-feature-tour.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[2400] * len(frames),
        loop=0,
        optimize=True,
        disposal=2,
    )


def main() -> None:
    render_card(
        "01-catalog-3d-ready.jpg",
        "10-cartography-explorer-card.jpg",
        "Catalog exploration",
        "See the whole data landscape",
        "A shared 3D cache keeps the catalog and lineage responsive.",
        "#63D8FF",
    )
    render_card(
        "02-agentic-rag-verified.jpg",
        "11-verified-assistant-card.jpg",
        "Agentic RAG + MCP",
        "Answers grounded in live evidence",
        "Qdrant retrieval is rechecked against DataHub before facts are shown.",
        "#72F2C0",
    )
    render_card(
        "03-independent-judge-states.jpg",
        "12-independent-review-card.jpg",
        "Independent judges",
        "Review outcomes are visible",
        "Pass, disagreement, and rejection are explicit — never hidden.",
        "#A28BFF",
    )
    render_card(
        "04-impact-analysis-read-only.jpg",
        "13-impact-analysis-card.jpg",
        "Read-only analysis",
        "Model the impact before the change",
        "Impact assessment starts with DataHub lineage, not a mutation.",
        "#FFD166",
    )
    render_card(
        "05-independent-judge-disagreement.jpg",
        "14-governed-writeback-card.jpg",
        "Governed write-back",
        "Human approval remains in control",
        "Only a reviewed analysis document may enter the controlled HITL path.",
        "#FF7D9C",
    )
    render_gif()


if __name__ == "__main__":
    main()
