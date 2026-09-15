#!/usr/bin/env python3
"""Static preflight audit for figure-plotting source.

Checks a Python plotting script for known risk patterns before rendering.
Deterministic, no network, no plotting imports. Warnings are review prompts,
not scientific validation: a PASS here never means the figure is correct.
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

UNSAFE_CMAPS = {"jet", "rainbow", "hsv", "gist_rainbow", "gist_ncar", "cool"}
EXCLUDE_NOTE = re.compile(r"排除|记录|保留|缺失|删失|剔除|drop|exclusion|keep", re.IGNORECASE)
MATHTEXT = re.compile(r"\$[^$]+\$")
PANEL_LETTER = re.compile(r"['\"]([a-pA-P])['\"]")

FONT_CHECK = "FONT-GLYPH-FLOOR"
CMAP_CHECK = "COLORMAP-UNSAFE"
INTERP_CHECK = "INTERP-MONOTONIC"
SAMPLE_CHECK = "SILENT-SAMPLING"
ROTATION_CHECK = "ROTATION-ANCHOR"
BBOX_CHECK = "ANNOTATION-WORKAROUND"
PANEL_CHECK = "PANEL-LABELS"
EXPORT_CHECK = "EXPORT-VECTOR"
DPI_CHECK = "DPI-RASTER"
MIX_CHECK = "BACKEND-MIX"
GATE_CHECK = "ALIGNMENT-GATE"

ALL_CHECKS = (FONT_CHECK, CMAP_CHECK, INTERP_CHECK, SAMPLE_CHECK, ROTATION_CHECK,
              BBOX_CHECK, PANEL_CHECK, EXPORT_CHECK, DPI_CHECK, MIX_CHECK, GATE_CHECK)


def _line(node) -> int:
    return node.lineno if node else 0


def _nearby_note(source: str, lineno: int) -> bool:
    lines = source.splitlines()
    start = max(0, lineno - 4)
    return bool(EXCLUDE_NOTE.search("\n".join(lines[start:lineno])))


def _iter_calls(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def _func_name(node) -> str:
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return ""


def _kwarg(node, name):
    for kw in node.keywords:
        if kw.arg == name:
            return kw
    return None


def _num_value(kw):
    if kw is None:
        return None
    if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
        return float(kw.value.value)
    return None


def _has_white_bbox(source: str) -> bool:
    for line in source.splitlines():
        if re.search(r"bbox\s*=\s*dict\([^)]*facecolor\s*=\s*['\"]white['\"]", line):
            return True
        if re.search(r"facecolor\s*=\s*['\"]white['\"]", line) and "bbox" in line:
            return True
    return False


def validate_source(source: str) -> list:
    """Return a list of check dicts: {check_id, level, message, evidence}."""
    findings = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [{"check_id": "SYNTAX", "level": "FAIL",
                 "message": f"Plotting source does not parse: {exc}",
                 "evidence": [f"line {exc.lineno}: {exc.msg}"]}]

    calls = list(_iter_calls(tree))
    font_sizes = []
    for call in calls:
        val = _num_value(_kwarg(call, "fontsize"))
        if val is not None:
            font_sizes.append((val, _line(call)))
    small = [(v, ln) for v, ln in font_sizes if v < 5]
    if small:
        findings.append({"check_id": FONT_CHECK, "level": "WARN",
                         "message": "fontsize below 5 pt; mathtext sub/superscripts shrink to ~0.7x and may fall under the floor.",
                         "evidence": [f"line {ln}: fontsize={v:g}" for v, ln in small]})
    elif MATHTEXT.search(source) and any(v < 7 for v, _ in font_sizes):
        findings.append({"check_id": FONT_CHECK, "level": "WARN",
                         "message": "mathtext used with parent fontsize < 7 pt; rendered glyphs may fall below the 5 pt floor.",
                         "evidence": ["consider Unicode glyphs such as R² or raise the parent size"]})

    for call in calls:
        cmap = _kwarg(call, "cmap")
        value = ""
        if cmap is not None and isinstance(cmap.value, ast.Constant):
            value = str(cmap.value.value)
        elif cmap is not None and isinstance(cmap.value, ast.Name):
            value = cmap.value.id
        if value and value.lower().lstrip("'\"") in UNSAFE_CMAPS:
            findings.append({"check_id": CMAP_CHECK, "level": "WARN",
                             "message": f"unsafe colormap '{value}'; use a perceptually uniform map and a color-blind-safe palette.",
                             "evidence": [f"line {_line(call)}"]})

    if re.search(r"\b(?:np|numpy)\.interp\s*\(", source) and "argsort" not in source \
            and "interp_monotone" not in source:
        findings.append({"check_id": INTERP_CHECK, "level": "WARN",
                         "message": "np.interp requires increasing xp; sort/assert monotonicity or use a guarded helper.",
                         "evidence": ["add argsort + strict-monotonicity assertion before interpolation"]})

    for call in calls:
        name = _func_name(call)
        if name in ("sample", "head", "dropna") and isinstance(call.func, ast.Attribute):
            if not _nearby_note(source, call.lineno):
                findings.append({"check_id": SAMPLE_CHECK, "level": "WARN",
                                 "message": f"'{name}' filters observations; record the predicate and before/after counts in QA notes.",
                                 "evidence": [f"line {_line(call)}"]})

    for call in calls:
        if _func_name(call) == "text":
            has_rotation = _kwarg(call, "rotation") is not None
            has_mode = _kwarg(call, "rotation_mode") is not None
            if has_rotation and not has_mode:
                findings.append({"check_id": ROTATION_CHECK, "level": "WARN",
                                 "message": "rotated text lacks rotation_mode='anchor'; bounding box may drift.",
                                 "evidence": [f"line {_line(call)}"]})

    if _has_white_bbox(source):
        findings.append({"check_id": BBOX_CHECK, "level": "WARN",
                         "message": "opaque white bbox used to mask overlaps; reposition text instead of hiding the path.",
                         "evidence": ["remove bbox=dict(facecolor='white')"]})

    panel_count = 0
    for call in calls:
        if _func_name(call) == "subplots":
            dims = [int(a.value) for a in call.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, (int, float))]
            if len(dims) >= 2:
                panel_count = max(panel_count, dims[0] * dims[1])
            if any(kw.arg in ("nrows", "ncols") for kw in call.keywords):
                panel_count = max(panel_count, 2)
        if _func_name(call) == "subplot_mosaic":
            panel_count = max(panel_count, 2)
        if _func_name(call) == "add_subplot":
            panel_count += 1
    if panel_count >= 2 and not PANEL_LETTER.search(source):
        findings.append({"check_id": PANEL_CHECK, "level": "WARN",
                         "message": "multi-panel figure without panel letters; add bold lowercase labels (a, b, ...).",
                         "evidence": [f"detected {panel_count}+ axes"]})

    formats, raster_dpi, dynamic_export = [], [], False
    for call in calls:
        if _func_name(call) == "savefig":
            if any(kw.arg is None for kw in call.keywords):
                dynamic_export = True
            for arg in call.args:
                segment = ast.get_source_segment(source, arg) or ""
                match = re.search(r"\.(svg|pdf|png|tiff?|jpe?g|webp)", segment.lower())
                if match:
                    formats.append(match.group(1))
            if _kwarg(call, "dpi") is not None:
                raster_dpi.append(_num_value(_kwarg(call, "dpi")))
    if dynamic_export:
        findings.append({"check_id": EXPORT_CHECK, "level": "PASS",
                         "message": "export formats are dynamic; verify vector (SVG/PDF) output and dpi at render time.",
                         "evidence": []})
    elif not formats:
        findings.append({"check_id": EXPORT_CHECK, "level": "WARN",
                         "message": "no savefig found; deliver editable vector output (SVG/PDF) plus a raster preview.",
                         "evidence": ["add savefig with svg/pdf"]})
    elif not ({"svg", "pdf"} & set(formats)):
        findings.append({"check_id": EXPORT_CHECK, "level": "WARN",
                         "message": "only raster exports found; keep an editable vector version (SVG/PDF).",
                         "evidence": [f"formats: {sorted(set(formats))}"]})
    if not dynamic_export and ({"png", "tiff", "jpg", "jpeg", "webp"} & set(formats)) \
            and not any(d and d >= 300 for d in raster_dpi):
        findings.append({"check_id": DPI_CHECK, "level": "WARN",
                         "message": "raster export without dpi >= 300; set dpi explicitly for publication previews.",
                         "evidence": [f"formats: {sorted(set(formats))}"]})

    if re.search(r"\b(?:plt|matplotlib)\.", source) and re.search(r"\b(?:library\s*\(|ggplot\s*\(|ggsave\s*\()", source):
        findings.append({"check_id": MIX_CHECK, "level": "WARN",
                         "message": "source mixes matplotlib and R-style calls; keep one exclusive backend.",
                         "evidence": ["choose Python or R and use it for preview, export and QA"]})

    if panel_count >= 2 and "alignment" not in source.lower():
        findings.append({"check_id": GATE_CHECK, "level": "WARN",
                         "message": "multi-panel figure without an alignment check; verify equal row/column edges and gutters at final size.",
                         "evidence": ["run an alignment audit or measure panel rectangles before export"]})

    for check in ALL_CHECKS:
        if not any(f["check_id"] == check for f in findings):
            findings.append({"check_id": check, "level": "PASS", "message": "no finding", "evidence": []})
    return findings


def audit_file(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    findings = validate_source(source)
    warnings = [f for f in findings if f["level"] == "WARN"]
    failed = [f for f in findings if f["level"] == "FAIL"]
    status = "failed" if failed else ("warnings_found" if warnings else "checks_passed")
    return {"status": status, "file": str(path), "language": "python",
            "scope": "Deterministic source preflight only; no statistical or visual verification.",
            "warnings": len(warnings), "checks": findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Python plotting script to audit")
    parser.add_argument("--json-out", type=Path, help="write JSON report to this file")
    parser.add_argument("--strict", action="store_true", help="treat WARN as blocking")
    args = parser.parse_args()
    try:
        result = audit_file(args.source)
    except OSError as exc:
        print(json.dumps({"status": "input_error", "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.json_out:
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    has_warn = any(f["level"] == "WARN" for f in result["checks"])
    has_fail = any(f["level"] == "FAIL" for f in result["checks"])
    return 1 if (has_fail or (args.strict and has_warn)) else 0


if __name__ == "__main__":
    sys.exit(main())
