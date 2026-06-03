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

prs = Presentation(TEMPLATE)

# Remove example slides while preserving masters/layouts.
def delete_slide(prs, index):
    xml_slides = prs.slides._sldIdLst
    slides = list(xml_slides)
    xml_slides.remove(slides[index])

while len(prs.slides):
    delete_slide(prs, 0)

W = prs.slide_width
H = prs.slide_height

# Template-friendly palette.
NAVY = RGBColor(24, 54, 96)
TEAL = RGBColor(38, 112, 94)
BLUE = RGBColor(70, 130, 180)
LIGHT_BLUE = RGBColor(217, 230, 240)
GREEN = RGBColor(108, 171, 128)
LIGHT_GREEN = RGBColor(220, 238, 224)
GOLD = RGBColor(226, 180, 87)
RED = RGBColor(198, 96, 96)
GRAY = RGBColor(98, 108, 118)
LIGHT_GRAY = RGBColor(238, 242, 245)
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
        set_text(t.text_frame, title, size=36, color=BLACK, bold=False)
    except Exception:
        add_textbox(slide, 0.7, 0.45, 9.5, 0.8, title, size=36)
    if subtitle:
        add_textbox(slide, 0.75, 1.35, 10.3, 0.55, subtitle, size=17, color=GRAY)


def add_footer(slide, n):
    add_textbox(slide, 11.25, 7.22, 1.55, 0.25, "Trusted and Efficient AI Group", size=9.5, color=RGBColor(130,130,130), align=PP_ALIGN.RIGHT)
    add_textbox(slide, 12.85, 7.22, 0.25, 0.25, str(n), size=12, color=BLACK, align=PP_ALIGN.RIGHT)


def rect(slide, x, y, w, h, fill=WHITE, line=RGBColor(220,220,220), radius=True):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid(); shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = line; shape.line.width = Pt(1)
    return shape


def metric(slide, x, y, w, h, number, label, body, accent):
    rect(slide, x, y, w, h, WHITE, RGBColor(218,226,232))
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(0.07))
    bar.fill.solid(); bar.fill.fore_color.rgb = accent; bar.line.color.rgb = accent
    add_textbox(slide, x+0.25, y+0.18, w-0.5, 0.45, number, size=28, color=accent, bold=True)
    add_textbox(slide, x+0.25, y+0.78, w-0.5, 0.46, label, size=14.8, color=BLACK, bold=True)
    if body:
        add_textbox(slide, x+0.25, y+1.28, w-0.5, h-1.40, body, size=9.5, color=GRAY, line_spacing=0.9)


def pill(slide, x, y, w, text, color, text_color=WHITE):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(0.35))
    shp.fill.solid(); shp.fill.fore_color.rgb = color
    shp.line.color.rgb = color
    set_text(shp.text_frame, text, size=12.5, color=text_color, bold=True, align=PP_ALIGN.CENTER)
    return shp


def arrow(slide, x1, y1, x2, y2, color=GRAY):
    shp = slide.shapes.add_connector(1, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    shp.line.color.rgb = color
    shp.line.width = Pt(2)
    try:
        shp.line.end_arrowhead = True
    except Exception:
        pass
    return shp


def bullet_block(slide, x, y, w, h, heading, bullets, accent=BLUE):
    rect(slide, x, y, w, h, WHITE, RGBColor(218,226,232))
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(0.07))
    bar.fill.solid(); bar.fill.fore_color.rgb = accent; bar.line.color.rgb = accent
    add_textbox(slide, x+0.25, y+0.28, w-0.5, 0.35, heading, size=17, color=BLACK, bold=True)
    tf = slide.shapes.add_textbox(Inches(x+0.28), Inches(y+0.82), Inches(w-0.55), Inches(h-0.92)).text_frame
    tf.clear(); tf.word_wrap = True
    for i,b in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = b
        p.level = 0
        p.font.name = FONT
        p.font.size = Pt(12.5)
        p.font.color.rgb = GRAY
        p.space_after = Pt(4)
        p.line_spacing = 0.9

