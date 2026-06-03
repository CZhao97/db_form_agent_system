from __future__ import annotations

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor

OUT = Path(__file__).resolve().parent
TEMPLATE = OUT / "Template (1).pptx"
PPTX = OUT / "dbcurator_agentic_science_demo_template.pptx"
FIGS = OUT / "manuscript_figures"

FIGURE_ASSETS = {
    "workflow": FIGS / "figure1_workflow.png",
    "fixed_cohort": FIGS / "figure2_fixed_cohort.png",
    "benchmark": FIGS / "figure3_benchmark_scale.png",
    "rubric": FIGS / "figure4_predicate_gates.png",
    "iterative": FIGS / "figure5_iterative_utility.png",
}

for name, path in FIGURE_ASSETS.items():
    if not path.exists():
        raise FileNotFoundError(f"Missing manuscript figure asset for {name}: {path}")

prs = Presentation(TEMPLATE)


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
PURPLE = RGBColor(120, 110, 165)
GRAY = RGBColor(88, 98, 108)
DARK_GRAY = RGBColor(45, 52, 60)
LIGHT_GRAY = RGBColor(241, 244, 247)
WHITE = RGBColor(255, 255, 255)
BLACK = RGBColor(0, 0, 0)
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
        set_text(t.text_frame, title, size=29, color=BLACK, bold=False)
    except Exception:
        add_textbox(slide, 0.65, 0.52, 10.8, 0.65, title, size=29)
    if subtitle:
        add_textbox(slide, 0.75, 1.22, 10.8, 0.45, subtitle, size=14.5, color=GRAY)


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


def pill(slide, x, y, w, text, color, text_color=WHITE, size=11.3):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(0.36))
    shp.fill.solid()
    shp.fill.fore_color.rgb = color
    shp.line.color.rgb = color
    set_text(shp.text_frame, text, size=size, color=text_color, bold=True, align=PP_ALIGN.CENTER)
    return shp


def metric_card(slide, x, y, w, h, number, label, color, note=None):
    rect(slide, x, y, w, h, WHITE, RGBColor(222, 228, 233))
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(0.07))
    bar.fill.solid(); bar.fill.fore_color.rgb = color; bar.line.color.rgb = color
    add_textbox(slide, x + 0.22, y + 0.18, w - 0.44, 0.42, number, size=25, color=color, bold=True)
    add_textbox(slide, x + 0.22, y + 0.76, w - 0.44, 0.40, label, size=12.8, color=BLACK, bold=True)
    if note:
        add_textbox(slide, x + 0.22, y + 1.16, w - 0.44, h - 1.23, note, size=9.2, color=GRAY, line_spacing=0.92)


def bullet_box(slide, x, y, w, h, title, bullets, color=BLUE):
    rect(slide, x, y, w, h, WHITE, RGBColor(222, 228, 233))
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(0.07))
    bar.fill.solid(); bar.fill.fore_color.rgb = color; bar.line.color.rgb = color
    add_textbox(slide, x + 0.22, y + 0.22, w - 0.44, 0.32, title, size=14.5, color=BLACK, bold=True)
    tf = slide.shapes.add_textbox(Inches(x + 0.25), Inches(y + 0.72), Inches(w - 0.48), Inches(h - 0.82)).text_frame
    tf.clear(); tf.word_wrap = True
    for i, b in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = b
        p.font.name = FONT
        p.font.size = Pt(11.2)
        p.font.color.rgb = DARK_GRAY
        p.space_after = Pt(4)
        p.line_spacing = 0.95


def quote_box(slide, x, y, w, h, text, color=TEAL):
    rect(slide, x, y, w, h, LIGHT_GRAY, RGBColor(224, 230, 235))
    add_textbox(slide, x + 0.22, y + 0.15, w - 0.44, h - 0.16, text, size=12.0, color=color, bold=True, line_spacing=0.92)


def add_picture_fit(slide, image_path: Path, x, y, w, h, border=True):
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


