from __future__ import annotations

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor

OUT = Path(__file__).resolve().parent
REPO = OUT.parent
TEMPLATE = OUT / "Template (1).pptx"
PPTX = OUT / "dbcurator_agentic_science_demo_template.pptx"
PDF = OUT / "dbcurator_agentic_science_demo_template.pdf"
FIGS = OUT / "manuscript_figures"

# These are copied from the manuscript figure assets so the demo deck can be
# regenerated from a clean public-release clone.
FIGURE_ASSETS = {
    "workflow": FIGS / "figure1_workflow.png",
    "fixed_cohort": FIGS / "figure2_fixed_cohort.png",
    "benchmark": FIGS / "figure3_benchmark_scale.png",
    "rubric": FIGS / "figure4_predicate_gates.png",
    "iterative": FIGS / "figure5_iterative_utility.png",
    "efficiency": FIGS / "figure6_operational_efficiency.png",
}

for name, path in FIGURE_ASSETS.items():
    if not path.exists():
        raise FileNotFoundError(f"Missing manuscript figure asset for {name}: {path}")

prs = Presentation(TEMPLATE)

# Remove example slides while preserving the template master/layouts.
def delete_slide(prs, index: int) -> None:
    xml_slides = prs.slides._sldIdLst
    slides = list(xml_slides)
    xml_slides.remove(slides[index])

while len(prs.slides):
    delete_slide(prs, 0)

NAVY = RGBColor(24, 54, 96)
TEAL = RGBColor(38, 112, 94)
BLUE = RGBColor(70, 130, 180)
GREEN = RGBColor(108, 171, 128)
GOLD = RGBColor(226, 180, 87)
RED = RGBColor(198, 96, 96)
GRAY = RGBColor(88, 98, 108)
LIGHT_GRAY = RGBColor(241, 244, 247)
BLACK = RGBColor(0, 0, 0)
WHITE = RGBColor(255, 255, 255)
FONT = "Arial"


def set_text(tf, text, size=24, color=BLACK, bold=False, align=None, line_spacing=1.0):
    tf.clear()
    p = tf.paragraphs[0]
    p.text = text
    p.font.name = FONT
    p.font.size = Pt(size)
    p.font.bold = bold
    p.font.color.rgb = color
    if align is not None:
        p.alignment = align
    p.line_spacing = line_spacing
    return p


def add_textbox(slide, x, y, w, h, text, size=20, color=BLACK, bold=False, align=None, line_spacing=1.0):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    box.text_frame.word_wrap = True
    set_text(box.text_frame, text, size=size, color=color, bold=bold, align=align, line_spacing=line_spacing)
    return box


def add_title(slide, title, subtitle=None):
    try:
        t = slide.shapes.title
        set_text(t.text_frame, title, size=28, color=BLACK, bold=False)
    except Exception:
        add_textbox(slide, 0.65, 0.52, 10.8, 0.65, title, size=28)
    if subtitle:
        add_textbox(slide, 0.75, 1.22, 10.8, 0.45, subtitle, size=15, color=GRAY)


def add_footer(slide, n):
    add_textbox(slide, 11.25, 7.22, 1.55, 0.25, "Trusted and Efficient AI Group", size=9.5, color=RGBColor(130, 130, 130), align=PP_ALIGN.RIGHT)
    add_textbox(slide, 12.85, 7.22, 0.25, 0.25, str(n), size=12, color=BLACK, align=PP_ALIGN.RIGHT)


def rect(slide, x, y, w, h, fill=WHITE, line=RGBColor(220, 220, 220), radius=True):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = line
    shape.line.width = Pt(1)
    return shape


def pill(slide, x, y, w, text, color, text_color=WHITE):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(0.34))
    shp.fill.solid()
    shp.fill.fore_color.rgb = color
    shp.line.color.rgb = color
    set_text(shp.text_frame, text, size=11.5, color=text_color, bold=True, align=PP_ALIGN.CENTER)
    return shp


