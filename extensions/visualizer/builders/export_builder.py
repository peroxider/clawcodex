"""Export builder (F-91-C / F-92-C).

Handles export to PNG/SVG/JSON/PDF formats.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from typing import Any
from xml.sax.saxutils import escape

from ..models.viz_models import ComparisonResult, ExportFormat, SessionVizData

logger = logging.getLogger(__name__)


class ExportBuilder:
    """Build export payloads for various formats."""

    def export_session(self, session: SessionVizData, fmt: ExportFormat) -> tuple[bytes, str, str]:
        """Export a session to the given format.

        Returns (content_bytes, mime_type, filename).
        """
        if fmt == ExportFormat.JSON:
            return self._export_json(session)
        if fmt == ExportFormat.SVG:
            return self._export_svg(session)
        if fmt == ExportFormat.PNG:
            return self._export_png(session)
        if fmt == ExportFormat.PDF:
            return self._export_pdf(session)
        return self._export_json(session)

    def export_comparison(
        self, comparison: ComparisonResult, fmt: ExportFormat
    ) -> tuple[bytes, str, str]:
        """Export a comparison to the given format."""
        if fmt == ExportFormat.JSON:
            data = comparison.model_dump_json(indent=2).encode("utf-8")
            return data, "application/json", "comparison.json"
        if fmt == ExportFormat.PDF:
            return self._comparison_pdf(comparison)
        # Fallback to JSON
        data = comparison.model_dump_json(indent=2).encode("utf-8")
        return data, "application/json", "comparison.json"

    def _export_json(self, session: SessionVizData) -> tuple[bytes, str, str]:
        data = session.model_dump_json(indent=2).encode("utf-8")
        return data, "application/json", f"{session.session_id}.json"

    def _export_svg(self, session: SessionVizData) -> tuple[bytes, str, str]:
        """Generate a simple SVG representation of the timeline."""
        bars = session.timeline
        if not bars:
            svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="100">'
                '<rect width="100%" height="100%" fill="#11162a"/>'
                '<text x="10" y="50" font-size="14" font-family="sans-serif" fill="#d7defa">'
                "No timeline data</text></svg>"
            )
            return svg.encode("utf-8"), "image/svg+xml", f"{session.session_id}.svg"

        width = 1200
        row_height = 30
        header_height = 40
        chart_height = max(len(bars) * row_height + header_height, 200)

        base_time = min(b.start_time for b in bars)
        total_span = max(b.end_time for b in bars) - base_time
        if total_span <= 0:
            total_span = 1

        title = escape(session.title or session.session_id[:8])
        svg_parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{chart_height}">',
            '<rect width="100%" height="100%" fill="#11162a"/>',
            '<rect x="6" y="6" width="1188" height="28" fill="#17213d" opacity="0.92" rx="4"/>',
            f'<text x="14" y="25" font-size="16" font-family="sans-serif" fill="#eef3ff">Session: {title}</text>',
        ]

        colors = {
            "tool_call": "#91cc75",
            "llm_call": "#5470c6",
            "phase": "#ee6666",
            "custom": "#9a60b4",
        }
        for i, bar in enumerate(bars):
            y = header_height + i * row_height
            x = 10 + int((bar.start_time - base_time) / total_span * (width - 20))
            w = max(2, int(bar.duration_ms / 1000 / total_span * (width - 20)))
            color = colors.get(bar.type.value, "#9a60b4")
            svg_parts.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{row_height - 4}" '
                f'fill="{color}" opacity="0.8" rx="3"/>'
            )
            svg_parts.append(
                f'<text x="{x + 4}" y="{y + row_height - 10}" font-size="10" '
                f'font-family="sans-serif" fill="#ffffff">{escape(bar.label[:20])}</text>'
            )

        svg_parts.append("</svg>")
        svg = "\n".join(svg_parts)
        return svg.encode("utf-8"), "image/svg+xml", f"{session.session_id}.svg"

    def _export_png(self, session: SessionVizData) -> tuple[bytes, str, str]:
        """Best-effort PNG export via Pillow if available."""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            logger.warning("Pillow not installed; falling back to SVG→PNG placeholder")
            return self._export_svg(session)

        bars = session.timeline
        if not bars:
            img = Image.new("RGB", (800, 100), "#f8f9fa")
            return self._img_to_png(img), "image/png", f"{session.session_id}.png"

        width = 1200
        row_height = 30
        header_height = 40
        chart_height = max(len(bars) * row_height + header_height, 200)

        img = Image.new("RGB", (width, chart_height), "#f8f9fa")
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
            header_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except Exception:
            font = ImageFont.load_default()
            header_font = font

        draw.text(
            (10, 10),
            f"Session: {session.title or session.session_id[:8]}",
            fill="#333333",
            font=header_font,
        )

        base_time = bars[0].start_time
        total_span = max(b.end_time for b in bars) - base_time
        if total_span <= 0:
            total_span = 1

        colors = {
            "tool_call": "#91cc75",
            "llm_call": "#5470c6",
            "phase": "#ee6666",
            "custom": "#9a60b4",
        }
        for i, bar in enumerate(bars):
            y = header_height + i * row_height
            x = 10 + int((bar.start_time - base_time) / total_span * (width - 20))
            w = max(2, int(bar.duration_ms / 1000 / total_span * (width - 20)))
            color = colors.get(bar.type.value, "#9a60b4")
            # Convert hex to RGB
            rgb = tuple(int(color[j : j + 2], 16) for j in (1, 3, 5))
            draw.rectangle([x, y, x + w, y + row_height - 4], fill=rgb)
            draw.text((x + 4, y + 4), bar.label[:20], fill="#ffffff", font=font)

        return self._img_to_png(img), "image/png", f"{session.session_id}.png"

    def _img_to_png(self, img: Any) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _export_pdf(self, session: SessionVizData) -> tuple[bytes, str, str]:
        """Best-effort PDF export. Falls back to HTML→PDF if reportlab unavailable."""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
        except ImportError:
            logger.warning("reportlab not installed; returning SVG as PDF placeholder")
            data, _, _ = self._export_svg(session)
            return data, "application/pdf", f"{session.session_id}.pdf"

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        width, height = letter

        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height - 50, f"Session Report: {session.title or session.session_id}")

        c.setFont("Helvetica", 12)
        y = height - 80
        c.drawString(50, y, f"Status: {session.status}")
        y -= 20
        c.drawString(50, y, f"Duration: {session.duration_ms / 1000:.1f}s")
        y -= 20
        c.drawString(50, y, f"Turns: {session.turn_count} | Tools: {session.tool_count}")
        y -= 20
        c.drawString(50, y, f"Cost: ${session.stats.cost_usd:.4f}")

        if session.anomalies:
            y -= 40
            c.setFont("Helvetica-Bold", 14)
            c.drawString(50, y, "Anomalies")
            c.setFont("Helvetica", 10)
            for anomaly in session.anomalies:
                y -= 15
                if y < 50:
                    c.showPage()
                    y = height - 50
                c.drawString(
                    50,
                    y,
                    f"[{anomaly.severity.value}] {anomaly.type.value}: {anomaly.description[:80]}",
                )

        c.save()
        return buf.getvalue(), "application/pdf", f"{session.session_id}.pdf"

    def _comparison_pdf(self, comparison: ComparisonResult) -> tuple[bytes, str, str]:
        """Generate a PDF comparison report."""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
        except ImportError:
            data = comparison.model_dump_json(indent=2).encode("utf-8")
            return data, "application/json", "comparison.json"

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        width, height = letter

        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height - 50, "Cross-Session Comparison Report")

        c.setFont("Helvetica", 12)
        y = height - 80
        metrics = comparison.common_metrics
        for key, value in metrics.items():
            c.drawString(50, y, f"{key}: {value}")
            y -= 20

        c.save()
        return buf.getvalue(), "application/pdf", "comparison.pdf"