# Slide 1.
slide = prs.slides.add_slide(prs.slide_layouts[0])
set_text(slide.shapes.title.text_frame, "DB-Curator", size=44, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
set_text(slide.placeholders[1].text_frame, "Agentic database construction for scientific evidence", size=22, color=BLACK, bold=True, align=PP_ALIGN.CENTER)
add_textbox(slide, 2.55, 5.40, 8.2, 0.54, "From open-ended scientific questions to verified, auditable database rows", size=18, color=TEAL, bold=True, align=PP_ALIGN.CENTER)
add_textbox(slide, 3.3, 6.10, 6.9, 0.35, "Chen Zhao, Botao Liu, Xiaoxiao Li, Tao Huan", size=14, color=BLACK, align=PP_ALIGN.CENTER)

# Slide 2: motivation and application target.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "Application target: build a database, not an answer")
bullet_box(slide, 0.82, 1.75, 3.75, 4.25, "Scientific pain point", [
    "Specialized databases are still built by slow expert literature curation.",
    "Relevant evidence is scattered across papers, tables, metadata and compound mentions.",
    "A plausible chemical name is not enough; release requires identity, scope and paper provenance."
], BLUE)
bullet_box(slide, 4.78, 1.75, 3.75, 4.25, "Agentic framing", [
    "The literature set is dynamic, not pre-curated: searches change as candidates and evidence gaps appear.",
    "Each candidate is treated as an evidence contract with mandatory and exclusion predicates.",
    "The loop stops only when the row is supported, rejected, or evidence-limited."
], TEAL)
bullet_box(slide, 8.75, 1.75, 3.55, 4.25, "What users get", [
    "Curated compound rows with identifiers and topic labels.",
    "Cited papers plus quote or local-context support.",
    "Human-reviewable failure states for borderline cases."
], GREEN)
quote_box(slide, 0.95, 6.28, 10.85, 0.72, "ML takeaway: the agent is valuable because it controls retrieval, state tracking and stopping decisions, not because it writes fluent summaries.")
add_footer(slide, 2)

# Slide 3: workflow with manuscript figure.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "How DB-Curator turns intent into verified rows")
add_picture_fit(slide, FIGURE_ASSETS["workflow"], 0.85, 1.55, 7.35, 4.95)
bullet_box(slide, 8.55, 1.72, 3.45, 1.25, "1. Dynamic literature", ["Searches are seeded by the user definition, candidate identities and critique-discovered gaps."], BLUE)
bullet_box(slide, 8.55, 3.12, 3.45, 1.25, "2. Candidate grounding", ["Chemical mentions are normalized, filtered and converted into compound-level verification questions."], GOLD)
bullet_box(slide, 8.55, 4.52, 3.45, 1.34, "3. Predicate verification", ["Researcher proposes evidence; Critique audits whether each rubric predicate is actually supported."], TEAL)
pill(slide, 8.70, 6.36, 1.35, "supported", GREEN)
pill(slide, 10.20, 6.36, 1.40, "unresolved", GOLD)
pill(slide, 8.70, 6.82, 1.55, "exclusion", RED)
pill(slide, 10.45, 6.82, 1.35, "exhausted", RGBColor(170, 181, 190))
add_footer(slide, 3)

# Slide 4: application results.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "Application result: known recovery plus literature-buried additions")
metric_card(slide, 0.82, 1.75, 2.65, 1.55, "246/250", "release-accepted rows", BLUE, "Fixed-cohort audit over five topics.")
metric_card(slide, 3.75, 1.75, 2.65, 1.55, "178", "benchmark overlaps", TEAL, "Known entries recovered automatically.")
metric_card(slide, 6.68, 1.75, 2.65, 1.55, "68", "new valid entries", GREEN, "Absent from benchmark but accepted by human experts.")
metric_card(slide, 9.60, 1.75, 2.20, 1.55, "4", "errors", RED, "Out-of-scope or false rows.")
add_picture_fit(slide, FIGURE_ASSETS["fixed_cohort"], 0.95, 3.65, 6.65, 2.80)
bullet_box(slide, 8.02, 3.75, 3.95, 2.40, "Why this matters scientifically", [
    "Benchmarks are incomplete for open-ended curation.",
    "A useful system should recover known compounds and surface evidence-backed additions.",
    "DB-Curator shifts human work from full literature search to focused audit of non-overlap rows and evidence."
], GREEN)
add_footer(slide, 4)

# Slide 5: verification logic and citation audit.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "How we verify the output")
bullet_box(slide, 0.82, 1.62, 3.55, 4.72, "Paper-level audit", [
    "Resolve the cited item to a real primary paper using DOI, PMID, title or recovered metadata.",
    "Search recovered paper text for the quoted span or equivalent local context.",
    "Exclude compound-database lookup pages from primary-paper citation counts."
], BLUE)
bullet_box(slide, 4.58, 1.62, 3.55, 4.72, "Predicate-level audit", [
    "Required predicates must be directly supported, not only semantically nearby.",
    "Exclusion contexts such as reagents, solvents or out-of-scope matrices block release.",
    "Unresolved predicates trigger follow-up retrieval or remain evidence-limited."
], TEAL)
metric_card(slide, 8.55, 1.62, 3.10, 1.25, "2,166/2,166", "fixed-cohort support", GREEN)
metric_card(slide, 8.55, 3.10, 3.10, 1.25, "7,430/7,453", "benchmark-scale support", BLUE)
metric_card(slide, 8.55, 4.58, 3.10, 1.25, "11/257", "zero-shot direct generation", RED)
quote_box(slide, 0.95, 6.34, 10.85, 0.66, "Core contrast: baseline models can name plausible compounds, but DB-Curator produces rows whose papers and evidence spans can be audited.")
add_footer(slide, 5)

# Slide 6: scale and agentic loop.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "What ML experts should take away")
metric_card(slide, 0.82, 1.58, 2.62, 1.45, "1,887", "candidate rows", BLUE)
metric_card(slide, 3.72, 1.58, 2.62, 1.45, "977", "Confirmed labels", GREEN)
metric_card(slide, 6.62, 1.58, 2.62, 1.45, "49", "rescued by critique", TEAL)
metric_card(slide, 9.52, 1.58, 2.45, 1.45, "5", "tightened", RED)
add_picture_fit(slide, FIGURE_ASSETS["benchmark"], 0.85, 3.35, 5.65, 2.85)
add_picture_fit(slide, FIGURE_ASSETS["iterative"], 6.82, 3.35, 5.25, 2.85)
quote_box(slide, 0.95, 6.42, 10.75, 0.72, "General lesson: agentic systems are most useful in science when they turn open-ended requests into inspectable states, evidence contracts and auditable artifacts.")
add_footer(slide, 6)

prs.save(PPTX)
print(PPTX)
