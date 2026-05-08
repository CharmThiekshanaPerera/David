from __future__ import annotations

import csv
import io
import re
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


SUPPORTED_UPLOAD_EXTENSIONS: set[str] = {
    ".bmp",
    ".csv",
    ".gif",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".webp",
    ".xls",
    ".xlsx",
}
MAX_TEXT_EXCERPT_CHARS = 4_000
MAX_SAMPLE_ROWS = 8
MAX_TABLE_SCAN_ROWS = 2_000
MAX_PDF_STREAM_BYTES = 2_000_000
MAX_PROFILE_VALUES = 6
MAX_KEYWORDS = 10

_XLSX_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rels": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
_HEADER_SAFE_RE = re.compile(r"[^a-zA-Z0-9_]+")
_NUMBER_RE = re.compile(r"^[+-]?\d+(?:[_,]\d{3})*(?:\.\d+)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{2}/\d{2}/\d{4}$")
_KEYWORD_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "what",
    "which",
    "where",
    "when",
    "your",
    "have",
    "has",
    "were",
    "been",
    "about",
    "page",
    "pages",
    "file",
    "document",
    "image",
    "table",
    "data",
}


def sanitize_upload_filename(file_name: str) -> str:
    raw = str(file_name or "").strip().replace("\\", "/")
    base = Path(raw).name
    if not base:
        base = "upload.bin"
    cleaned = "".join(ch if (ch.isalnum() or ch in {"-", "_", "."}) else "_" for ch in base)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    if not cleaned:
        cleaned = "upload.bin"
    if "." not in cleaned:
        cleaned = f"{cleaned}.bin"
    return cleaned[:120]


def analyze_uploaded_content(file_name: str, content_type: str, content: bytes) -> dict[str, Any]:
    if not isinstance(content, (bytes, bytearray)):
        raise ValueError("Upload content must be bytes.")
    raw = bytes(content)
    if not raw:
        raise ValueError("Uploaded file is empty.")
    clean_name = sanitize_upload_filename(file_name)
    extension = Path(clean_name).suffix.lower()
    detected = _detect_format(extension, str(content_type or ""), raw)
    detected_format = detected["format"]
    kind = detected["kind"]

    if extension and extension not in SUPPORTED_UPLOAD_EXTENSIONS and detected_format not in {"jpeg", "jpg", "png", "gif", "bmp", "webp"}:
        raise ValueError(
            "Unsupported file extension. Allowed: csv, xlsx, xls, pdf, png, jpg, jpeg, gif, bmp, webp."
        )

    if detected_format == "csv":
        return _analyze_csv(clean_name, raw)
    if detected_format == "xlsx":
        return _analyze_xlsx(clean_name, raw)
    if detected_format == "xls":
        return _analyze_legacy_xls(clean_name, raw)
    if detected_format == "pdf":
        return _analyze_pdf(clean_name, raw)
    if kind == "image":
        return _analyze_image(clean_name, raw)

    raise ValueError(
        "Unsupported file type. Allowed: CSV, XLSX, XLS, PDF, and common image formats (PNG/JPEG/GIF/BMP/WEBP)."
    )


