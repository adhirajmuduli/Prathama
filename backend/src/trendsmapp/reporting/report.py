"""Deterministic PDF report rendering for a finished run.

The report is a publication-grade summary of one run: cover with all hashes,
the methods record, result tables, embedded figure rasters, an ML section
(comparison table, uncertainty coverage, importance and prediction charts
rendered with matplotlib and embedded as PNG), and a checksum appendix listing
every artifact in the export bundle. Output is byte-stable for the same
inputs (fixed fonts, no wall-clock values beyond the manifest's generated_at).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

__all__ = ["REPORT_SCHEMA_VERSION", "build_report_pdf"]

REPORT_SCHEMA_VERSION = "1.0.0"

_PAGE = A4
_MARGIN = 2 * cm


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=22, spaceAfter=12),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontSize=15, spaceBefore=14, spaceAfter=8
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=6
        ),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontSize=9.5, leading=13),
        "mono": ParagraphStyle(
            "mono", parent=base["Code"], fontName="Courier", fontSize=8, leading=11
        ),
    }


def _csv_rows(payload: bytes, max_rows: int = 200) -> list[list[str]]:
    """Parse a CSV table into string rows for a PDF table."""
    text = payload.decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    return [rows[0], *rows[1 : 1 + max_rows]]


def _pdf_table(rows: Sequence[Sequence[str]], col_widths: Sequence[float] | None = None) -> Table:
    """Render CSV rows as a styled reportlab table."""
    data = [[str(cell) for cell in row] for row in rows]
    table = Table(data, colWidths=list(col_widths) if col_widths else None, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("FONTNAME", (0, 1), (-1, -1), "Courier"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _png_figure(payload: bytes, max_width: float = 15 * cm) -> Image:
    """Embed a PNG raster scaled to the page width."""
    from PIL import Image as PILImage

    with PILImage.open(io.BytesIO(payload)) as image:
        width, height = image.size
    scale = max_width / width if width > max_width / cm * 72 else 1.0
    return Image(io.BytesIO(payload), width=width * scale, height=height * scale)


def _matplotlib_chart(kind: str, payload: Mapping[str, Any]) -> bytes:
    """Render an ML chart with matplotlib (Agg) and return PNG bytes."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(6.4, 3.2), dpi=150)
    try:
        if kind == "importance":
            rows = payload.get("rows") or []
            rows = sorted(rows, key=lambda row: -(row.get("value") or 0.0))[:12]
            names = [str(row.get("feature", "")) for row in rows][::-1]
            values = [float(row.get("value") or 0.0) for row in rows][::-1]
            axis.barh(names, values, color="#0369a1")
            axis.set_xlabel("importance (change in primary metric)")
            axis.set_title("Feature importance (held-out rows)")
        elif kind == "predictions":
            folds = payload.get("folds") or []
            truth: list[float] = []
            predicted: list[float] = []
            for fold in folds:
                truth.extend(float(v) for v in fold.get("y_true", []))
                predicted.extend(float(v) for v in fold.get("y_pred", []))
            axis.scatter(truth, predicted, s=8, alpha=0.6, color="#0369a1")
            if truth:
                low = min(truth + predicted)
                high = max(truth + predicted)
                axis.plot([low, high], [low, high], "k--", linewidth=0.8)
            axis.set_xlabel("observed")
            axis.set_ylabel("predicted (held out)")
            axis.set_title("Observed vs predicted")
        else:
            raise ValueError(f"unknown chart kind: {kind}")
        figure.tight_layout()
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png")
        return buffer.getvalue()
    finally:
        plt.close(figure)


def _kv_table(pairs: Sequence[tuple[str, str]]) -> Table:
    """Two-column key/value table for the cover page."""
    return _pdf_table([["Field", "Value"], *[[k, v] for k, v in pairs]])


