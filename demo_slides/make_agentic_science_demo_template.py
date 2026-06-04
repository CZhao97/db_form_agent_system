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


def add_small_title(slide, title):
    try:
        t = slide.shapes.title
        set_text(t.text_frame, title, size=25, color=BLACK, bold=False)
    except Exception:
        add_textbox(slide, 0.65, 0.52, 10.8, 0.65, title, size=25)


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
        add_textbox(slide, x + 0.22, y + 1.15, w - 0.44, h - 1.22, note, size=8.7, color=GRAY, line_spacing=0.9)


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
        p.font.size = Pt(10.8)
        p.font.color.rgb = DARK_GRAY
        p.space_after = Pt(4)
        p.line_spacing = 0.95


def quote_box(slide, x, y, w, h, text, color=TEAL):
    rect(slide, x, y, w, h, LIGHT_GRAY, RGBColor(224, 230, 235))
    add_textbox(slide, x + 0.22, y + 0.15, w - 0.44, h - 0.16, text, size=12.0, color=color, bold=True, line_spacing=0.92)


def figure_note(slide, x, y, w, text, color=GRAY):
    add_textbox(slide, x, y, w, 0.28, text, size=10.4, color=color, bold=True)


def result_panel(slide, x, y, w, h, title, rows, color):
    rect(slide, x, y, w, h, WHITE, RGBColor(222, 228, 233))
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(0.07))
    bar.fill.solid(); bar.fill.fore_color.rgb = color; bar.line.color.rgb = color
    add_textbox(slide, x + 0.22, y + 0.20, w - 0.44, 0.35, title, size=14.2, color=BLACK, bold=True)
    yy = y + 0.78
    for number, label in rows:
        num_size = 16.4 if len(number) > 8 else 19.5
        num_w = 1.92 if len(number) > 8 else 1.42
        label_x = 2.12 if len(number) > 8 else 1.58
        add_textbox(slide, x + 0.22, yy, num_w, 0.35, number, size=num_size, color=color, bold=True)
        add_textbox(slide, x + label_x, yy + 0.03, w - label_x - 0.24, 0.32, label, size=10.4, color=DARK_GRAY)
        yy += 0.58


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
add_textbox(slide, 2.25, 5.35, 8.8, 0.62, "A tool that searches literature, proposes candidates, and verifies each database row with auditable evidence", size=17.2, color=TEAL, bold=True, align=PP_ALIGN.CENTER)
add_textbox(slide, 3.3, 6.10, 6.9, 0.35, "Chen Zhao, Botao Liu, Xiaoxiao Li, Tao Huan", size=14, color=BLACK, align=PP_ALIGN.CENTER)

# Content slide 1: background.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "Background: scientific databases are reusable knowledge infrastructure")
add_textbox(slide, 0.95, 1.35, 11.0, 0.55, "Scientific databases turn scattered papers into searchable, comparable and reusable knowledge.", size=18.5, color=NAVY, bold=True)
bullet_box(slide, 0.82, 2.12, 2.70, 3.45, "1. Define scope", [
    "Experts decide what should count as an entry.",
    "Borderline cases need explicit inclusion and exclusion rules."
], BLUE)
bullet_box(slide, 3.72, 2.12, 2.70, 3.45, "2. Search papers", [
    "Relevant evidence is scattered across many articles.",
    "The literature set changes as the topic becomes clearer."
], TEAL)
bullet_box(slide, 6.62, 2.12, 2.70, 3.45, "3. Interpret context", [
    "A name mention is not enough.",
    "The row needs identity, matrix, mechanism and evidence context."
], GOLD)
bullet_box(slide, 9.52, 2.12, 2.70, 3.45, "4. Record evidence", [
    "Accepted entries need citations and provenance.",
    "Future users must be able to inspect why the row exists."
], GREEN)
quote_box(slide, 1.05, 6.20, 10.70, 0.78, "Takeaway: scientific curation is slow because every accepted row needs identity, scope and evidence provenance.")
add_footer(slide, 1)

# Content slide 2: problem definition.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "Problem: extraction and RAG do not decide database membership")
add_textbox(slide, 0.95, 1.28, 10.9, 0.50, "A chemical mention can be a target compound, reagent, precursor, solvent, contaminant or contextual comparison.", size=17.0, color=NAVY, bold=True)
bullet_box(slide, 0.95, 2.05, 5.10, 3.95, "Standard extraction / RAG", [
    "Finds entity mentions or retrieves passages.",
    "Generates an answer from a context window.",
    "Citations can look plausible even when they do not support the exact claim.",
    "The output is usually a one-shot answer."
], BLUE)
bullet_box(slide, 6.55, 2.05, 5.10, 3.95, "Scientific database construction", [
    "Decides whether an entity deserves a row.",
    "Assigns an entry-level verification state.",
    "The cited paper must support the exact rubric predicate.",
    "The output is an inspectable, correctable database artifact."
], TEAL)
pill(slide, 1.25, 6.28, 1.55, "missing evidence", GOLD, size=10.5)
pill(slide, 3.05, 6.28, 1.80, "exclusion evidence", RED, size=10.5)
pill(slide, 5.10, 6.28, 1.55, "off-scope", PURPLE, size=10.5)
add_textbox(slide, 7.15, 6.23, 4.70, 0.50, "These should change the row label, not just change answer wording.", size=13.2, color=TEAL, bold=True)
add_footer(slide, 2)