def answer_question_from_analysis(analysis: dict[str, Any], question: str) -> dict[str, Any]:
    text = str(question or "").strip()
    if not text:
        raise ValueError("Question cannot be empty.")
    if not isinstance(analysis, dict) or not analysis:
        raise ValueError("Upload analysis is missing.")

    fmt = str(analysis.get("format", "")).strip().lower()
    summary = str(analysis.get("summary", "")).strip()
    content_brief = str(analysis.get("content_brief", "")).strip()
    tokens = _tokenize(text)
    lowered_question = text.casefold()
    evidence: list[dict[str, Any]] = []
    confidence = 0.35
    summary_intent = any(
        tok in tokens
        for tok in {"summary", "summarize", "about", "describe", "description", "show", "showing", "content", "inside"}
    )
    if summary_intent and content_brief:
        return {
            "answer": content_brief,
            "confidence": 0.86,
            "evidence": [{"type": "content_brief"}],
            "analysis_summary": summary,
        }

    stats = analysis.get("stats", {})
    count_intent = any(tok in {"count", "number", "many", "total"} for tok in tokens)
    if isinstance(stats, dict):
        rows = stats.get("rows")
        columns = stats.get("columns")
        if rows is not None and count_intent and any(tok in {"row", "rows"} for tok in tokens):
            answer = f"The analyzed table has {int(rows)} data rows."
            return {"answer": answer, "confidence": 0.85, "evidence": evidence, "analysis_summary": summary}
        if columns is not None and count_intent and any(tok in {"column", "columns"} for tok in tokens):
            answer = f"The analyzed table has {int(columns)} columns."
            return {"answer": answer, "confidence": 0.85, "evidence": evidence, "analysis_summary": summary}

    if fmt in {"csv", "xlsx", "xls"}:
        headers = analysis.get("headers", [])
        sample_rows = analysis.get("sample_rows", [])
        profiles = analysis.get("column_profiles", [])
        header_line = ", ".join(str(h) for h in headers if str(h).strip())
        profile_match = _best_matching_profile(
            [item for item in profiles if isinstance(item, dict)],
            tokens=tokens,
            question_lower=lowered_question,
        )
        if profile_match:
            column_name = str(profile_match.get("name", "")).strip() or "column"
            non_empty = int(profile_match.get("non_empty", 0) or 0)
            missing = int(profile_match.get("missing", 0) or 0)
            unique = int(profile_match.get("unique", 0) or 0)
            top_values = profile_match.get("top_values", [])
            top_preview = ", ".join(str(item) for item in top_values[:MAX_PROFILE_VALUES])
            numeric = profile_match.get("numeric", {})
            if not isinstance(numeric, dict):
                numeric = {}

            wants_avg = any(tok in {"average", "avg", "mean"} for tok in tokens)
            wants_sum = any(tok in {"sum", "total"} for tok in tokens)
            wants_min = any(tok in {"min", "minimum", "lowest"} for tok in tokens)
            wants_max = any(tok in {"max", "maximum", "highest"} for tok in tokens)
            wants_unique = any(tok in {"unique", "distinct"} for tok in tokens)
            wants_missing = any(tok in {"missing", "null", "empty", "blank"} for tok in tokens)

            if numeric and any([wants_avg, wants_sum, wants_min, wants_max]):
                if wants_avg and numeric.get("avg") is not None:
                    answer = f"Average of `{column_name}` is {numeric.get('avg')}."
                elif wants_sum and numeric.get("sum") is not None:
                    answer = f"Total sum of `{column_name}` is {numeric.get('sum')}."
                elif wants_min and numeric.get("min") is not None:
                    answer = f"Minimum of `{column_name}` is {numeric.get('min')}."
                elif wants_max and numeric.get("max") is not None:
                    answer = f"Maximum of `{column_name}` is {numeric.get('max')}."
                else:
                    answer = f"`{column_name}` numeric stats: min={numeric.get('min')}, max={numeric.get('max')}, avg={numeric.get('avg')}."
                evidence.append({"type": "column_profile", "column": column_name, "profile": profile_match})
                return {"answer": answer, "confidence": 0.9, "evidence": evidence, "analysis_summary": summary}

            if wants_missing:
                answer = f"`{column_name}` has {missing} missing values out of {non_empty + missing} scanned records."
                evidence.append({"type": "column_profile", "column": column_name, "profile": profile_match})
                return {"answer": answer, "confidence": 0.86, "evidence": evidence, "analysis_summary": summary}

            if wants_unique:
                answer = f"`{column_name}` has {unique} distinct values. Top values: {top_preview or '-'}."
                evidence.append({"type": "column_profile", "column": column_name, "profile": profile_match})
                return {"answer": answer, "confidence": 0.86, "evidence": evidence, "analysis_summary": summary}

        matched = _best_matching_sample_row(sample_rows if isinstance(sample_rows, list) else [], tokens)
        if matched:
            evidence.append(
                {
                    "type": "sample_row",
                    "row_index": matched["row_index"],
                    "score": matched["score"],
                    "row": matched["row"],
                }
            )
            rendered = " | ".join(f"{k}: {v}" for k, v in matched["row"].items())
            answer = f"Best match from sampled rows is row {matched['row_index']}: {rendered}"
            confidence = 0.8
        else:
            if content_brief:
                answer = content_brief
                confidence = 0.68
            elif header_line:
                answer = f"{summary} Available columns: {header_line}."
                confidence = 0.45
            else:
                answer = summary or "Table analysis is available, but no sampled rows matched your question."
                confidence = 0.45
        return {"answer": answer, "confidence": confidence, "evidence": evidence, "analysis_summary": summary}

    if fmt == "pdf":
        excerpt = str(analysis.get("text_excerpt", "")).strip()
        if summary_intent and content_brief:
            return {
                "answer": content_brief,
                "confidence": 0.88,
                "evidence": [{"type": "content_brief"}],
                "analysis_summary": summary,
            }
        if excerpt:
            sentence = _best_matching_sentence(excerpt, tokens)
            evidence.append({"type": "pdf_excerpt", "text": sentence})
            answer = f"Best matching passage from the document: {sentence}"
            confidence = 0.7
        else:
            answer = summary or "No extractable text was found in the PDF."
            confidence = 0.4
        return {"answer": answer, "confidence": confidence, "evidence": evidence, "analysis_summary": summary}

    if fmt in {"png", "jpg", "jpeg", "gif", "bmp", "webp"}:
        image_stats = analysis.get("stats", {})
        if summary_intent and content_brief:
            return {
                "answer": content_brief,
                "confidence": 0.84,
                "evidence": [{"type": "content_brief"}],
                "analysis_summary": summary,
            }
        if isinstance(image_stats, dict):
            width = image_stats.get("width")
            height = image_stats.get("height")
            if width and height and any(tok in {"size", "dimension", "dimensions", "width", "height"} for tok in tokens):
                answer = f"The image dimensions are {int(width)} x {int(height)} pixels."
                return {"answer": answer, "confidence": 0.9, "evidence": evidence, "analysis_summary": summary}
        excerpt = str(analysis.get("text_excerpt", "")).strip()
        if excerpt and any(tok in {"text", "caption", "label", "title"} for tok in tokens):
            answer = f"Embedded text hints from the image: {excerpt[:280]}"
            confidence = 0.75
        else:
            answer = content_brief or summary or "Image metadata is available."
            confidence = 0.55
        return {"answer": answer, "confidence": confidence, "evidence": evidence, "analysis_summary": summary}

    return {
        "answer": content_brief or summary or "Analysis is available for this upload.",
        "confidence": confidence,
        "evidence": evidence,
        "analysis_summary": summary,
    }