def build_report_pdf(
    *,
    manifest: Mapping[str, Any],
    documents: Mapping[str, Mapping[str, Any]],
    tables: Mapping[str, bytes],
    figures: Sequence[tuple[str, bytes]],
) -> bytes:
    """Render the PDF report for one run and return its bytes.

    ``manifest`` is the export-bundle manifest; ``documents`` maps document
    roles (``metrics``, ``predictions``, ``explanations``) to parsed JSON;
    ``tables`` maps table names to CSV bytes; ``figures`` are ``(label, png)``
    pairs of raster artifacts to embed.
    """
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=_PAGE,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
        title=f"Trendsmapp report {manifest.get('run_id', '')}",
        author="Trendsmapp",
    )
    story: list[Any] = []

    story.append(Paragraph("Trendsmapp run report", styles["title"]))
    story.append(
        _kv_table(
            [
                ("Run", str(manifest.get("run_id", ""))),
                ("Report schema", REPORT_SCHEMA_VERSION),
                ("Application version", str(manifest.get("application_version", ""))),
                ("Generated at", str(manifest.get("generated_at", ""))),
                ("Dataset SHA-256", str(manifest.get("dataset_sha256", ""))[:32] + "…"),
                (
                    "Boundary SHA-256",
                    str(manifest.get("boundary_sha256") or "—")[:32]
                    + ("…" if manifest.get("boundary_sha256") else ""),
                ),
                ("Recipe SHA-256", str(manifest.get("recipe_hash", ""))[:32] + "…"),
                ("Seed", str(manifest.get("seed", ""))),
                (
                    "Reproduce",
                    str(
                        (manifest.get("reproduction") or {}).get(
                            "command", "trendsmapp reproduce <bundle.zip>"
                        )
                    ),
                ),
            ]
        )
    )
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        Paragraph(
            "Every figure, table, and number in this report is read from the run's stored, "
            "content-addressed artifacts. The appendix lists every artifact with its SHA-256.",
            styles["body"],
        )
    )

    methods = manifest.get("methods") or {}
    story.append(PageBreak())
    story.append(Paragraph("Methods", styles["h1"]))
    story.append(Paragraph(f"Seed: {manifest.get('seed')}", styles["body"]))
    spatial = methods.get("spatial") or {}
    if spatial:
        story.append(Paragraph("Spatial", styles["h2"]))
        story.append(
            Paragraph(
                f"Methods: {', '.join(str(m) for m in spatial.get('methods') or [])} — "
                f"CRS {spatial.get('analysis_crs')}, grid {spatial.get('grid_resolution_m')} m, "
                f"validation {spatial.get('validation')}.",
                styles["body"],
            )
        )
    temporal = methods.get("temporal") or {}
    if temporal:
        story.append(Paragraph("Temporal", styles["h2"]))
        story.append(
            Paragraph(
                f"Resolution {temporal.get('resolution')}, "
                f"interpolation {temporal.get('interpolation')}.",
                styles["body"],
            )
        )
    ml = methods.get("machine_learning") or {}
    if ml:
        story.append(Paragraph("Machine learning", styles["h2"]))
        story.append(
            Paragraph(
                f"Setting {ml.get('setting')}, outer split {ml.get('outer_split')}, "
                f"inner split {ml.get('inner_split')}, "
                f"candidates {', '.join(str(m) for m in ml.get('candidate_models') or [])}, "
                f"budget {ml.get('search_budget')}, "
                f"uncertainty {ml.get('uncertainty_method')}, "
                f"explanations {', '.join(str(m) for m in ml.get('explanation_methods') or [])}.",
                styles["body"],
            )
        )

    metrics = documents.get("metrics")
    story.append(Paragraph("Results", styles["h1"]))
    for name in sorted(tables):
        story.append(Paragraph(name, styles["h2"]))
        story.append(_pdf_table(_csv_rows(tables[name])))
        story.append(Spacer(1, 0.2 * cm))

    if figures:
        story.append(PageBreak())
        story.append(Paragraph("Figures", styles["h1"]))
        for label, payload in figures:
            if not payload[:8].startswith(b"\x89PNG\r\n\x1a\n"):
                continue
            story.append(Paragraph(label, styles["h2"]))
            story.append(_png_figure(payload))
            story.append(Spacer(1, 0.3 * cm))

    if isinstance(metrics, Mapping) and isinstance(metrics.get("aggregated"), dict):
        story.append(PageBreak())
        story.append(Paragraph("Model comparison", styles["h1"]))
        aggregated = metrics["aggregated"]
        rows = [["Family", "RMSE mean", "RMSE 95% CI", "MAE mean", "Baseline"]]
        baseline_comparison = metrics.get("baseline_comparison") or {}
        for family in sorted(aggregated):
            entry = aggregated[family] or {}
            ci = entry.get("rmse_ci95")
            ci_text = (
                f"[{float(ci[0]):.4f}, {float(ci[1]):.4f}]"
                if isinstance(ci, list) and len(ci) == 2
                else "—"
            )
            rows.append(
                [
                    family,
                    f"{float(entry.get('rmse_mean', 0)):.4f}",
                    ci_text,
                    f"{float(entry.get('mae_mean', 0)):.4f}",
                    "yes" if family in baseline_comparison else "—",
                ]
            )
        story.append(_pdf_table(rows))
        uncertainty = metrics.get("uncertainty") or {}
        story.append(Spacer(1, 0.3 * cm))
        story.append(
            Paragraph(
                f"Selected family: <b>{metrics.get('selected_family')}</b>. Uncertainty: "
                f"{uncertainty.get('method')} with empirical coverage "
                f"{uncertainty.get('empirical_coverage')}. Importance values are associations, "
                "not causal effects.",
                styles["body"],
            )
        )
        explanations = documents.get("explanations")
        if isinstance(explanations, Mapping) and explanations.get("rows"):
            story.append(Paragraph("Feature importance", styles["h2"]))
            story.append(_png_figure(_matplotlib_chart("importance", explanations)))
        predictions = documents.get("predictions")
        if isinstance(predictions, Mapping) and predictions.get("folds"):
            story.append(Paragraph("Held-out predictions", styles["h2"]))
            story.append(_png_figure(_matplotlib_chart("predictions", predictions)))

    artifacts = manifest.get("artifacts") or []
    if artifacts:
        story.append(PageBreak())
        story.append(Paragraph("Artifact checksums (appendix)", styles["h1"]))
        rows = [["Kind", "SHA-256", "Bytes", "Bundle path"]]
        for entry in artifacts:
            if not isinstance(entry, Mapping):
                continue
            rows.append(
                [
                    str(entry.get("kind", "")),
                    str(entry.get("sha256", ""))[:32] + "…",
                    str(entry.get("size_bytes", "")),
                    str(entry.get("bundle_path", "")),
                ]
            )
        story.append(_pdf_table(rows))

    # invariant=1 fixes the document /ID and omits timestamps, so identical
    # inputs produce byte-identical PDFs. build() passes invariant itself, so
    # only default it when absent.
    def _invariant_canvas(*args: Any, **kwargs: Any) -> pdfcanvas.Canvas:
        kwargs["invariant"] = 1  # force: build() passes its own value
        return pdfcanvas.Canvas(*args, **kwargs)

    doc.build(story, canvasmaker=_invariant_canvas)
    return buffer.getvalue()