# Slide 1: title.
slide = prs.slides.add_slide(prs.slide_layouts[0])
set_text(slide.shapes.title.text_frame, "DB-Curator", size=44, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
set_text(slide.placeholders[1].text_frame, "Agentic scientific database construction with auditable evidence", size=22, color=BLACK, bold=True, align=PP_ALIGN.CENTER)
add_textbox(slide, 3.0, 5.55, 7.4, 0.5, "Dynamic literature construction + predicate-state verification", size=18, color=TEAL, bold=True, align=PP_ALIGN.CENTER)
add_textbox(slide, 3.3, 6.15, 6.9, 0.35, "Chen Zhao, Botao Liu, Xiaoxiao Li, Tao Huan", size=14, color=BLACK, align=PP_ALIGN.CENTER)

# Slide 2.
slide = prs.slides.add_slide(prs.slide_layouts[1]); add_title(slide, "Why scientific database construction is an agentic task")
metric(slide, 0.75, 2.10, 3.75, 1.82, "Not Q&A", "Task mismatch", "A database row must be accepted, rejected, or left evidence-limited with provenance.", BLUE)
metric(slide, 4.75, 2.10, 3.75, 1.82, "Dynamic", "Corpus construction", "The paper set is built during the run from scope, candidates and critique feedback.", TEAL)
metric(slide, 8.75, 2.10, 3.75, 1.82, "Auditable", "Entry-level evidence", "Accepted compounds need cited papers, local context and evidence spans.", GREEN)
pill(slide, 1.0, 5.1, 2.5, "less manual triage", BLUE)
pill(slide, 3.75, 5.1, 3.0, "explicit inclusion/exclusion", TEAL)
pill(slide, 7.05, 5.1, 2.7, "paper-grounded rows", GOLD)
pill(slide, 10.05, 5.1, 2.45, "edge-case review", RGBColor(120,110,165))
add_textbox(slide, 0.95, 6.1, 11.5, 0.65, "Core message for ML + science: the agent is useful because it controls search, state, and stopping criteria, not because it writes fluent summaries.", size=16, color=GRAY, bold=False)
add_footer(slide, 2)

# Slide 3 workflow.
slide = prs.slides.add_slide(prs.slide_layouts[1]); add_title(slide, "DB-Curator workflow")
steps = [("1 Scope", "request → rubric\ninclusion / exclusion", BLUE), ("2 Literature", "broad search\nseed expansion\nfollow-up", LIGHT_BLUE), ("3 Candidates", "NER + grounding\nranking + queue", GOLD), ("4 Verification", "Researcher reads\nCritique audits", RGBColor(214,142,67)), ("5 Database", "accepted rows\nspans + IDs", GREEN)]
x0=0.72
for i,(h,b,c) in enumerate(steps):
    x=x0+i*2.45
    rect(slide,x,2.05,2.1,1.55,WHITE,RGBColor(218,226,232))
    bar=slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(2.05), Inches(2.1), Inches(0.07)); bar.fill.solid(); bar.fill.fore_color.rgb=c; bar.line.color.rgb=c
    add_textbox(slide,x+0.18,2.35,1.75,0.3,h,size=16,bold=True,color=BLACK)
    add_textbox(slide,x+0.18,2.83,1.75,0.52,b,size=12.3,color=GRAY,line_spacing=0.85)
    if i<4: arrow(slide,x+2.12,2.82,x+2.43,2.82)
rect(slide,2.5,4.45,8.45,1.55,WHITE,RGBColor(218,226,232))
add_textbox(slide,2.82,4.72,3.1,0.35,"Predicate-state loop",size=18,bold=True,color=BLACK)
pill(slide,3.0,5.28,1.3,"supported",GREEN)
pill(slide,4.75,5.28,1.35,"unresolved",GOLD)
pill(slide,6.55,5.28,1.9,"exclusion",RED)
pill(slide,8.9,5.28,1.25,"exhausted",RGBColor(170,181,190))
add_textbox(slide,2.82,6.20,8.3,0.55,"Critique asks which predicate is unsupported, what evidence is missing, and what should be searched next.",size=15,color=GRAY)
add_footer(slide,3)

# Slide 4 release audit.
slide = prs.slides.add_slide(prs.slide_layouts[1]); add_title(slide, "Application: release-ready database rows")
metric(slide,0.85,2.05,3.25,1.30,"178","Known entries","",BLUE)
metric(slide,0.85,3.75,3.25,1.30,"68","Benchmark-missing valid","",GREEN)
metric(slide,0.85,5.45,3.25,1.30,"4","Low release error","",RED)
# stacked bar
add_textbox(slide,5.0,2.08,6.8,0.35,"Release audit over five domains",size=20,bold=True,color=BLACK)
bar_x, bar_y, bar_w, bar_h = 5.0, 3.05, 6.9, 1.15
segments=[(178,BLUE,"178"),(68,GREEN,"68"),(4,RED,"4")]
left=bar_x
for val,c,label in segments:
    w=bar_w*val/250
    shp=slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(bar_y), Inches(w), Inches(bar_h))
    shp.fill.solid(); shp.fill.fore_color.rgb=c; shp.line.color.rgb=WHITE
    add_textbox(slide,left+w/2-0.4,bar_y+0.40,0.8,0.28,label,size=18,color=WHITE if val>20 else BLACK,bold=True,align=PP_ALIGN.CENTER)
    left+=w
add_textbox(slide,5.0,4.45,6.8,0.4,"Rows out of 250: benchmark overlap, benchmark-missing true, false",size=12,color=GRAY)
add_textbox(slide,5.0,5.55,7.0,0.85,"Scientific punchline: the system recovers known entries and surfaces literature-buried additions with auditable evidence.",size=17,color=GRAY)
add_footer(slide,4)