def _detect_format(extension: str, content_type: str, content: bytes) -> dict[str, str]:
    ext = str(extension or "").strip().lower()
    mime = str(content_type or "").strip().lower()
    image_format = _detect_image_format(content)
    if image_format:
        return {"kind": "image", "format": image_format}
    if content.startswith(b"%PDF-") or ext == ".pdf" or "application/pdf" in mime:
        return {"kind": "document", "format": "pdf"}
    if ext == ".csv" or "text/csv" in mime or "application/csv" in mime:
        return {"kind": "table", "format": "csv"}
    if ext == ".xlsx" or ("spreadsheetml.sheet" in mime):
        return {"kind": "table", "format": "xlsx"}
    if ext == ".xls":
        return {"kind": "table", "format": "xls"}
    if ext in _IMAGE_EXTENSIONS:
        fmt = ext.lstrip(".")
        return {"kind": "image", "format": "jpeg" if fmt == "jpg" else fmt}
    if ext in SUPPORTED_UPLOAD_EXTENSIONS:
        return {"kind": "document", "format": ext.lstrip(".")}
    return {"kind": "unknown", "format": "unknown"}


def _analyze_csv(file_name: str, content: bytes) -> dict[str, Any]:
    text = _decode_text_bytes(content)
    reader = csv.reader(io.StringIO(text))
    rows: list[list[str]] = []
    truncated = False
    for idx, row in enumerate(reader):
        if idx >= MAX_TABLE_SCAN_ROWS:
            truncated = True
            break
        rows.append([str(cell).strip() for cell in row])
    if not rows:
        raise ValueError("CSV appears empty.")

    headers = _normalize_headers(rows[0], max(1, len(rows[0])))
    data_rows = rows[1:]
    row_dicts = [_row_to_dict(headers, row) for row in data_rows]
    sample_rows = row_dicts[:MAX_SAMPLE_ROWS]
    excerpt_lines = [",".join(row) for row in rows[: min(len(rows), 6)]]
    text_excerpt = "\n".join(excerpt_lines)[:MAX_TEXT_EXCERPT_CHARS]
    row_count = len(data_rows)
    col_count = len(headers)
    column_profiles = _build_table_profiles(headers, row_dicts)

    summary = f"CSV analyzed: {row_count} data rows and {col_count} columns."
    if truncated:
        summary += " Scan truncated for safety limits."
    content_brief = _build_table_content_brief(headers, row_dicts, column_profiles, summary)

    return {
        "kind": "table",
        "format": "csv",
        "file_name": file_name,
        "summary": summary,
        "content_brief": content_brief,
        "headers": headers,
        "sample_rows": sample_rows,
        "column_profiles": column_profiles,
        "stats": {
            "rows": row_count,
            "columns": col_count,
            "scan_truncated": truncated,
        },
        "text_excerpt": text_excerpt,
        "warnings": [],
    }


def _analyze_xlsx(file_name: str, content: bytes) -> dict[str, Any]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content), mode="r")
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid XLSX archive.") from exc

    with archive:
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names:
            raise ValueError("Invalid XLSX workbook structure.")
        shared_strings = _xlsx_shared_strings(archive)
        sheets = _xlsx_sheet_defs(archive)
        if not sheets:
            raise ValueError("XLSX workbook has no sheets.")
        first_sheet_name, first_sheet_path = sheets[0]
        rows, truncated = _xlsx_sheet_rows(archive, first_sheet_path, shared_strings)
        headers: list[str] = []
        sample_rows: list[dict[str, str]] = []
        row_dicts: list[dict[str, str]] = []
        if rows:
            headers = _normalize_headers(rows[0], max(1, len(rows[0])))
            row_dicts = [_row_to_dict(headers, row) for row in rows[1:]]
            sample_rows = row_dicts[:MAX_SAMPLE_ROWS]
        excerpt_lines = []
        if headers:
            excerpt_lines.append(",".join(headers))
        for row in sample_rows[:5]:
            excerpt_lines.append(",".join(str(row.get(h, "")) for h in headers))
        text_excerpt = "\n".join(excerpt_lines)[:MAX_TEXT_EXCERPT_CHARS]

        row_count = max(0, len(rows) - 1)
        col_count = len(headers)
        column_profiles = _build_table_profiles(headers, row_dicts)
        summary = (
            f"XLSX analyzed: {len(sheets)} sheet(s). "
            f"Primary sheet '{first_sheet_name}' has {row_count} sampled data rows and {col_count} columns."
        )
        if truncated:
            summary += " Scan truncated for safety limits."
        content_brief = _build_table_content_brief(headers, row_dicts, column_profiles, summary)

        return {
            "kind": "table",
            "format": "xlsx",
            "file_name": file_name,
            "summary": summary,
            "content_brief": content_brief,
            "headers": headers,
            "sample_rows": sample_rows,
            "column_profiles": column_profiles,
            "stats": {
                "rows": row_count,
                "columns": col_count,
                "scan_truncated": truncated,
                "sheet_count": len(sheets),
                "sheet_names": [name for name, _ in sheets[:10]],
                "primary_sheet": first_sheet_name,
            },
            "text_excerpt": text_excerpt,
            "warnings": [],
        }