# Content slide 3: core idea.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "Core idea: turn user intent into an evidence contract")
add_picture_fit(slide, FIGURE_ASSETS["workflow"], 0.82, 1.50, 6.65, 4.95)
bullet_box(slide, 7.85, 1.45, 3.85, 1.35, "1. Dynamic literature construction", [
    "Search changes as candidates and evidence gaps appear."
], BLUE)
bullet_box(slide, 7.85, 2.95, 3.85, 1.35, "2. Candidate grounding", [
    "Names are normalized and filtered before expensive verification."
], GOLD)
bullet_box(slide, 7.85, 4.45, 3.85, 1.45, "3. Predicate-state verification", [
    "Researcher finds evidence; Critique checks support and exclusions."
], TEAL)
pill(slide, 0.95, 6.36, 1.35, "supported", GREEN)
pill(slide, 2.50, 6.36, 1.40, "unresolved", GOLD)
pill(slide, 4.10, 6.36, 1.55, "exclusion", RED)
pill(slide, 5.88, 6.36, 1.35, "exhausted", RGBColor(170, 181, 190))
quote_box(slide, 7.95, 6.18, 3.75, 0.62, "Accepted = required predicates supported + no triggered exclusion.")
add_footer(slide, 3)

# Content slide 4: application demo.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "Application demo: DBP database construction")
add_textbox(slide, 0.95, 1.28, 11.0, 0.50, "User request: build a database of experimentally confirmed disinfection byproducts.", size=17.2, color=NAVY, bold=True)
bullet_box(slide, 0.82, 2.02, 3.55, 3.20, "Refined rubric", [
    "Water-relevant disinfection or oxidation context.",
    "Formation from disinfectant or oxidant reaction with relevant precursors.",
    "Structural confirmation in peer-reviewed studies."
], TEAL)
bullet_box(slide, 4.58, 2.02, 3.55, 3.20, "Agent execution", [
    "Expand DBP-specific literature searches.",
    "Extract and ground chemical entities.",
    "Ask compound-level verification questions."
], BLUE)
bullet_box(slide, 8.35, 2.02, 3.55, 3.20, "Example question", [
    "Is NDMA an experimentally confirmed DBP?",
    "Which paper supports formation, matrix and analytical confirmation?",
    "Which contexts should block release?"
], GOLD)
metric_card(slide, 1.05, 5.55, 2.80, 1.25, "label", "Confirmed / limited / negative", GREEN, None)
metric_card(slide, 4.05, 5.55, 2.80, 1.25, "evidence", "quotes + citations", BLUE, None)
metric_card(slide, 7.05, 5.55, 2.80, 1.25, "state", "predicate audit trail", TEAL, None)
metric_card(slide, 10.05, 5.55, 2.05, 1.25, "logs", "search history", PURPLE, None)
add_footer(slide, 4)

# Content slide 5: verification logic and citation audit.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_title(slide, "Verification: how do we know the output is reliable?")
bullet_box(slide, 0.82, 1.62, 3.55, 4.72, "Paper-level audit", [
    "Does the cited item resolve to a real primary paper?",
    "Does the paper contain the quoted span or equivalent local context?",
    "Compound lookup pages support identity grounding, but are not counted as primary evidence."
], BLUE)
bullet_box(slide, 4.58, 1.62, 3.55, 4.72, "Predicate-level audit", [
    "The paper must support the actual rubric predicate.",
    "Mentioning the same compound is not enough.",
    "Reagent, solvent, precursor or out-of-scope context can block release."
], TEAL)
metric_card(slide, 8.55, 1.47, 3.10, 1.42, "2,166/2,166", "fixed-cohort support", GREEN, "Refs with quote/context support.")
metric_card(slide, 8.55, 3.05, 3.10, 1.42, "7,430/7,453", "benchmark-scale support", BLUE, "Auditable refs across five domains.")
metric_card(slide, 8.55, 4.63, 3.10, 1.42, "11/257", "zero-shot baseline", RED, "Usable refs from direct generation.")
quote_box(slide, 0.95, 6.34, 10.85, 0.66, "Trust argument: the output is not trusted because the model says so; it is trusted because the cited paper and predicate can be inspected.")
add_footer(slide, 5)

# Content slide 6: results and ML lesson.
slide = prs.slides.add_slide(prs.slide_layouts[1])
add_small_title(slide, "Results and ML lesson: why agentic design matters")
result_panel(slide, 0.82, 1.52, 3.70, 3.28, "Release-ready construction", [
    ("246/250", "release-ready rows"),
    ("68", "benchmark-missing, human-validated entries"),
    ("4", "rejected non-overlap errors")
], BLUE)
result_panel(slide, 4.82, 1.52, 3.70, 3.28, "Benchmark-scale verification", [
    ("1,887", "evaluated candidates across five domains"),
    ("977", "system Confirmed labels"),
    ("7,430/7,453", "auditable primary-paper refs")
], TEAL)
result_panel(slide, 8.82, 1.52, 3.70, 3.28, "Critique-loop utility", [
    ("49", "evidence-limited rows rescued to Confirmed"),
    ("5", "premature Confirmed labels tightened away"),
    ("51/54", "changed decisions judged right by human inspection")
], RED)
quote_box(slide, 1.05, 5.42, 11.15, 1.05, "Final ML lesson: the value of agentic AI in science is not fluent generation. It is dynamic evidence construction, explicit state tracking and critique-driven correction.", color=TEAL)
add_textbox(slide, 1.25, 6.55, 10.55, 0.45, "Practical implication: humans audit compact evidence trails and edge cases instead of manually searching every paper from scratch.", size=13.0, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
add_footer(slide, 6)

prs.save(PPTX)
print(PPTX)