# Slide 5 verification.
slide = prs.slides.add_slide(prs.slide_layouts[1]); add_title(slide, "Verification: evidence trails survive paper-level audit")
metric(slide,0.85,2.0,3.65,1.7,"2,166/2,166","DB-Curator release audit","All cited primary-paper references contained supporting span or local context.",GREEN)
metric(slide,4.85,2.0,3.65,1.7,"11/257","Zero-shot generation","Plausible rows, but few usable evidence trails.",RED)
metric(slide,8.85,2.0,3.65,1.7,"7,430/7,453","Benchmark-scale audit","Almost all cited references had quote/context support.",BLUE)
# support bars
for i,(lab,pct,c) in enumerate([("DB-Curator release audit",1.0,GREEN),("Zero-shot generation",11/257,RED),("DB-Curator benchmark-scale",7430/7453,BLUE)]):
    y=4.65+i*0.65
    add_textbox(slide,1.25,y-0.05,3.0,0.25,lab,size=12.5,bold=True,color=BLACK)
    bg=slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(4.5), Inches(y), Inches(6.1), Inches(0.22)); bg.fill.solid(); bg.fill.fore_color.rgb=LIGHT_GRAY; bg.line.color.rgb=LIGHT_GRAY
    fg=slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(4.5), Inches(y), Inches(6.1*pct), Inches(0.22)); fg.fill.solid(); fg.fill.fore_color.rgb=c; fg.line.color.rgb=c
    add_textbox(slide,10.8,y-0.06,0.8,0.3,f"{pct*100:.1f}%" if pct<1 else "100%",size=13,color=c,bold=True)
add_textbox(slide,1.0,6.68,11.3,0.35,"Audit rule: resolve paper identity → search recovered text → accept exact quote or equivalent local context → exclude lookup pages.",size=12.8,color=GRAY)
add_footer(slide,5)

# Slide 6 benchmark + agent loop.
slide = prs.slides.add_slide(prs.slide_layouts[1]); add_title(slide, "Benchmark-scale verification across domains")
metric(slide,0.85,2.0,2.8,1.20,"1,887","Candidate rows","",BLUE)
metric(slide,0.85,3.55,2.8,1.20,"977","Confirmed by system","",GREEN)
metric(slide,0.85,5.10,2.8,1.20,"375","Baseline","",RGBColor(170,181,190))
# bar chart using native rectangles
chart_x, chart_y, chart_w, chart_h = 4.3, 2.15, 7.4, 3.35
add_textbox(slide,4.3,1.75,5.0,0.3,"Confirmed fraction by topic",size=17,bold=True,color=BLACK)
for k in range(5):
    y=chart_y+chart_h*(k/4)
    line=slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(chart_x), Inches(y), Inches(chart_w), Inches(0.005)); line.fill.solid(); line.fill.fore_color.rgb=RGBColor(225,230,235); line.line.color.rgb=RGBColor(225,230,235)
topics=["DBP","Blood","Drug","Endog.","Microbial\nNP"]
db=[321/687,86/300,210/300,123/300,237/300]
base=[137/687,5/300,120/300,69/300,44/300]
db_counts=["321/687","86/300","210/300","123/300","237/300"]
base_counts=["137/687","5/300","120/300","69/300","44/300"]
for i,t in enumerate(topics):
    x=chart_x+0.55+i*1.35
    for j,(v,c) in enumerate([(db[i],BLUE),(base[i],RGBColor(170,181,190))]):
        h=chart_h*v/0.9
        shp=slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x+j*0.32), Inches(chart_y+chart_h-h), Inches(0.28), Inches(h))
        shp.fill.solid(); shp.fill.fore_color.rgb=c; shp.line.color.rgb=c
        label = db_counts[i] if j == 0 else base_counts[i]
        if v > 0.06:
            add_textbox(slide, x+j*0.32-0.16, chart_y+chart_h-h-0.28, 0.62, 0.18, label, size=8.4, color=c, bold=True, align=PP_ALIGN.CENTER)
    add_textbox(slide,x-0.1,chart_y+chart_h+0.15,0.9,0.45,t,size=10.5,color=BLACK,align=PP_ALIGN.CENTER)
for yv in [0,0.3,0.6,0.9]:
    add_textbox(slide,chart_x-0.55,chart_y+chart_h-chart_h*yv/0.9-0.08,0.48,0.2,f"{yv:.1f}",size=9,color=GRAY,align=PP_ALIGN.RIGHT)
pill(slide,4.5,5.95,1.45,"DB-Curator",BLUE)
pill(slide,6.05,5.95,1.85,"zero-shot baseline",RGBColor(170,181,190))
add_textbox(slide,4.3,6.55,7.2,0.55,"ML takeaway: this is not one classifier threshold. Different topic definitions create different predicate gates and failure modes.",size=13,color=GRAY)
add_footer(slide,6)

# Slide 7 agent loop? User asked 5-6; keep exactly 6 by not adding separate. Instead final takeaway in slide 6.

prs.save(PPTX)
print(PPTX)