def _analyze_legacy_xls(file_name: str, content: bytes) -> dict[str, Any]:
    is_ole = content.startswith(b"\xD0\xCF\x11\xE0")
    summary = "Legacy XLS uploaded. Basic metadata captured."
    if is_ole:
        summary += " Convert to XLSX for full structured analysis."
    content_brief = (
        "This spreadsheet is a legacy XLS binary file. Internal row/column records cannot be parsed reliably in this mode."
    )
    return {
        "kind": "table",
        "format": "xls",
        "file_name": file_name,
        "summary": summary,
        "content_brief": content_brief,
        "headers": [],
        "sample_rows": [],
        "column_profiles": [],
        "stats": {"rows": 0, "columns": 0, "legacy_binary": bool(is_ole)},
        "text_excerpt": "",
        "warnings": ["Legacy .xls parsing is limited. Convert to .xlsx for full analysis."],
    }


def _analyze_pdf(file_name: str, content: bytes) -> dict[str, Any]:
    if not content.startswith(b"%PDF-"):
        raise ValueError("PDF signature not found.")
    page_count = len(re.findall(rb"/Type\s*/Page\b", content))
    extracted = _extract_pdf_text(content)
    words = re.findall(r"[A-Za-z0-9_]+", extracted)
    keywords = _extract_keywords(extracted, limit=MAX_KEYWORDS)
    content_brief = _build_pdf_content_brief(extracted, keywords, page_count=max(1, page_count))
    summary = f"PDF analyzed: {max(1, page_count)} page marker(s), approx {len(words)} extracted words."
    if not extracted:
        summary += " No readable text could be extracted."
    return {
        "kind": "document",
        "format": "pdf",
        "file_name": file_name,
        "summary": summary,
        "content_brief": content_brief,
        "headers": [],
        "sample_rows": [],
        "stats": {
            "pages": max(1, page_count),
            "word_count": len(words),
            "keywords": keywords,
        },
        "text_excerpt": extracted[:MAX_TEXT_EXCERPT_CHARS],
        "warnings": [] if extracted else ["No readable PDF text extracted from sampled streams."],
    }


def _analyze_image(file_name: str, content: bytes) -> dict[str, Any]:
    fmt = _detect_image_format(content)
    if not fmt:
        raise ValueError("Unsupported or unrecognized image format.")
    width, height = _image_dimensions(fmt, content)
    text_hints = _extract_image_text_hints(fmt, content)
    stats: dict[str, Any] = {"width": width, "height": height}
    if width and height:
        stats["megapixels"] = round((width * height) / 1_000_000, 3)
        summary = f"{fmt.upper()} image analyzed: {width} x {height} pixels."
    else:
        summary = f"{fmt.upper()} image analyzed: dimensions unavailable."
    if text_hints:
        stats["embedded_text_count"] = len(text_hints)
    content_brief = _build_image_content_brief(
        format_name=fmt,
        width=width,
        height=height,
        file_name=file_name,
        text_hints=text_hints,
    )
    return {
        "kind": "image",
        "format": fmt,
        "file_name": file_name,
        "summary": summary,
        "content_brief": content_brief,
        "headers": [],
        "sample_rows": [],
        "stats": stats,
        "text_excerpt": " ".join(text_hints)[:MAX_TEXT_EXCERPT_CHARS] if text_hints else "",
        "warnings": [] if width and height else ["Unable to extract dimensions from image bytes."],
    }


def _decode_text_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _normalize_headers(raw_headers: list[str], count_hint: int) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}
    count = max(count_hint, len(raw_headers))
    for idx in range(count):
        source = raw_headers[idx] if idx < len(raw_headers) else ""
        base = _HEADER_SAFE_RE.sub("_", str(source).strip().lower()).strip("_")
        if not base:
            base = f"column_{idx + 1}"
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            base = f"{base}_{seen[base]}"
        headers.append(base)
    return headers


def _row_to_dict(headers: list[str], row: list[str]) -> dict[str, str]:
    values = list(row)
    if len(values) < len(headers):
        values.extend([""] * (len(headers) - len(values)))
    if len(values) > len(headers):
        values = values[: len(headers)]
    return {headers[idx]: str(values[idx]).strip() for idx in range(len(headers))}