def add_picture_fit(slide, image_path: Path, x, y, w, h, border=True):
    """Place image with aspect ratio preserved inside the requested box."""
    from PIL import Image

    with Image.open(image_path) as im:
        iw, ih = im.size
    target_ratio = w / h
    image_ratio = iw / ih
    if image_ratio >= target_ratio:
        final_w = w
        final_h = w / image_ratio
    else:
        final_h = h
        final_w = h * image_ratio
    px = x + (w - final_w) / 2
    py = y + (h - final_h) / 2
    if border:
        rect(slide, px - 0.04, py - 0.04, final_w + 0.08, final_h + 0.08, WHITE, RGBColor(222, 228, 233), radius=False)
    return slide.shapes.add_picture(str(image_path), Inches(px), Inches(py), width=Inches(final_w), height=Inches(final_h))


def callout(slide, text, color=TEAL):
    rect(slide, 0.78, 6.52, 10.7, 0.58, LIGHT_GRAY, RGBColor(224, 230, 235))
    add_textbox(slide, 1.02, 6.67, 10.2, 0.25, text, size=13.5, color=color, bold=True)


# Slide 1: title.
slide = prs.slides.add_slide(prs.slide_layouts[0])
set_text(slide.shapes.title.text_frame, "DB-Curator", size=44, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
set_text(slide.placeholders[1].text_frame, "Agentic scientific database construction with auditable evidence", size=22, color=BLACK, bold=True, align=PP_ALIGN.CENTER)
add_textbox(slide, 2.95, 5.50, 7.5, 0.45, "Dynamic literature construction + predicate-state verification", size=18, color=TEAL, bold=True, align=PP_ALIGN.CENTER)
add_textbox(slide, 3.3, 6.10, 6.9, 0.35, "Chen Zhao, Botao Liu, Xiaoxiao Li, Tao Huan", size=14, color=BLACK, align=PP_ALIGN.CENTER)

# Slide 2: workflow from manuscript Figure 1.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "Agents build evidence, not only answers")
add_picture_fit(slide, FIGURE_ASSETS["workflow"], 0.82, 1.72, 11.62, 4.95)
callout(slide, "Takeaway: the agent controls search, state and stopping criteria for each database entry.")
add_footer(slide, 2)

# Slide 3: fixed-cohort release and evidence grounding from manuscript Figure 2.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "Release-ready rows need evidence trails")
add_picture_fit(slide, FIGURE_ASSETS["fixed_cohort"], 0.70, 1.62, 12.05, 4.86)
pill(slide, 0.95, 6.55, 2.25, "246/250 accepted", BLUE)
pill(slide, 3.35, 6.55, 2.55, "68 new valid entries", GREEN)
pill(slide, 6.05, 6.55, 2.65, "2,166/2,166 supported", TEAL)
pill(slide, 8.85, 6.55, 2.75, "baseline: 11/257 refs", RED)
add_footer(slide, 3)

# Slide 4: benchmark-scale validation from manuscript Figure 3.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "Benchmark scale across five domains")
add_picture_fit(slide, FIGURE_ASSETS["benchmark"], 0.70, 1.58, 12.05, 5.00)
add_footer(slide, 4)

# Slide 5: rubric / predicate gates from manuscript Figure 4.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "Verification is predicate-specific")
add_picture_fit(slide, FIGURE_ASSETS["rubric"], 0.58, 1.50, 12.25, 5.15)
add_footer(slide, 5)

# Slide 6: iterative utility from manuscript Figure 5.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "Why the agentic loop matters")
add_picture_fit(slide, FIGURE_ASSETS["iterative"], 0.78, 1.45, 11.50, 5.25)
pill(slide, 1.15, 6.67, 2.10, "49 rescued", GREEN)
pill(slide, 3.55, 6.67, 2.15, "5 tightened", RED)
pill(slide, 5.95, 6.67, 2.45, "hybrid adds evidence", BLUE)
pill(slide, 8.70, 6.67, 2.65, "changed claims need review", TEAL)
add_footer(slide, 6)

prs.save(PPTX)
print(PPTX)
