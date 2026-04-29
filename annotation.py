"""
annotation.py — Bean Quality Annotator (deployment build)

Deployed on Streamlit Cloud. Users upload PNG images, annotate them,
and download a ZIP of all JSON annotation files when done.

    pip install streamlit pillow streamlit-drawable-canvas
"""

from __future__ import annotations

import base64
import csv
import io
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw

try:
    import streamlit.elements.image as st_image
    from streamlit.elements.lib.image_utils import image_to_url as _image_to_url
    from streamlit.elements.lib.layout_utils import LayoutConfig

    if not hasattr(st_image, "image_to_url"):
        def image_to_url_compat(image, width, clamp, channels, output_format, image_id):
            return _image_to_url(
                image,
                LayoutConfig(width=width),
                clamp,
                channels,
                output_format,
                image_id,
            )

        st_image.image_to_url = image_to_url_compat
except Exception:
    pass

try:
    import streamlit_drawable_canvas as drawable_canvas
    from streamlit_drawable_canvas import st_canvas
except ImportError:
    drawable_canvas = None
    st_canvas = None


def _patch_drawable_canvas_frontend() -> None:
    """Allow data URL backgrounds in streamlit-drawable-canvas 0.9.3.

    The bundled frontend prepends the Streamlit app origin to every background
    URL. That works for /media/... URLs, but breaks data:image/... URLs, which
    are the most reliable way to keep uploaded images visible on Streamlit Cloud.
    """
    if drawable_canvas is None:
        return
    try:
        source_build = Path(drawable_canvas.__file__).parent / "frontend" / "build"
        patched_build = Path(tempfile.gettempdir()) / "bean_annotator_drawable_canvas_build"
        shutil.copytree(source_build, patched_build, dirs_exist_ok=True)

        for js_path in (patched_build / "static" / "js").glob("main.*.js"):
            src = js_path.read_text(encoding="utf-8")
            old = "e.src=n+h"
            new = 'e.src=h&&h.startsWith("data:")?h:n+h'
            if old in src and new not in src:
                js_path.write_text(src.replace(old, new), encoding="utf-8")
            break

        drawable_canvas._component_func = components.declare_component(
            "st_canvas_patched",
            path=str(patched_build),
        )
    except OSError:
        pass


_patch_drawable_canvas_frontend()


# ── Constants ─────────────────────────────────────────────────────────────────

BORDER_WIDTH     = 8
MAX_CANVAS_WIDTH = 760
MIN_CANVAS_WIDTH = 620
MIN_DEFECT_AREA  = 25
ANNOTATION_VER   = 3
RESAMPLE         = getattr(Image, "Resampling", Image).LANCZOS

DEFECT_TYPES = [
    "Crack", "Hole", "Discoloration", "Mold", "Spot",
    "Broken", "Wrinkle", "Insect Damage", "Foreign Matter", "Other",
]

SEVERITY = {
    1: {"label": "Excellent", "color": "#16a34a", "fg": "#fff",
        "desc": "Intact, clean, evenly colored. No defects. Highest quality grade."},
    2: {"label": "Very Good", "color": "#65a30d", "fg": "#fff",
        "desc": "Minor cosmetic variation only. No structural defect or contamination."},
    3: {"label": "Moderate",  "color": "#d97706", "fg": "#fff",
        "desc": "Limited visible flaw — small crack, spot, wrinkle, or mild discoloration."},
    4: {"label": "Poor",      "color": "#ea580c", "fg": "#fff",
        "desc": "Prominent damage, breakage, or discoloration. Likely downgraded or rejected."},
    5: {"label": "Severe",    "color": "#dc2626", "fg": "#fff",
        "desc": "Clearly unusable. Severe defect, mold, major breakage, or contamination."},
}

STEPS = [
    ("Inspect",       "Use the zoom viewer. Scroll to zoom, drag to pan, double-click to reset."),
    ("Rate",          "Assign the overall severity from 1 (Excellent) to 5 (Severe)."),
    ("Draw defects",  "Switch to Draw tab. Draw a polygon around each defect."),
    ("Label defects", "For each shape select the defect type, severity, and add notes."),
    ("Save",          "Click Save. Download the annotations ZIP from the sidebar regularly."),
]