def _build_table_profiles(headers: list[str], rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for header in headers:
        values = [str(row.get(header, "")).strip() for row in rows]
        non_empty = [val for val in values if val != ""]
        missing = len(values) - len(non_empty)
        unique_values = sorted(set(non_empty))
        counts: dict[str, int] = {}
        for value in non_empty:
            counts[value] = counts.get(value, 0) + 1
        top_values = [
            value
            for value, _freq in sorted(
                counts.items(),
                key=lambda item: (-int(item[1]), str(item[0]).casefold()),
            )[:MAX_PROFILE_VALUES]
        ]

        numeric_values: list[float] = []
        date_like = 0
        for value in non_empty:
            parsed_number = _parse_number(value)
            if parsed_number is not None:
                numeric_values.append(parsed_number)
            if _DATE_RE.match(value):
                date_like += 1

        value_count = len(non_empty)
        numeric_ratio = (len(numeric_values) / value_count) if value_count else 0.0
        date_ratio = (date_like / value_count) if value_count else 0.0
        if value_count and numeric_ratio >= 0.6:
            value_type = "numeric"
        elif value_count and date_ratio >= 0.6:
            value_type = "date"
        elif value_count and len(unique_values) <= min(30, max(4, value_count // 2)):
            value_type = "categorical"
        else:
            value_type = "text"

        profile: dict[str, Any] = {
            "name": header,
            "type": value_type,
            "non_empty": value_count,
            "missing": missing,
            "unique": len(unique_values),
            "top_values": top_values,
        }
        if numeric_values:
            numeric_sum = sum(numeric_values)
            profile["numeric"] = {
                "count": len(numeric_values),
                "min": _round_number(min(numeric_values)),
                "max": _round_number(max(numeric_values)),
                "avg": _round_number(numeric_sum / len(numeric_values)),
                "sum": _round_number(numeric_sum),
            }
        profiles.append(profile)
    return profiles


def _build_table_content_brief(
    headers: list[str],
    rows: list[dict[str, str]],
    profiles: list[dict[str, Any]],
    fallback_summary: str,
) -> str:
    if not headers:
        return fallback_summary
    row_count = len(rows)
    header_preview = ", ".join(headers[:6])
    segments = [f"This table contains {row_count} records with fields such as {header_preview}."]
    if rows:
        first = rows[0]
        first_line = ", ".join(f"{name}={first.get(name, '')}" for name in headers[:4])
        if first_line:
            segments.append(f"Sample record: {first_line}.")

    numeric_profiles = [
        item for item in profiles if isinstance(item, dict) and str(item.get("type", "")).lower() == "numeric"
    ]
    if numeric_profiles:
        best = numeric_profiles[0]
        numeric = best.get("numeric", {})
        if isinstance(numeric, dict):
            name = str(best.get("name", "value"))
            low = numeric.get("min")
            high = numeric.get("max")
            avg = numeric.get("avg")
            segments.append(f"Numeric range for `{name}` is {low} to {high} (avg {avg}).")

    categorical_profiles = [
        item for item in profiles if isinstance(item, dict) and str(item.get("type", "")).lower() == "categorical"
    ]
    if categorical_profiles:
        cat = categorical_profiles[0]
        top_values = cat.get("top_values", [])
        if isinstance(top_values, list) and top_values:
            name = str(cat.get("name", "category"))
            segments.append(f"Common values in `{name}` include {', '.join(str(v) for v in top_values[:4])}.")
    return " ".join(segments).strip()[:MAX_TEXT_EXCERPT_CHARS]


def _best_matching_profile(
    profiles: list[dict[str, Any]],
    *,
    tokens: list[str],
    question_lower: str,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = 0
    for profile in profiles:
        name = str(profile.get("name", "")).strip().casefold()
        if not name:
            continue
        parts = [part for part in re.split(r"[_\W]+", name) if part]
        score = 0
        if name and name in question_lower:
            score += 3
        for token in tokens:
            if token == name:
                score += 3
            elif token in parts:
                score += 2
            elif token in name:
                score += 1
        if score > best_score:
            best = profile
            best_score = score
    if best_score <= 0:
        return None
    return best


def _parse_number(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    clean = text.replace(",", "").replace("_", "")
    if not _NUMBER_RE.match(text.replace(" ", "")) and not _NUMBER_RE.match(clean):
        return None
    try:
        return float(clean)
    except ValueError:
        return None


def _round_number(value: float) -> float:
    return float(f"{float(value):.6g}")


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in archive.namelist():
        return []
    try:
        root = ET.fromstring(archive.read(path))
    except Exception:
        return []
    values: list[str] = []
    for si in root.findall("main:si", _XLSX_NS):
        text_bits = [t.text or "" for t in si.findall(".//main:t", _XLSX_NS)]
        values.append("".join(text_bits).strip())
    return values


def _xlsx_sheet_defs(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    try:
        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
    except Exception as exc:
        raise ValueError("Unable to parse workbook.xml.") from exc

    rel_map: dict[str, str] = {}
    rel_path = "xl/_rels/workbook.xml.rels"
    if rel_path in archive.namelist():
        try:
            rel_root = ET.fromstring(archive.read(rel_path))
            for rel in rel_root.findall("rels:Relationship", _XLSX_NS):
                rid = str(rel.attrib.get("Id", "")).strip()
                target = str(rel.attrib.get("Target", "")).strip()
                if rid and target:
                    clean = target.replace("\\", "/")
                    if clean.startswith("/"):
                        clean = clean.lstrip("/")
                    if not clean.startswith("xl/"):
                        clean = f"xl/{clean.lstrip('./')}"
                    rel_map[rid] = clean
        except Exception:
            rel_map = {}

    sheets: list[tuple[str, str]] = []
    for sheet in workbook_root.findall("main:sheets/main:sheet", _XLSX_NS):
        name = str(sheet.attrib.get("name", "")).strip() or "Sheet"
        rel_id = str(sheet.attrib.get(f"{{{_XLSX_NS['r']}}}id", "")).strip()
        target = rel_map.get(rel_id, "")
        if not target:
            sheet_id = str(sheet.attrib.get("sheetId", "")).strip()
            if sheet_id:
                target = f"xl/worksheets/sheet{sheet_id}.xml"
        if target:
            sheets.append((name, target))
    return sheets


def _xlsx_sheet_rows(
    archive: zipfile.ZipFile,
    path: str,
    shared_strings: list[str],
) -> tuple[list[list[str]], bool]:
    if path not in archive.namelist():
        return [], False
    try:
        root = ET.fromstring(archive.read(path))
    except Exception:
        return [], False

    rows: list[list[str]] = []
    truncated = False
    sheet_data = root.find("main:sheetData", _XLSX_NS)
    if sheet_data is None:
        return rows, truncated
    for idx, row_el in enumerate(sheet_data.findall("main:row", _XLSX_NS)):
        if idx >= MAX_TABLE_SCAN_ROWS:
            truncated = True
            break
        current: list[str] = []
        for cell in row_el.findall("main:c", _XLSX_NS):
            ref = str(cell.attrib.get("r", "")).strip()
            col_index = _xlsx_col_index(ref)
            value = _xlsx_cell_value(cell, shared_strings)
            if col_index >= len(current):
                current.extend([""] * (col_index - len(current) + 1))
            current[col_index] = value
        while current and not str(current[-1]).strip():
            current.pop()
        rows.append(current)
    return rows, truncated


def _xlsx_col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in str(cell_ref or "") if ch.isalpha()).upper()
    if not letters:
        return 0
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return max(0, idx - 1)


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = str(cell.attrib.get("t", "")).strip()
    if cell_type == "inlineStr":
        values = [t.text or "" for t in cell.findall(".//main:t", _XLSX_NS)]
        return "".join(values).strip()
    value_node = cell.find("main:v", _XLSX_NS)
    raw = str(value_node.text if value_node is not None else "").strip()
    if cell_type == "s":
        try:
            idx = int(raw)
            return str(shared_strings[idx]) if 0 <= idx < len(shared_strings) else raw
        except (TypeError, ValueError):
            return raw
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw


def _extract_pdf_text(content: bytes) -> str:
    snippets: list[str] = []
    seen: set[str] = set()

    def _collect(blob: bytes) -> None:
        for match in re.finditer(rb"\((?:\\.|[^\\()]){1,220}\)", blob):
            raw = match.group(0)[1:-1]
            text = _decode_pdf_literal(raw)
            clean = re.sub(r"\s+", " ", text).strip()
            if len(clean) < 3:
                continue
            key = clean.casefold()
            if key in seen:
                continue
            seen.add(key)
            snippets.append(clean)
            if sum(len(part) for part in snippets) >= MAX_TEXT_EXCERPT_CHARS:
                return

    _collect(content)
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", content, flags=re.DOTALL):
        chunk = match.group(1)
        if len(chunk) > MAX_PDF_STREAM_BYTES:
            continue
        try:
            decoded = zlib.decompress(chunk)
        except Exception:
            continue
        _collect(decoded)
        if sum(len(part) for part in snippets) >= MAX_TEXT_EXCERPT_CHARS:
            break

    joined = " ".join(snippets).strip()
    if not joined:
        ascii_text = re.sub(r"\s+", " ", content.decode("latin-1", errors="ignore"))
        printable = "".join(ch for ch in ascii_text if 31 < ord(ch) < 127)
        joined = printable[:MAX_TEXT_EXCERPT_CHARS].strip()
    return joined[:MAX_TEXT_EXCERPT_CHARS]


def _decode_pdf_literal(raw: bytes) -> str:
    out = bytearray()
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == 92:  # backslash
            i += 1
            if i >= len(raw):
                break
            esc = raw[i]
            mapping = {
                ord("n"): b"\n",
                ord("r"): b"\r",
                ord("t"): b"\t",
                ord("b"): b"\b",
                ord("f"): b"\f",
                ord("("): b"(",
                ord(")"): b")",
                ord("\\"): b"\\",
            }
            if esc in mapping:
                out.extend(mapping[esc])
            elif 48 <= esc <= 55:
                octal = bytes([esc])
                for _ in range(2):
                    if i + 1 < len(raw) and 48 <= raw[i + 1] <= 55:
                        i += 1
                        octal += bytes([raw[i]])
                    else:
                        break
                try:
                    out.append(int(octal, 8))
                except ValueError:
                    pass
            else:
                out.append(esc)
        else:
            out.append(ch)
        i += 1
    return out.decode("utf-8", errors="replace")


def _extract_keywords(text: str, *, limit: int = 8) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", str(text or "").casefold())
    counts: dict[str, int] = {}
    for word in words:
        if word in _KEYWORD_STOPWORDS:
            continue
        counts[word] = counts.get(word, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
    return [word for word, _freq in ordered[: max(1, min(limit, 30))]]


def _build_pdf_content_brief(text_excerpt: str, keywords: list[str], *, page_count: int) -> str:
    excerpt = str(text_excerpt or "").strip()
    if not excerpt:
        if keywords:
            return (
                f"This PDF has around {page_count} page markers and appears related to: "
                f"{', '.join(keywords[:6])}."
            )
        return (
            "This PDF structure was detected, but no reliable text excerpt could be extracted. "
            "If this is a scanned PDF, OCR is required for deeper content understanding."
        )
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", excerpt) if part.strip()]
    lead = sentences[0][:260] if sentences else excerpt[:260]
    if keywords:
        return (
            f"This PDF appears to discuss {', '.join(keywords[:6])}. "
            f"Key passage: {lead}"
        )[:MAX_TEXT_EXCERPT_CHARS]
    return f"This PDF content appears to be: {lead}"[:MAX_TEXT_EXCERPT_CHARS]


def _detect_image_format(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xFF\xD8\xFF"):
        return "jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if content.startswith(b"BM"):
        return "bmp"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "webp"
    return ""


def _image_dimensions(fmt: str, content: bytes) -> tuple[int | None, int | None]:
    if fmt == "png":
        if len(content) >= 24:
            try:
                width, height = struct.unpack(">II", content[16:24])
                return int(width), int(height)
            except struct.error:
                return None, None
    if fmt == "gif":
        if len(content) >= 10:
            try:
                width, height = struct.unpack("<HH", content[6:10])
                return int(width), int(height)
            except struct.error:
                return None, None
    if fmt == "bmp":
        if len(content) >= 26:
            try:
                width, height = struct.unpack("<ii", content[18:26])
                return abs(int(width)), abs(int(height))
            except struct.error:
                return None, None
    if fmt == "jpeg":
        return _jpeg_dimensions(content)
    if fmt == "webp":
        return _webp_dimensions(content)
    return None, None


def _jpeg_dimensions(content: bytes) -> tuple[int | None, int | None]:
    if len(content) < 4 or not content.startswith(b"\xFF\xD8"):
        return None, None
    idx = 2
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while idx + 8 < len(content):
        if content[idx] != 0xFF:
            idx += 1
            continue
        marker = content[idx + 1]
        idx += 2
        if marker in {0xD8, 0xD9}:
            continue
        if idx + 2 > len(content):
            break
        length = struct.unpack(">H", content[idx : idx + 2])[0]
        if length < 2 or idx + length > len(content):
            break
        if marker in sof_markers and idx + 7 <= len(content):
            try:
                height, width = struct.unpack(">HH", content[idx + 3 : idx + 7])
                return int(width), int(height)
            except struct.error:
                return None, None
        idx += length
    return None, None


def _webp_dimensions(content: bytes) -> tuple[int | None, int | None]:
    if len(content) < 30 or not (content.startswith(b"RIFF") and content[8:12] == b"WEBP"):
        return None, None
    chunk = content[12:16]
    if chunk == b"VP8X" and len(content) >= 30:
        width = 1 + int.from_bytes(content[24:27], "little")
        height = 1 + int.from_bytes(content[27:30], "little")
        return int(width), int(height)
    if chunk == b"VP8L" and len(content) >= 25:
        b0, b1, b2, b3 = content[21], content[22], content[23], content[24]
        width = 1 + (((b1 & 0x3F) << 8) | b0)
        height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        return int(width), int(height)
    if chunk == b"VP8 " and len(content) >= 30:
        try:
            width = struct.unpack("<H", content[26:28])[0] & 0x3FFF
            height = struct.unpack("<H", content[28:30])[0] & 0x3FFF
            return int(width), int(height)
        except struct.error:
            return None, None
    return None, None


def _extract_image_text_hints(fmt: str, content: bytes) -> list[str]:
    hints: list[str] = []
    if fmt == "png":
        hints.extend(_extract_png_text_chunks(content))
    elif fmt == "jpeg":
        hints.extend(_extract_jpeg_text_chunks(content))
    elif fmt == "webp":
        hints.extend(_extract_webp_text_chunks(content))
    deduped: list[str] = []
    seen: set[str] = set()
    for row in hints:
        clean = re.sub(r"\s+", " ", str(row or "")).strip()
        if len(clean) < 3:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(clean)
        if len(deduped) >= MAX_PROFILE_VALUES:
            break
    return deduped


def _extract_png_text_chunks(content: bytes) -> list[str]:
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        return []
    idx = 8
    rows: list[str] = []
    while idx + 12 <= len(content):
        try:
            chunk_len = struct.unpack(">I", content[idx : idx + 4])[0]
        except struct.error:
            break
        chunk_type = content[idx + 4 : idx + 8]
        data_start = idx + 8
        data_end = data_start + chunk_len
        if data_end + 4 > len(content):
            break
        chunk_data = content[data_start:data_end]
        if chunk_type == b"tEXt":
            rows.extend(_decode_png_text_chunk(chunk_data))
        elif chunk_type == b"zTXt":
            rows.extend(_decode_png_ztxt_chunk(chunk_data))
        elif chunk_type == b"iTXt":
            rows.extend(_decode_png_itxt_chunk(chunk_data))
        idx = data_end + 4
        if chunk_type == b"IEND":
            break
    return rows


def _decode_png_text_chunk(data: bytes) -> list[str]:
    try:
        key, value = data.split(b"\x00", 1)
    except ValueError:
        return []
    key_text = key.decode("latin-1", errors="ignore").strip()
    value_text = value.decode("utf-8", errors="replace").strip()
    if key_text and value_text:
        return [f"{key_text}: {value_text}"]
    if value_text:
        return [value_text]
    return []


def _decode_png_ztxt_chunk(data: bytes) -> list[str]:
    try:
        key, remainder = data.split(b"\x00", 1)
    except ValueError:
        return []
    if len(remainder) < 2:
        return []
    compressed = remainder[1:]
    try:
        value = zlib.decompress(compressed).decode("utf-8", errors="replace").strip()
    except Exception:
        return []
    key_text = key.decode("latin-1", errors="ignore").strip()
    if key_text and value:
        return [f"{key_text}: {value}"]
    if value:
        return [value]
    return []


def _decode_png_itxt_chunk(data: bytes) -> list[str]:
    parts = data.split(b"\x00", 5)
    if len(parts) < 6:
        return []
    key = parts[0].decode("utf-8", errors="replace").strip()
    text_raw = parts[5]
    try:
        value = text_raw.decode("utf-8", errors="replace").strip()
    except Exception:
        value = ""
    if key and value:
        return [f"{key}: {value}"]
    if value:
        return [value]
    return []


def _extract_jpeg_text_chunks(content: bytes) -> list[str]:
    if len(content) < 4 or not content.startswith(b"\xFF\xD8"):
        return []
    idx = 2
    rows: list[str] = []
    while idx + 4 <= len(content):
        if content[idx] != 0xFF:
            idx += 1
            continue
        marker = content[idx + 1]
        idx += 2
        if marker in {0xD8, 0xD9}:
            continue
        if idx + 2 > len(content):
            break
        seg_len = struct.unpack(">H", content[idx : idx + 2])[0]
        if seg_len < 2 or idx + seg_len > len(content):
            break
        seg_data = content[idx + 2 : idx + seg_len]
        if marker == 0xFE:  # COM
            comment = seg_data.decode("latin-1", errors="replace").strip()
            if comment:
                rows.append(comment)
        elif marker in {0xE1, 0xED}:  # APP1/APP13
            text = seg_data.decode("latin-1", errors="ignore")
            rows.extend(_extract_embedded_metadata_text(text))
        idx += seg_len
    return rows


def _extract_webp_text_chunks(content: bytes) -> list[str]:
    text = content.decode("latin-1", errors="ignore")
    return _extract_embedded_metadata_text(text)


def _extract_embedded_metadata_text(text: str) -> list[str]:
    rows: list[str] = []
    patterns = [
        r"(?:description|caption|title|imagedescription)\s*[:=]\s*([^\n\r<]{3,180})",
        r"<dc:title>\s*([^<]{3,180})\s*</dc:title>",
        r"<dc:description>\s*([^<]{3,180})\s*</dc:description>",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = re.sub(r"\s+", " ", str(match.group(1) or "")).strip()
            if value:
                rows.append(value)
    return rows


def _filename_subject_hint(file_name: str) -> str:
    stem = Path(str(file_name or "")).stem.casefold()
    tokens = [tok for tok in re.split(r"[_\-\s]+", stem) if tok]
    blocked = {"img", "image", "photo", "picture", "scan", "file", "upload", "screenshot", "doc"}
    useful = [tok for tok in tokens if tok not in blocked and len(tok) >= 3]
    if not useful:
        return ""
    return " ".join(useful[:5])


def _build_image_content_brief(
    *,
    format_name: str,
    width: int | None,
    height: int | None,
    file_name: str,
    text_hints: list[str],
) -> str:
    orientation = "unknown orientation"
    if width and height:
        if width > height:
            orientation = "landscape"
        elif height > width:
            orientation = "portrait"
        else:
            orientation = "square"
    base = f"This image is a {orientation} {format_name.upper()} file"
    if width and height:
        base += f" with dimensions {width} x {height}."
    else:
        base += "."
    if text_hints:
        hint_preview = "; ".join(text_hints[:3])
        return f"{base} Embedded text hints suggest: {hint_preview}."[:MAX_TEXT_EXCERPT_CHARS]
    subject_hint = _filename_subject_hint(file_name)
    if subject_hint:
        return (
            f"{base} Filename hints suggest the subject may relate to '{subject_hint}'. "
            "No OCR scene text was extracted."
        )[:MAX_TEXT_EXCERPT_CHARS]
    return (
        f"{base} No embedded caption text was found. For scene-level object details, connect an OCR/vision model."
    )[:MAX_TEXT_EXCERPT_CHARS]


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]{2,}", str(text or "").casefold())
    stopwords = {"the", "and", "for", "with", "that", "this", "from", "into", "what", "which", "where", "when"}
    return [tok for tok in tokens if tok not in stopwords]


def _score_tokens(tokens: list[str], text: str) -> int:
    lowered = str(text or "").casefold()
    score = 0
    for token in tokens:
        if token and token in lowered:
            score += 1
    return score


def _best_matching_sample_row(sample_rows: list[dict[str, Any]], tokens: list[str]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for idx, row in enumerate(sample_rows, start=1):
        if not isinstance(row, dict):
            continue
        rendered = " ".join(str(value) for value in row.values())
        score = _score_tokens(tokens, rendered)
        if score <= 0:
            continue
        candidate = {"row_index": idx, "row": {str(k): str(v) for k, v in row.items()}, "score": score}
        if best is None or int(candidate["score"]) > int(best["score"]):
            best = candidate
    return best


def _best_matching_sentence(excerpt: str, tokens: list[str]) -> str:
    parts = re.split(r"(?<=[.!?])\s+|\n+", str(excerpt or "").strip())
    parts = [part.strip() for part in parts if part.strip()]
    if not parts:
        return str(excerpt or "").strip()[:260]
    best = parts[0]
    best_score = _score_tokens(tokens, best)
    for part in parts[1:]:
        score = _score_tokens(tokens, part)
        if score > best_score:
            best = part
            best_score = score
    return best[:320]
