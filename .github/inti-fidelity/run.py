"""One-off exact-main regression run; no compiler source modifications."""
from __future__ import annotations

import json
import subprocess
from collections import Counter
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageOps
from pptx import Presentation as ReadPPTX

from domoxml import Presentation, Slide
from domoxml.types import OutputFormat, SlideSize

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "inti_20261103"
OUT = ROOT / "inti-main-fidelity-results"
OUT.mkdir(exist_ok=True)

deck = Presentation(size=SlideSize.WIDE_16_9)
for i in range(1, 7):
    markup = (FIXTURES / f"slide-{i}.html").read_text(encoding="utf-8")
    deck.add(Slide(html=markup))

print("COMPILER_CWD:", ROOT, flush=True)
print("COMPILER_GIT_SHA:", subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(), flush=True)
result = deck.render({OutputFormat.PPTX, OutputFormat.PNG})
if result.pptx is None:
    raise RuntimeError("domOXML returned no PPTX")
(OUT / "inti-main.pptx").write_bytes(result.pptx)
if len(result.pngs) != 6:
    raise AssertionError(f"expected 6 PNGs; got {len(result.pngs)}")
for i, data in enumerate(result.pngs, 1):
    (OUT / f"source-{i}.png").write_bytes(data)

pptx = ReadPPTX(BytesIO(result.pptx))
stats = []
for i, slide in enumerate(pptx.slides, 1):
    shapes = list(slide.shapes)
    typenames = Counter(str(s.shape_type) for s in shapes)
    text_nodes = []
    for shape in shapes:
        if getattr(shape, "has_text_frame", False) and shape.text:
            text_nodes.append({
                "text": shape.text,
                "x": shape.left,
                "y": shape.top,
                "width": shape.width,
                "height": shape.height,
            })
    row = {
        "slide": i,
        "shapes": len(shapes),
        "shape_types": dict(typenames),
        "text_shapes": len(text_nodes),
        "text": text_nodes,
    }
    stats.append(row)
    print("SLIDE_STATS", json.dumps({k:v for k,v in row.items() if k!="text"}), flush=True)
    print("SLIDE_TEXT", i, [t["text"] for t in text_nodes], flush=True)

warnings = [{"element":str(getattr(w,"element","")),"message":str(getattr(w,"message",""))} for w in result.warnings]
print("WARNINGS", json.dumps(warnings), flush=True)
(OUT / "coverage-and-shapes.json").write_text(json.dumps({
    "commit": subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT).decode().strip(),
    "slides":stats,
    "warnings":warnings,
},indent=2),encoding="utf-8")

# Native PPTX rendering via LibreOffice; this follows the earlier review's
# rendering environment as closely as possible.
converter = subprocess.run([
    "soffice","-env:UserInstallation=file:///tmp/inti-fidelity-lo-profile",
    "--headless","--convert-to","pdf","--outdir",str(OUT),str(OUT/"inti-main.pptx")
],capture_output=True,text=True,timeout=180)
print("SOFFICE_EXIT",converter.returncode,converter.stdout,converter.stderr,flush=True)
pdf=OUT/"inti-main.pdf"
if converter.returncode != 0 or not pdf.exists():
    raise RuntimeError("LibreOffice could not render the generated PPTX")
subprocess.run(["pdftoppm","-png","-r","96",str(pdf),str(OUT/"pptx")],
               check=True,timeout=120,capture_output=True)
for i in range(1,7):
    source=Image.open(OUT/f"source-{i}.png").convert("RGB")
    current=Image.open(OUT/f"pptx-{i}.png").convert("RGB")
    if current.size!=source.size:
        current=current.resize(source.size,Image.Resampling.LANCZOS)
    # Left: browser source; right: LO PowerPoint render.
    comparison=Image.new("RGB",(source.width*2,source.height),"#eeeeee")
    comparison.paste(source,(0,0))
    comparison.paste(current,(source.width,0))
    comparison.save(OUT/f"compare-{i}.png")
    diff=ImageChops.difference(source,current)
    h=diff.histogram()
    total = sum((idx%256)*n for idx,n in enumerate(h))
    mae=total/(source.width*source.height*3)
    print("RENDER_DIFF",i,round(mae,3),flush=True)

print("RESULT_OK",len(stats),"slides",flush=True)