PANEL_STEPS = {
    "Inspect & Rate": {0, 1},
    "Draw Defects":   {2, 3},
    "Saved JSON":     {4},
}


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
<style>
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
.block-container { padding-top:1.25rem !important; padding-bottom:3rem !important; max-width:1200px !important; }
h1 { font-size:1.2rem !important; font-weight:700 !important; letter-spacing:-0.02em; color:#0f172a; }
h2 { font-size:1rem !important; font-weight:700 !important; color:#0f172a; }
h3, h4 { font-size:0.88rem !important; font-weight:600 !important; color:#374151; }
button { border-radius:5px !important; font-size:0.82rem !important; font-weight:500 !important; }
button[kind="primary"] { background:#0f172a !important; border:1px solid #0f172a !important; color:#fff !important; font-weight:600 !important; }
button[kind="primary"]:hover { background:#1e293b !important; }
button[kind="secondary"] { background:#fff !important; border:1px solid #d1d5db !important; color:#374151 !important; }
button[kind="secondary"]:hover { background:#f9fafb !important; }
.stTextInput label, .stTextArea label, .stSelectbox label,
.stNumberInput label, .stRadio label span, .stCheckbox label span {
    font-size:0.78rem !important; font-weight:600 !important; color:#374151 !important;
}
div[data-testid="stProgress"] > div { height:2px !important; background:#e5e7eb !important; border-radius:0 !important; }
div[data-testid="stProgress"] > div > div { background:#0f172a !important; border-radius:0 !important; }
div[data-testid="stMetric"] { background:transparent !important; padding:0 !important; }
div[data-testid="stMetricValue"] { font-size:1.35rem !important; font-weight:700 !important; color:#0f172a !important; }
div[data-testid="stMetricLabel"] { font-size:0.72rem !important; font-weight:500 !important; color:#6b7280 !important; }
.stCaption p { font-size:0.75rem !important; color:#9ca3af !important; }
hr { border:none !important; border-top:1px solid #f3f4f6 !important; margin:0.75rem 0 !important; }
details { border:1px solid #e5e7eb !important; border-radius:6px !important; overflow:hidden; }
details summary { font-size:0.8rem !important; font-weight:600 !important; color:#374151 !important; padding:10px 14px !important; background:#f9fafb !important; cursor:pointer; }
details[open] summary { border-bottom:1px solid #e5e7eb !important; }
details > div { padding:14px !important; }
div[data-testid="stToast"] { border-radius:6px !important; font-size:0.82rem !important; font-weight:500 !important; border:1px solid #e5e7eb !important; }
div[data-testid="stDataFrame"] { border:1px solid #e5e7eb !important; border-radius:6px !important; overflow:hidden; }
div[data-testid="stRadio"] > div { gap:8px !important; }
div[data-testid="stRadio"] label { font-size:0.82rem !important; }
/* ── Sidebar ── */
section[data-testid="stSidebar"] { background:#f8fafc !important; border-right:1px solid #e2e8f0 !important; min-width:248px !important; }
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] .stMarkdown li,
section[data-testid="stSidebar"] small,
section[data-testid="stSidebar"] .stCaption p { color:#64748b !important; font-size:0.78rem !important; }
section[data-testid="stSidebar"] strong, section[data-testid="stSidebar"] b { color:#0f172a !important; }
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] h4 { color:#0f172a !important; }
section[data-testid="stSidebar"] hr { border-color:#e2e8f0 !important; }
section[data-testid="stSidebar"] div[data-testid="stMetricValue"] { color:#0f172a !important; font-size:1.3rem !important; }
section[data-testid="stSidebar"] div[data-testid="stMetricLabel"] { color:#64748b !important; }
section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] label span { color:#374151 !important; }
section[data-testid="stSidebar"] div[data-testid="stProgress"] > div { background:#e2e8f0 !important; }
section[data-testid="stSidebar"] div[data-testid="stProgress"] > div > div { background:#2563eb !important; }
section[data-testid="stSidebar"] .stButton button { background:#fff !important; border:1px solid #d1d5db !important; color:#374151 !important; font-size:0.8rem !important; }
section[data-testid="stSidebar"] .stButton button:hover { background:#f1f5f9 !important; border-color:#94a3b8 !important; }
</style>
"""


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _html(content: str) -> None:
    if hasattr(st, "html"):
        st.html(content)
    else:
        st.markdown(content, unsafe_allow_html=True)


def _col_html(col: Any, content: str) -> None:
    if hasattr(col, "html"):
        col.html(content)
    else:
        col.markdown(content, unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────
# imgs      : dict[mid, bytes]       — raw PNG bytes per image
# img_order : list[str]              — sorted list of mask IDs
# anns      : dict[mid, dict]        — annotation records
# annotator : str
# ready     : bool

def all_anns() -> dict[str, dict[str, Any]]:
    return st.session_state.get("anns", {})


def get_ann(mask_id: str) -> dict[str, Any]:
    return all_anns().get(mask_id, blank_annotation(mask_id))


def save_ann(ann: dict[str, Any]) -> None:
    ann["timestamp"] = utc_now()
    st.session_state.setdefault("anns", {})[ann["mask_id"]] = ann


def open_img(mask_id: str) -> Image.Image:
    return Image.open(io.BytesIO(st.session_state["imgs"][mask_id])).convert("RGB")


def project_bundle_bytes() -> bytes:
    """One resumable export with images, detailed JSON annotations, and labels.csv."""
    order = st.session_state.get("img_order", [])
    annotations = all_anns()
    images = st.session_state.get("imgs", {})
    files = [Path(f"{m}.png") for m in order]
    manifest = {
        "bundle_version": 1,
        "created_at": utc_now(),
        "annotation_version": ANNOTATION_VER,
        "annotator": st.session_state.get("annotator", ""),
        "image_order": order,
        "image_filenames": {mid: image_filename_of(mid) for mid in order},
        "annotation_count": len(annotations),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("labels.csv", csv_bytes(files, annotations))
        for mid in order:
            if mid in images:
                zf.writestr(f"images/{image_filename_of(mid)}", image_png_bytes(images[mid]))
            ann = annotations.get(mid, blank_annotation(mid))
            ann = normalize_annotation_for_export(ann, mid)
            zf.writestr(f"annotations/{mid}.json", json.dumps(ann, indent=2))
    return buf.getvalue()


def project_bundle_filename() -> str:
    order = st.session_state.get("img_order", [])
    if not order:
        return "annotations_bundle.zip"
    if len(order) == 1:
        return f"{order[0]}_annotations_bundle.zip"
    return f"{order[0]}_to_{order[-1]}_{len(order)}_annotations_bundle.zip"


def image_filename_of(mask_id: str) -> str:
    return f"{mask_id}.png"


def image_png_bytes(raw: bytes) -> bytes:
    """Normalize uploaded image bytes to PNG for the resumable bundle."""
    out = io.BytesIO()
    Image.open(io.BytesIO(raw)).convert("RGB").save(out, format="PNG")
    return out.getvalue()


def normalize_annotation_for_export(ann: dict[str, Any], mask_id: str) -> dict[str, Any]:
    """Ensure exported records are keyed by the image stem and use closed polygons."""
    out = dict(ann)
    image_stem = str(out.get("image_stem") or mask_id)
    out["annotation_version"] = out.get("annotation_version", ANNOTATION_VER)
    out["mask_id"] = str(out.get("mask_id") or mask_id)
    out["image_stem"] = image_stem
    out["image_filename"] = str(out.get("image_filename") or image_filename_of(image_stem))
    out["defects"] = [normalize_defect_geometry(d) for d in (out.get("defects", []) or [])]
    return out


def load_resume_uploads(uploaded_files: list[Any]) -> tuple[dict[str, bytes], dict[str, dict], list[str], list[str]]:
    """Load new ZIP bundles, old annotation ZIPs, or old individual JSON files."""
    bundled_imgs: dict[str, bytes] = {}
    prior: dict[str, dict] = {}
    skipped: list[str] = []
    unmatched: list[str] = []

    def add_ann(data: Any, source_name: str, valid_mask_ids: set[str] | None) -> None:
        if not isinstance(data, dict):
            raise ValueError("annotation JSON must be an object")
        mid = str(data.get("mask_id") or Path(source_name).stem)
        if valid_mask_ids is not None and mid not in valid_mask_ids:
            unmatched.append(source_name)
            return
        prior[mid] = normalize_annotation_for_export(data, mid)

    for f in uploaded_files or []:
        name = f.name
        raw = f.getvalue()
        suffix = Path(name).suffix.lower()
        try:
            if suffix == ".zip":
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    for img_name in zf.namelist():
                        if img_name.endswith("/") or not img_name.startswith("images/"):
                            continue
                        if Path(img_name).suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                            continue
                        mid = Path(img_name).stem
                        try:
                            bundled_imgs[mid] = image_png_bytes(zf.read(img_name))
                        except Exception:
                            skipped.append(f"{name}:{img_name}")

                    valid_ids = set(bundled_imgs) if bundled_imgs else None
                    json_names = [
                        n for n in zf.namelist()
                        if n.lower().endswith(".json")
                        and Path(n).name != "manifest.json"
                        and not n.endswith("/")
                    ]
                    if not json_names:
                        skipped.append(name)
                        continue
                    for json_name in json_names:
                        try:
                            data = json.loads(zf.read(json_name).decode("utf-8"))
                            add_ann(data, json_name, valid_ids)
                        except Exception:
                            skipped.append(f"{name}:{json_name}")
            else:
                data = json.loads(raw)
                add_ann(data, name, None)
        except Exception:
            skipped.append(name)

    return bundled_imgs, prior, skipped, unmatched


# ── Core data helpers ─────────────────────────────────────────────────────────

def severity_color(sev: int | None) -> str:
    return SEVERITY.get(sev, {}).get("color", "#64748b")


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i: i + 2], 16) for i in (0, 2, 4))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_id_of(path: Path) -> str:
    return path.stem


def blank_annotation(mask_id: str) -> dict[str, Any]:
    return {
        "annotation_version": ANNOTATION_VER,
        "mask_id":            mask_id,
        "image_stem":         mask_id,
        "image_filename":     f"{mask_id}.png",
        "overall_severity":   None,
        "overall_notes":      "",
        "defects":            [],
        "skip":               {"skipped": False, "reason": ""},
        "timestamp":          None,
        "annotator":          "",
    }


def is_done(ann: dict[str, Any]) -> bool:
    return bool(ann.get("skip", {}).get("skipped")) or ann.get("overall_severity") in SEVERITY


def next_unfinished(files: list[Path], annotations: dict[str, dict[str, Any]], start: int) -> int:
    for i in range(start, len(files)):
        mid = mask_id_of(files[i])
        if not is_done(annotations.get(mid, blank_annotation(mid))):
            return i
    return min(start, len(files) - 1)


# ── CSV / download ────────────────────────────────────────────────────────────

_CSV_FIELDS = [
    "image_stem", "image_filename", "mask_id", "overall_severity", "severity_label", "defect_count",
    "skipped", "skip_reason", "overall_notes", "timestamp", "annotator",
]


def _csv_row(mask_id: str, ann: dict[str, Any]) -> dict:
    sev = ann.get("overall_severity")
    image_stem = ann.get("image_stem") or mask_id
    image_filename = ann.get("image_filename") or f"{image_stem}.png"
    return {
        "image_stem":       image_stem,
        "image_filename":   image_filename,
        "mask_id":          mask_id,
        "overall_severity": sev or "",
        "severity_label":   SEVERITY.get(sev, {}).get("label", ""),
        "defect_count":     len(ann.get("defects", []) or []),
        "skipped":          bool(ann.get("skip", {}).get("skipped")),
        "skip_reason":      ann.get("skip", {}).get("reason", ""),
        "overall_notes":    ann.get("overall_notes", ""),
        "timestamp":        ann.get("timestamp", ""),
        "annotator":        ann.get("annotator", ""),
    }


def csv_bytes(files: list[Path], annotations: dict[str, dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    w   = csv.DictWriter(buf, fieldnames=_CSV_FIELDS)
    w.writeheader()
    for p in files:
        mid = mask_id_of(p)
        w.writerow(_csv_row(mid, annotations.get(mid, blank_annotation(mid))))
    return buf.getvalue().encode("utf-8")


# ── Image helpers ─────────────────────────────────────────────────────────────

def add_border(img: Image.Image, sev: int | None, width: int = BORDER_WIDTH) -> Image.Image:
    out   = img.copy().convert("RGB")
    color = hex_to_rgb(severity_color(sev))
    draw  = ImageDraw.Draw(out)
    w, h  = out.size
    for i in range(width):
        draw.rectangle([i, i, w - 1 - i, h - 1 - i], outline=color)
    return out


def img_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


# ── Zoom viewer ───────────────────────────────────────────────────────────────

def zoom_viewer(img: Image.Image, key: str) -> None:
    url = img_data_url(img)
    components.html(
        f"""
        <div id="z{key}" style="position:relative;width:100%;height:500px;background:#0d1117;border:1px solid #21262d;border-radius:6px;overflow:hidden;">
          <canvas style="width:100%;height:100%;display:block;cursor:grab;"></canvas>
          <div id="hud{key}" style="position:absolute;right:10px;bottom:10px;padding:4px 9px;background:rgba(0,0,0,0.55);color:#c9d1d9;font:11px/1.5 'SF Mono','Fira Code',monospace;border-radius:4px;border:1px solid rgba(255,255,255,0.07);pointer-events:none;">100%</div>
        </div>
        <script>
        (function() {{
          const root=document.getElementById("z{key}"),canvas=root.querySelector("canvas"),hud=document.getElementById("hud{key}"),ctx=canvas.getContext("2d"),img=new Image();
          let sc=1,base=1,ox=0,oy=0,drag=false,lx=0,ly=0;
          function fit(){{const r=root.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.max(1,r.width*dpr|0);canvas.height=Math.max(1,r.height*dpr|0);ctx.setTransform(dpr,0,0,dpr,0,0);base=Math.min(r.width/img.width,r.height/img.height);sc=base;ox=(r.width-img.width*sc)/2;oy=(r.height-img.height*sc)/2;draw();}}
          function draw(){{const r=root.getBoundingClientRect();ctx.clearRect(0,0,r.width,r.height);ctx.imageSmoothingEnabled=true;ctx.drawImage(img,ox,oy,img.width*sc,img.height*sc);hud.textContent=Math.round(sc/base*100)+"% · scroll: zoom · drag: pan · dbl-click: reset";}}
          img.onload=fit;img.src="{url}";new ResizeObserver(fit).observe(root);
          canvas.addEventListener("wheel",e=>{{e.preventDefault();const r=canvas.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top,prev=sc;sc=Math.min(Math.max(base*0.5,sc*(e.deltaY<0?1.12:0.88)),base*14);ox=mx-(mx-ox)/prev*sc;oy=my-(my-oy)/prev*sc;draw();}},{{passive:false}});
          canvas.addEventListener("mousedown",e=>{{drag=true;lx=e.clientX;ly=e.clientY;canvas.style.cursor="grabbing";}});
          window.addEventListener("mouseup",()=>{{drag=false;canvas.style.cursor="grab";}});
          window.addEventListener("mousemove",e=>{{if(!drag)return;ox+=e.clientX-lx;oy+=e.clientY-ly;lx=e.clientX;ly=e.clientY;draw();}});
          canvas.addEventListener("dblclick",fit);
        }})();
        </script>
        """,
        height=520,
    )


# ── Drawing canvas ────────────────────────────────────────────────────────────

def draw_canvas(img: Image.Image, canvas_key: str, mode: str, stroke: str) -> tuple[list[dict], float]:
    if drawable_canvas is None or st_canvas is None:
        st.error("Install streamlit-drawable-canvas to use defect drawing.")
        st.code("pip install streamlit-drawable-canvas")
        return [], 1.0

    w0, h0 = img.size
    cw     = max(MIN_CANVAS_WIDTH, min(MAX_CANVAS_WIDTH, w0))
    scale  = cw / w0 if w0 else 1.0
    ch     = max(1, int(h0 * scale))
    bg     = img.resize((cw, ch), RESAMPLE)

    bg_url = img_data_url(bg)

    # Bypass streamlit-drawable-canvas' Python wrapper for the background image.
    # Its wrapper uses Streamlit's internal media URL API, which can resolve to a
    # blank background on Streamlit Cloud. The frontend accepts a data URL directly.
    try:
        initial_drawing = {"version": "4.4.0", "background": ""}
        component_value = drawable_canvas._component_func(
            fillColor="rgba(255,255,255,0.08)",
            strokeWidth=2,
            strokeColor=stroke,
            backgroundColor="",
            backgroundImageURL=bg_url,
            realtimeUpdateStreamlit=(mode != "polygon"),
            canvasHeight=ch,
            canvasWidth=cw,
            drawingMode=mode,
            initialDrawing=initial_drawing,
            displayToolbar=True,
            displayRadius=3,
            key=canvas_key,
            default=None,
        )
    except Exception as e:
        st.image(bg, caption="Image preview — drawing unavailable")
        st.warning(
            f"The drawing canvas failed to load ({type(e).__name__}: {e}). "
            "You can still rate the bean in Step 1. "
            "Please report this error to the developer: **parimalnath321@gmail.com**"
        )
        return [], scale

    objects = []
    if component_value and component_value.get("raw"):
        objects = component_value["raw"].get("objects", []) or []
    return objects, scale


def fabric_to_shape(obj: dict[str, Any], scale: float) -> dict[str, Any] | None:
    t   = obj.get("type")
    l   = float(obj.get("left", 0))
    tp  = float(obj.get("top",  0))
    w   = float(obj.get("width",  0)) * float(obj.get("scaleX", 1))
    h   = float(obj.get("height", 0)) * float(obj.get("scaleY", 1))
    inv = 1 / scale if scale else 1

    if t == "rect":
        x, y, rw, rh = round(l*inv,2), round(tp*inv,2), round(w*inv,2), round(h*inv,2)
        if rw <= 1 or rh <= 1:
            return None
        return {"shape": "bbox", "bbox": {"x": x, "y": y, "width": rw, "height": rh}}

    if t in {"polygon", "path"}:
        pts = obj.get("points") or []
        if pts:
            poly = [{"x": round((l+float(p.get("x",0)))*inv,2), "y": round((tp+float(p.get("y",0)))*inv,2)} for p in pts]
            poly = close_polygon(poly)
            if len(poly) >= 3:
                return {"shape": "polygon", "polygon": poly}
        elif obj.get("path"):
            poly = path_to_polygon(obj.get("path"), inv)
            bbox = {"x": round(l*inv,2), "y": round(tp*inv,2), "width": round(w*inv,2), "height": round(h*inv,2)}
            if len(poly) >= 4:
                return {"shape": "polygon", "bbox": bbox, "polygon": poly}
            return {"shape": "path", "bbox": bbox, "path": obj.get("path")}
    return None


def close_polygon(points: list[dict[str, float]]) -> list[dict[str, float]]:
    if len(points) < 3:
        return points
    first = points[0]
    last = points[-1]
    if first.get("x") != last.get("x") or first.get("y") != last.get("y"):
        points = [*points, {"x": first["x"], "y": first["y"]}]
    return points


def path_to_polygon(path: Any, inv: float) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    if not isinstance(path, list):
        return points
    for cmd in path:
        if not isinstance(cmd, list) or not cmd:
            continue
        op = str(cmd[0]).upper()
        if op in {"M", "L"} and len(cmd) >= 3:
            points.append({"x": round(float(cmd[1]) * inv, 2), "y": round(float(cmd[2]) * inv, 2)})
        elif op == "Z":
            break
    return close_polygon(points)


def normalize_defect_geometry(defect: dict[str, Any]) -> dict[str, Any]:
    out = dict(defect)
    if out.get("polygon"):
        out["shape"] = "polygon"
        out["polygon"] = close_polygon([{"x": float(p["x"]), "y": float(p["y"])} for p in out.get("polygon", [])])
    elif out.get("path"):
        poly = path_to_polygon(out.get("path"), 1.0)
        if len(poly) >= 4:
            out["shape"] = "polygon"
            out["polygon"] = poly
    if out.get("shape") == "polygon":
        out["closed"] = True
    return out


def shape_area(s: dict[str, Any]) -> float:
    if s.get("shape") in {"bbox", "path"}:
        b = s.get("bbox") or {}
        return float(b.get("width", 0)) * float(b.get("height", 0))
    pts = s.get("polygon") or []
    if len(pts) < 3:
        return 0.0
    area = 0.0
    for i, p in enumerate(pts):
        n = pts[(i + 1) % len(pts)]
        area += float(p["x"]) * float(n["y"]) - float(n["x"]) * float(p["y"])
    return abs(area) / 2


def filter_shapes(objects: list[dict], scale: float) -> list[dict]:
    out = []
    for obj in objects:
        s = fabric_to_shape(obj, scale)
        if s and shape_area(s) >= MIN_DEFECT_AREA:
            out.append(s)
    return out


# ── UI components ─────────────────────────────────────────────────────────────

def severity_selector(current: int | None, key: str) -> int:
    default  = current if current in SEVERITY else 3
    selected = st.radio(
        "Severity",
        options=list(SEVERITY.keys()),
        index=list(SEVERITY.keys()).index(default),
        horizontal=True,
        format_func=lambda v: f"{v} — {SEVERITY[v]['label']}",
        key=key,
        label_visibility="collapsed",
    )
    selected = int(selected)

    cols = st.columns(5)
    for level, col in zip(SEVERITY.keys(), cols):
        meta   = SEVERITY[level]
        is_sel = level == selected
        border  = f"2px solid {meta['color']}" if is_sel else "2px solid transparent"
        opacity = "1" if is_sel else "0.5"
        ring    = f"box-shadow:0 0 0 3px {meta['color']}40;" if is_sel else ""
        _col_html(col,
            f'<div style="padding:10px 4px;border-radius:5px;border:{border};background:{meta["color"]};'
            f'color:{meta["fg"]};text-align:center;opacity:{opacity};{ring}">'
            f'<div style="font-size:1.1rem;font-weight:800;line-height:1;">{level}</div>'
            f'<div style="font-size:0.62rem;font-weight:600;margin-top:4px;opacity:0.9;">{meta["label"]}</div>'
            f'</div>'
        )

    meta = SEVERITY[selected]
    _html(
        f'<div style="margin-top:8px;padding:9px 13px;border-radius:5px;'
        f'background:{meta["color"]}14;border-left:3px solid {meta["color"]};'
        f'font-size:0.82rem;color:#374151;line-height:1.5;">'
        f'<strong style="color:{meta["color"]};">Level {selected} — {meta["label"]}.</strong> {meta["desc"]}'
        f'</div>'
    )
    return selected


def guidelines_panel() -> None:
    with st.expander("Severity reference"):
        parts = []
        for level, meta in SEVERITY.items():
            parts.append(
                f'<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 0;border-bottom:1px solid #f3f4f6;">'
                f'<div style="flex:0 0 52px;text-align:center;padding:5px 0;border-radius:4px;'
                f'background:{meta["color"]};color:{meta["fg"]};font-weight:700;font-size:0.85rem;">{level}</div>'
                f'<div><div style="font-weight:600;font-size:0.82rem;">{meta["label"]}</div>'
                f'<div style="font-size:0.78rem;color:#6b7280;margin-top:2px;">{meta["desc"]}</div>'
                f'</div></div>'
            )
        _html("".join(parts))


def guide_panel(current_panel: str) -> None:
    active = PANEL_STEPS.get(current_panel, set())
    with st.expander("Annotation guide"):
        for i, (title, desc) in enumerate(STEPS):
            is_active = i in active
            num_bg    = "#2563eb" if is_active else "#e5e7eb"
            num_fg    = "#fff"    if is_active else "#6b7280"
            row_bg    = "#eff6ff" if is_active else "transparent"
            title_col = "#1d4ed8" if is_active else "#111827"
            _html(
                f'<div style="display:flex;align-items:flex-start;gap:10px;padding:9px 10px;border-radius:5px;margin-bottom:4px;background:{row_bg};">'
                f'<div style="flex:0 0 22px;height:22px;border-radius:50%;background:{num_bg};color:{num_fg};'
                f'font-size:0.7rem;font-weight:700;display:flex;align-items:center;justify-content:center;min-width:22px;">{i+1}</div>'
                f'<div><div style="font-size:0.8rem;font-weight:600;color:{title_col};">{title}</div>'
                f'<div style="font-size:0.75rem;color:#6b7280;margin-top:2px;">{desc}</div></div>'
                f'</div>'
            )


def existing_defects_table(ann: dict[str, Any]) -> None:
    defects = ann.get("defects", []) or []
    if not defects:
        st.caption("No defects saved yet.")
        return
    rows = [
        {"#": i, "type": d.get("custom_name") or d.get("type", ""),
         "severity": d.get("severity", ""), "shape": d.get("shape", ""), "notes": d.get("notes", "")}
        for i, d in enumerate(defects, 1)
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def defect_form(shapes: list[dict], prefix: str) -> list[dict[str, Any]]:
    defects = []
    for idx, shape in enumerate(shapes, 1):
        bbox = shape.get("bbox", {})
        loc  = f"x {bbox.get('x',0):.0f}, y {bbox.get('y',0):.0f}" if bbox else ""
        loc_span = f'&nbsp;&nbsp;<span style="color:#9ca3af;">{loc}</span>' if loc else ""
        _html(
            f'<div style="padding:10px 13px;border-radius:5px;border:1px solid #e5e7eb;background:#f9fafb;margin:8px 0;">'
            f'<span style="font-size:0.75rem;font-weight:600;color:#374151;">'
            f'Shape {idx} &ndash; {shape.get("shape","").upper()}{loc_span}</span></div>'
        )
        if not st.checkbox("Include", value=True, key=f"{prefix}_inc_{idx}"):
            continue

        c1, c2, c3 = st.columns([1.4, 1, 1.3])
        dtype = c1.selectbox("Type", DEFECT_TYPES, key=f"{prefix}_type_{idx}")
        dsev  = c2.selectbox("Severity", list(SEVERITY.keys()), index=2,
                             format_func=lambda v: f"{v} — {SEVERITY[v]['label']}",
                             key=f"{prefix}_sev_{idx}")
        if dtype == "Other":
            custom = c3.text_input("Name", key=f"{prefix}_custom_{idx}")
        else:
            meta   = SEVERITY[dsev]
            _col_html(c3,
                f'<div style="margin-top:24px;padding:6px 9px;border-radius:4px;'
                f'border-left:3px solid {meta["color"]};background:{meta["color"]}14;'
                f'font-size:0.75rem;font-weight:500;color:#374151;">'
                f'{meta["label"]}: {meta["desc"][:60]}…</div>'
            )
            custom = ""

        notes = st.text_input("Notes", key=f"{prefix}_notes_{idx}",
                              placeholder="Optional — e.g. 'near tip', '3 mm crack'")
        entry: dict[str, Any] = {"type": dtype, "severity": int(dsev), "notes": notes.strip()}
        if custom.strip():
            entry["custom_name"] = custom.strip()
        entry.update(shape)
        defects.append(entry)
    return defects


# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar(files: list[Path], current_mid: str = "") -> str:
    annotations = all_anns()
    total       = len(files)
    completed   = sum(1 for p in files if is_done(annotations.get(mask_id_of(p), blank_annotation(mask_id_of(p)))))
    skipped     = sum(1 for a in annotations.values() if a.get("skip", {}).get("skipped"))
    counts      = {k: sum(1 for a in annotations.values() if a.get("overall_severity") == k) for k in SEVERITY}
    pct         = round(100 * completed / total) if total else 0

    cur_ann  = annotations.get(current_mid, {})
    has_sev  = cur_ann.get("overall_severity") is not None
    has_def  = bool(cur_ann.get("defects"))
    is_skip  = bool(cur_ann.get("skip", {}).get("skipped"))

    with st.sidebar:
        _html(
            '<div style="padding:18px 0 14px;">'
            '<div style="font-size:0.6rem;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#94a3b8;">Bean Quality</div>'
            '<div style="font-size:1.1rem;font-weight:800;color:#0f172a;margin-top:3px;letter-spacing:-0.02em;">Annotator</div>'
            '</div>'
        )

        # ── Panel step navigator ──
        if "_switch_to_panel" in st.session_state:
            st.session_state["workflow_panel"] = st.session_state.pop("_switch_to_panel")
        if "workflow_panel" not in st.session_state:
            st.session_state["workflow_panel"] = "Inspect & Rate"

        panel = st.session_state["workflow_panel"]

        step_defs = [
            ("Inspect & Rate", "Inspect & Rate", "Rate overall severity",   has_sev or is_skip),
            ("Draw Defects",   "Draw Defects",   "Mark individual defects", has_def or is_skip),
            ("Saved JSON",     "Review JSON",     "Inspect saved record",    False),
        ]

        _html('<div style="font-size:0.6rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:#94a3b8;margin-bottom:8px;">Steps</div>')

        step_parts = []
        for i, (panel_key, label, sub, step_done) in enumerate(step_defs, 1):
            is_active = panel_key == panel
            if step_done:
                circle_bg, circle_fg, circle_val = "#16a34a", "#fff", "&#10003;"
                label_col, sub_col = "#6b7280", "#9ca3af"
                row_bg, row_border, left_bar = "transparent", "transparent", "#16a34a"
            elif is_active:
                circle_bg, circle_fg, circle_val = "#2563eb", "#fff", str(i)
                label_col, sub_col = "#1e40af", "#3b82f6"
                row_bg, row_border, left_bar = "#eff6ff", "#bfdbfe", "#2563eb"
            else:
                circle_bg, circle_fg, circle_val = "#fff", "#9ca3af", str(i)
                label_col, sub_col = "#9ca3af", "#cbd5e1"
                row_bg, row_border, left_bar = "transparent", "#e5e7eb", "#e5e7eb"

            step_parts.append(
                f'<div style="display:flex;align-items:center;gap:11px;padding:9px 12px;border-radius:7px;'
                f'background:{row_bg};border:1px solid {row_border};margin-bottom:4px;border-left:3px solid {left_bar};">'
                f'<div style="flex:0 0 24px;height:24px;border-radius:50%;background:{circle_bg};'
                f'color:{circle_fg};font-size:0.68rem;font-weight:800;display:flex;align-items:center;'
                f'justify-content:center;min-width:24px;border:1.5px solid {row_border};">{circle_val}</div>'
                f'<div><div style="font-size:0.8rem;font-weight:{"700" if is_active else "500"};color:{label_col};line-height:1.2;">{label}</div>'
                f'<div style="font-size:0.68rem;color:{sub_col};margin-top:2px;">{sub}</div></div>'
                f'</div>'
            )
        _html("".join(step_parts))

        _html('<div style="height:1px;background:#e2e8f0;margin:16px 0;"></div>')

        # ── Progress ──
        _html('<div style="font-size:0.6rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:#94a3b8;margin-bottom:10px;">Progress</div>')
        _html(
            f'<div style="padding:14px 16px;background:#fff;border-radius:8px;border:1px solid #e2e8f0;margin-bottom:10px;">'
            f'<div style="font-size:1.8rem;font-weight:900;color:#0f172a;line-height:1;">{pct}%</div>'
            f'<div style="font-size:0.72rem;color:#64748b;margin-top:4px;">'
            f'{completed} of {total} annotated &nbsp;·&nbsp; {skipped} skipped</div>'
            f'</div>'
        )
        st.progress(completed / total if total else 0)

        _html('<div style="height:1px;background:#e2e8f0;margin:16px 0;"></div>')

        # ── Severity breakdown ──
        _html('<div style="font-size:0.6rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:#94a3b8;margin-bottom:10px;">By severity</div>')
        sev_parts = []
        for level, count in counts.items():
            meta  = SEVERITY[level]
            bar_w = round(100 * count / total) if total else 0
            sev_parts.append(
                f'<div style="margin-bottom:7px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
                f'<span style="display:flex;align-items:center;gap:6px;font-size:0.75rem;color:#374151;">'
                f'<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:{meta["color"]};"></span>'
                f'{level} &ndash; {meta["label"]}</span>'
                f'<span style="font-size:0.75rem;font-weight:700;color:#111827;">{count}</span></div>'
                f'<div style="height:4px;background:#f1f5f9;border-radius:99px;">'
                f'<div style="width:{bar_w}%;height:100%;background:{meta["color"]};border-radius:99px;"></div>'
                f'</div></div>'
            )
        _html("".join(sev_parts))

        _html('<div style="height:1px;background:#e2e8f0;margin:16px 0;"></div>')

        # ── Downloads ──
        _html('<div style="font-size:0.6rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:#94a3b8;margin-bottom:8px;">Export</div>')
        st.download_button("Download project bundle", data=project_bundle_bytes(),
                           file_name=project_bundle_filename(), mime="application/zip",
                           use_container_width=True)
        st.caption("Download regularly — annotations are not saved after refresh.")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Start over", use_container_width=True):
            for key in ["imgs", "img_order", "anns", "annotator", "ready", "workflow_panel"]:
                st.session_state.pop(key, None)
            st.rerun()

    return panel


# ── Setup page ────────────────────────────────────────────────────────────────

def setup_page() -> None:
    _, col, _ = st.columns([1, 1.8, 1])
    with col:
        _html(
            '<div style="padding:28px 0 18px;text-align:center;">'
            '<div style="font-size:0.62rem;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#9ca3af;margin-bottom:8px;">Bean Quality Annotator</div>'
            '<div style="font-size:1.5rem;font-weight:800;letter-spacing:-0.03em;color:#0f172a;margin:0 0 6px;">Start a session</div>'
            '<p style="font-size:0.84rem;color:#6b7280;margin:0;">Upload your bean images to begin annotating.</p>'
            '</div>'
        )

        annotator = st.text_input("Annotator name", placeholder="Optional — your name or initials")

        img_files = st.file_uploader(
            "Bean images (PNG / JPG)",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            help="Select all images you want to annotate in this session.",
        )
        ann_files = st.file_uploader(
            "Resume — upload previous project bundle or JSONs (optional)",
            type=["zip", "json"],
            accept_multiple_files=True,
            help="Upload bean_annotations_bundle.zip, or older individual .json files, to continue where you left off.",
        )

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("Start annotating", type="primary", use_container_width=True):
            imgs: dict[str, bytes] = {}
            skipped_images: list[str] = []
            for f in (img_files or []):
                mid = Path(f.name).stem
                raw = f.getvalue()
                try:
                    with Image.open(io.BytesIO(raw)) as check:
                        check.verify()
                    imgs[mid] = raw
                except Exception:
                    skipped_images.append(f.name)

            if skipped_images:
                st.warning("Skipped invalid image file(s): " + ", ".join(skipped_images))

            bundle_imgs, prior, skipped_json, unmatched_json = load_resume_uploads(ann_files or [])
            for mid, raw in bundle_imgs.items():
                imgs.setdefault(mid, raw)

            if skipped_json:
                st.warning("Skipped invalid resume file(s): " + ", ".join(skipped_json))
            valid_ids = set(imgs.keys())
            unmatched_json.extend(mid for mid in prior if mid not in valid_ids)
            prior = {mid: ann for mid, ann in prior.items() if mid in valid_ids}
            if unmatched_json:
                st.warning("Skipped annotations with no matching image: " + ", ".join(unmatched_json))

            if not imgs:
                st.error("Upload at least one image, or upload a project bundle that contains images.")
                return

            st.session_state.update({
                "imgs":      imgs,
                "img_order": sorted(imgs.keys()),
                "anns":      prior,
                "annotator": annotator.strip(),
                "ready":     True,
            })
            st.rerun()

        st.divider()
        _html(
            '<div style="font-size:0.74rem;color:#9ca3af;text-align:center;line-height:1.7;">'
            'Annotate &nbsp;·&nbsp; Download one project bundle &nbsp;·&nbsp; Upload it next session to resume'
            '</div>'
        )


# ── Annotation view ───────────────────────────────────────────────────────────

def annotation_view() -> None:
    files = [Path(f"{m}.png") for m in st.session_state.get("img_order", [])]
    total = len(files)

    if total == 0:
        st.error("No images loaded. Go back and upload PNG files.")
        if st.button("Back to setup"):
            st.session_state["ready"] = False
            st.rerun()
        return

    annotations = all_anns()

    idx_key = "idx"
    if idx_key not in st.session_state:
        st.session_state[idx_key] = next_unfinished(files, annotations, 0)

    cur  = max(0, min(int(st.session_state[idx_key]), total - 1))
    st.session_state[idx_key] = cur
    file = files[cur]
    mid  = mask_id_of(file)

    panel = sidebar(files, current_mid=mid)
    ann   = get_ann(mid)

    try:
        img = open_img(mid)
    except Exception as e:
        st.error(f"Cannot open image '{mid}': {e}")
        st.session_state[idx_key] = min(cur + 1, total - 1)
        st.rerun()
        return

    sev       = ann.get("overall_severity")
    skipped   = ann.get("skip", {}).get("skipped")
    completed = sum(1 for p in files if is_done(annotations.get(mask_id_of(p), blank_annotation(mask_id_of(p)))))
    pct       = round(100 * completed / total) if total else 0

    # ── Header ──
    h_left, h_right = st.columns([3, 1])
    with h_left:
        _html(
            f'<div style="margin-bottom:2px;">'
            f'<span style="font-size:1.05rem;font-weight:700;color:#0f172a;">Bean {cur + 1} of {total}</span>'
            f'<span style="font-size:0.75rem;color:#9ca3af;margin-left:10px;">{mid}</span>'
            f'</div>'
        )
        annotator_name = st.session_state.get("annotator") or "—"
        st.caption(f"Annotator: {annotator_name}  ·  {completed} of {total} done ({pct}%)")
    with h_right:
        if sev:
            meta = SEVERITY[sev]
            _html(
                f'<div style="text-align:center;padding:8px 12px;border-radius:5px;background:{meta["color"]};color:{meta["fg"]};">'
                f'<div style="font-size:0.58rem;font-weight:600;letter-spacing:0.08em;opacity:0.75;text-transform:uppercase;">saved</div>'
                f'<div style="font-size:1.4rem;font-weight:800;line-height:1.1;">{sev}</div>'
                f'<div style="font-size:0.62rem;font-weight:600;">{meta["label"]}</div>'
                f'</div>'
            )
        elif skipped:
            _html(
                '<div style="text-align:center;padding:8px 12px;border-radius:5px;background:#f1f5f9;border:1px solid #e2e8f0;color:#64748b;">'
                '<div style="font-size:0.58rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;">skipped</div>'
                '<div style="font-size:0.8rem;font-weight:600;margin-top:4px;">—</div>'
                '</div>'
            )

    st.progress(completed / total if total else 0)

    # ── Navigation ──
    st.markdown("<br>", unsafe_allow_html=True)
    n1, n2, n3, n4 = st.columns([1, 1.4, 1, 1.5])
    if n1.button("Previous", use_container_width=True, disabled=cur == 0):
        st.session_state[idx_key] = cur - 1
        st.rerun()
    with n2:
        jump = st.number_input("Jump to", min_value=1, max_value=total,
                               value=cur + 1, step=1, label_visibility="collapsed")
        if st.button(f"Go to {int(jump)}", use_container_width=True):
            st.session_state[idx_key] = int(jump) - 1
            st.rerun()
    if n3.button("Next", use_container_width=True, disabled=cur >= total - 1):
        st.session_state[idx_key] = cur + 1
        st.rerun()
    if n4.button("Next unfinished", use_container_width=True):
        st.session_state[idx_key] = next_unfinished(files, all_anns(), cur + 1)
        st.rerun()

    st.divider()

    # ── Widget state init ──
    sev_key   = f"sev_{mid}"
    notes_key = f"notes_{mid}"
    if sev_key not in st.session_state:
        st.session_state[sev_key]   = sev if sev in SEVERITY else 3
    if notes_key not in st.session_state:
        st.session_state[notes_key] = ann.get("overall_notes", "")

    cur_sev   = int(st.session_state.get(sev_key, 3))
    cur_notes = str(st.session_state.get(notes_key, ""))
    defects   = ann.get("defects", []) or []

    guide_panel(panel)
    guidelines_panel()
    st.divider()

    # ── Active panel ──
    if panel == "Inspect & Rate":
        zoom_viewer(add_border(img, sev) if sev else img, key=mid)
        st.divider()
        st.caption("Overall severity")
        cur_sev = severity_selector(cur_sev, key=sev_key)
        st.caption("Notes")
        cur_notes = st.text_area("Notes", placeholder="Optional observations about overall bean quality.",
                                 key=notes_key, height=80, label_visibility="collapsed")

    elif panel == "Draw Defects":
        st.caption("Draw one closed polygon per defect. Fill in type and severity below the canvas.")
        mode = "polygon"

        objects, canvas_scale = draw_canvas(img, canvas_key=f"cv_{mid}", mode=mode, stroke=severity_color(cur_sev))

        if objects:
            shapes  = filter_shapes(objects, canvas_scale)
            ignored = len(objects) - len(shapes)
            n_s     = len(shapes)
            st.caption(f"{n_s} shape{'s' if n_s != 1 else ''} detected{f' — {ignored} ignored (too small)' if ignored else ''}")
            defects = defect_form(shapes, prefix=f"d_{mid}")
        else:
            defects = ann.get("defects", []) or []
            st.caption("No shapes drawn. Existing defects will be preserved on save.")

        with st.expander(f"Saved defects ({len(ann.get('defects', []) or [])})"):
            existing_defects_table(ann)

    else:
        st.caption("Annotation record")
        if ann.get("timestamp"):
            st.caption(f"Last saved: {ann['timestamp']}")
        st.json(ann)

    # ── Actions ──
    st.divider()

    def _do_save(advance_to_next: bool) -> None:
        updated = {
            "annotation_version": ANNOTATION_VER,
            "mask_id":            mid,
            "image_stem":         mid,
            "image_filename":     image_filename_of(mid),
            "overall_severity":   int(cur_sev),
            "overall_notes":      cur_notes.strip(),
            "defects":            [normalize_defect_geometry(d) for d in defects],
            "skip":               {"skipped": False, "reason": ""},
            "timestamp":          utc_now(),
            "annotator":          st.session_state.get("annotator", ""),
        }
        save_ann(updated)
        st.toast(f"Saved — {mid} · Severity {cur_sev} ({SEVERITY[int(cur_sev)]['label']})")
        if advance_to_next:
            st.session_state[idx_key] = min(cur + 1, total - 1)
            st.session_state["_switch_to_panel"] = "Inspect & Rate"

    def _skip_widget() -> None:
        with st.expander("Skip"):
            skip_reason = st.text_input("Reason", key=f"skipreason_{mid}",
                                        placeholder="Blurred, duplicate, unclear...",
                                        label_visibility="collapsed")
            st.caption("Skip when the image cannot be reliably annotated.")
            if st.button("Confirm skip", use_container_width=True):
                updated = blank_annotation(mid)
                updated.update({
                    "image_stem":     mid,
                    "image_filename": image_filename_of(mid),
                    "overall_notes": cur_notes.strip(),
                    "defects":       [normalize_defect_geometry(d) for d in (ann.get("defects", []) or [])],
                    "skip":          {"skipped": True, "reason": skip_reason.strip() or "No reason given"},
                    "timestamp":     utc_now(),
                    "annotator":     st.session_state.get("annotator", ""),
                })
                save_ann(updated)
                st.toast(f"Skipped — {mid}")
                st.session_state[idx_key] = min(cur + 1, total - 1)
                st.session_state["_switch_to_panel"] = "Inspect & Rate"
                st.rerun()

    if panel == "Inspect & Rate":
        s_col, n_col, skip_col = st.columns([1.2, 1.2, 1])
        with s_col:
            if st.button("Save", type="primary", use_container_width=True):
                _do_save(advance_to_next=False)
                st.rerun()
        with n_col:
            if st.button("Next Step →", use_container_width=True):
                _do_save(advance_to_next=False)
                st.session_state["_switch_to_panel"] = "Draw Defects"
                st.rerun()
        with skip_col:
            _skip_widget()

    elif panel == "Draw Defects":
        p_col, s_col, skip_col = st.columns([1.2, 1.2, 1])
        with p_col:
            if st.button("← Previous Step", use_container_width=True):
                st.session_state["_switch_to_panel"] = "Inspect & Rate"
                st.rerun()
        with s_col:
            if st.button("Save", type="primary", use_container_width=True):
                _do_save(advance_to_next=True)
                st.rerun()
        with skip_col:
            _skip_widget()

    else:
        s_col, b_col = st.columns([1.2, 1])
        with s_col:
            if st.button("Save", type="primary", use_container_width=True):
                _do_save(advance_to_next=True)
                st.rerun()
        with b_col:
            if st.button("← Back to Step 1", use_container_width=True):
                st.session_state["_switch_to_panel"] = "Inspect & Rate"
                st.rerun()

    if completed == total:
        st.success("All beans annotated or skipped. Download the project bundle from the sidebar.")


# ── Entry point ───────────────────────────────────────────────────────────────

def _report_error(e: Exception) -> None:
    st.error("Something went wrong. The page may recover on reload.")
    with st.expander("Error details — include this when reporting"):
        st.code(f"{type(e).__name__}: {e}", language="text")
    st.info(
        "Please report this error to **parimalnath321@gmail.com** "
        "or open an issue on GitHub. Include the error details above.",
    )
    if st.button("Reload"):
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Bean Quality Annotator",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CSS, unsafe_allow_html=True)

    try:
        if not st.session_state.get("ready"):
            setup_page()
        else:
            annotation_view()
    except Exception as e:
        _report_error(e)


if __name__ == "__main__":
    main()
