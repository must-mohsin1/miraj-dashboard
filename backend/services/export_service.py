"""Export service — generate CSV and PDF reports from analysis results."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Optional

from fpdf import FPDF


def _sanitize(text: object) -> str:
    """Convert *text* to a Latin-1-safe string for fpdf2 core fonts.

    Replaces or strips characters that Helvetica can't render.
    """
    s = str(text) if text is not None else ""
    # Replace common Unicode characters with ASCII equivalents
    s = s.replace("\u2014", "--")  # em dash
    s = s.replace("\u2013", "-")   # en dash
    s = s.replace("\u2018", "'")  # left single quote
    s = s.replace("\u2019", "'")  # right single quote
    s = s.replace("\u201c", '"')  # left double quote
    s = s.replace("\u201d", '"')  # right double quote
    s = s.replace("\u2026", "...")  # ellipsis
    s = s.replace("\u2022", "-")   # bullet
    s = s.replace("\u25cf", "*")   # black circle
    s = s.replace("\u25cb", "o")   # white circle
    s = s.replace("\u2605", "*")   # star
    s = s.replace("\u2713", "v")   # check mark
    s = s.replace("\u2714", "v")   # heavy check mark
    s = s.replace("\u2716", "x")   # heavy multiplication x
    s = s.replace("\u2192", "->")  # right arrow
    s = s.replace("\u2190", "<-")  # left arrow
    s = s.replace("\u2191", "^")   # up arrow
    s = s.replace("\u2193", "v")   # down arrow
    # Strip or replace any remaining character outside Latin-1
    return s.encode("latin-1", errors="replace").decode("latin-1")


# ── PDF styling constants ─────────────────────────────────────────────────

_PAGE_W = 210  # A4 width, mm
_MARGIN = 15
_BODY_W = _PAGE_W - 2 * _MARGIN  # 180mm

_COLOR_PRIMARY = (30, 64, 175)  # dark blue
_COLOR_SECONDARY = (59, 130, 246)  # medium blue
_COLOR_BG = (243, 244, 246)  # light gray
_COLOR_TEXT = (31, 41, 55)  # near-black
_COLOR_MUTED = (107, 114, 128)  # gray-500


# ── Public API ─────────────────────────────────────────────────────────────


def generate_csv(result: dict[str, Any]) -> str:
    """Generate a CSV string from *result* data.

    The output has two columns: **Field** and **Value**, one row per
    data point.  Nested dicts and lists are shown as JSON to keep the
    format flat and readable.
    """
    import json as _json

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Field", "Value"])

    rows: list[tuple[str, Any]] = [
        ("Symbol", result.get("symbol")),
        ("Overall Score", result.get("overall_score")),
        ("Confluence Score", result.get("confluence_score")),
        ("Timestamp (UTC)", datetime.now(timezone.utc).isoformat()),
    ]

    # Trade plan (flat)
    tp_flat = result.get("trade_plan_flat") or {}
    for key in ("direction", "entry", "stop_loss", "target_1", "target_2", "target_3"):
        val = tp_flat.get(key)
        if val is not None:
            rows.append((f"Trade Plan — {key.replace('_', ' ').title()}", val))

    # Score breakdown
    scores = result.get("scores") or {}
    for cat, score in scores.items():
        rows.append((f"Score — {cat.replace('_', ' ').title()}", score))

    # Score sub-breakdowns
    sb = result.get("score_breakdown") or {}
    for cat, data in sb.items():
        if isinstance(data, dict):
            sub = data.get("score") or data.get("sub_score")
            if sub is not None:
                rows.append((f"Breakdown — {cat.replace('_', ' ').title()}", sub))

    # Macro data
    macro = result.get("macro_data") or {}
    for mk, mv in macro.items():
        if mv is not None:
            rows.append((f"Macro — {mk}", mv))

    # SMC (compact)
    smc = result.get("smc") or {}
    ob_count = len(smc.get("order_blocks", [])) if isinstance(smc, dict) else 0
    fvg_count = len(smc.get("fvgs", [])) if isinstance(smc, dict) else 0
    lg_count = len(smc.get("liquidity_grabs", [])) if isinstance(smc, dict) else 0
    rows.append(("SMC — Order Blocks", ob_count))
    rows.append(("SMC — FVGs", fvg_count))
    rows.append(("SMC — Liquidity Grabs", lg_count))

    # Patterns
    patterns = result.get("patterns") or {}
    if isinstance(patterns, dict):
        detected = patterns.get("detected", [])
        rows.append(("Patterns — Count", len(detected)))
        for i, p in enumerate(detected[:5], 1):
            rows.append((f"Pattern {i}", _json.dumps(p)))

    # QQE
    qqe = result.get("qqe") or {}
    if isinstance(qqe, dict):
        for tf, sig in qqe.items():
            if isinstance(sig, dict):
                rows.append((f"QQE — {tf}", sig.get("signal", "-")))

    # Staleness
    rows.append(("Stale", result.get("stale", False)))
    rows.append(("Cached At", result.get("cached_at", "")))

    for field, value in rows:
        display = str(value) if value is not None else ""
        writer.writerow([field, display])

    return output.getvalue()


def generate_pdf(result: dict[str, Any]) -> bytes:
    """Generate a PDF report (bytes) from *result* data."""
    pdf = _ReportPDF()
    pdf.add_page()
    pdf._header_block(result)
    pdf._score_section(result)
    pdf._trade_plan_section(result)
    pdf._breakdown_section(result)
    pdf._macro_section(result)
    pdf._technical_section(result)
    return pdf.output_bytes()


# ── Internal PDF builder ───────────────────────────────────────────────────


class _ReportPDF(FPDF):  # type: ignore[misc]
    """Minimal PDF report for a single analysis result."""

    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=20)

    def output_bytes(self) -> bytes:
        """Return the PDF as a ``bytes`` object."""
        return bytes(self.output())

    # ── helpers ───────────────────────────────────────────────────────

    def _section_title(self, title: str) -> None:
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*_COLOR_PRIMARY)
        self.cell(0, 8, _sanitize(title), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*_COLOR_SECONDARY)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def _kv_row(
        self,
        key: str,
        value: object,
        bold_key: bool = True,
        value_color: tuple[int, int, int] | None = None,
    ) -> None:
        self.set_font("Helvetica", "B" if bold_key else "", 10)
        self.set_text_color(*_COLOR_TEXT)
        sk = _sanitize(key + "  ")
        kw = self.get_string_width(sk)
        self.cell(kw, 6, sk)
        self.set_font("Helvetica", "", 10)
        if value_color:
            self.set_text_color(*value_color)
        else:
            self.set_text_color(*_COLOR_MUTED)
        self.cell(_BODY_W - kw, 6, _sanitize(value), new_x="LMARGIN", new_y="NEXT")

    def _section_spacer(self) -> None:
        self.ln(3)

    # ── sections ──────────────────────────────────────────────────────

    def _header_block(self, result: dict[str, Any]) -> None:
        # Title bar
        self.set_fill_color(*_COLOR_PRIMARY)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 18)
        self.cell(0, 14, _sanitize("  Analysis Report"), fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(6)

        sym = _sanitize(result.get("symbol", "-"))
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.set_font("Helvetica", "", 11)
        self.set_text_color(*_COLOR_TEXT)
        self.cell(0, 6, f"Symbol:  {sym}", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*_COLOR_MUTED)
        self.cell(0, 6, _sanitize(f"Generated:  {now}"), new_x="LMARGIN", new_y="NEXT")
        self.ln(4)

    def _score_section(self, result: dict[str, Any]) -> None:
        self._section_title("Score Overview")

        overall = result.get("overall_score")
        confluence = result.get("confluence_score")
        self._kv_row("Overall Score", f"{overall:.0f}/100" if overall is not None else "-")
        self._kv_row("Confluence Score", f"{confluence:.1f}/30" if confluence is not None else "-")

        scores = result.get("scores") or {}
        for cat, val in scores.items():
            label = cat.replace("_", " ").title()
            self._kv_row(f"  {label}", f"{val:.1f}")

        self._section_spacer()

    def _trade_plan_section(self, result: dict[str, Any]) -> None:
        self._section_title("Trade Plan")

        tp_flat = result.get("trade_plan_flat") or {}
        direction = tp_flat.get("direction", "-")
        self._kv_row("Direction", direction)
        self._kv_row("Entry Price", self._fmt_price(tp_flat.get("entry")))

        sl = tp_flat.get("stop_loss")
        if sl is not None:
            self._kv_row("Stop Loss", self._fmt_price(sl), value_color=(220, 38, 38))
        else:
            self._kv_row("Stop Loss", "-")

        for i, key in enumerate(("target_1", "target_2", "target_3"), 1):
            tgt = tp_flat.get(key)
            if tgt is not None:
                self._kv_row(f"  Target {i}", self._fmt_price(tgt), value_color=(22, 163, 74))

        rationale = tp_flat.get("rationale")
        if rationale:
            self._section_spacer()
            self.set_font("Helvetica", "I", 10)
            self.set_text_color(*_COLOR_TEXT)
            self.multi_cell(0, 5, _sanitize(f"Rationale: {rationale}"))

        self._section_spacer()

    def _breakdown_section(self, result: dict[str, Any]) -> None:
        sb = result.get("score_breakdown") or {}
        if not sb:
            return

        self._section_title("Score Breakdown")
        for cat, data in sb.items():
            if isinstance(data, dict):
                label = cat.replace("_", " ").title()
                score = data.get("score", "-")
                details = data.get("details") or data.get("reasoning", "")
                self._kv_row(label, str(score))
                if details:
                    self.set_font("Helvetica", "", 9)
                    self.set_text_color(*_COLOR_MUTED)
                    self.multi_cell(0, 4, _sanitize(f"    {details}"))
        self._section_spacer()

    def _macro_section(self, result: dict[str, Any]) -> None:
        macro = result.get("macro_data") or {}
        if not macro:
            return

        self._section_title("Macro Context")
        labels = {
            "btc_d": "BTC Dominance",
            "usdt_d": "USDT Dominance",
            "dxy": "DXY",
            "fear_greed": "Fear & Greed",
            "long_short_ratio_btc": "Long/Short Ratio (BTC)",
        }
        for key, label in labels.items():
            val = macro.get(key)
            if isinstance(val, dict):
                v = val.get("value") or val.get("score") or str(val)
            elif val is not None:
                v = str(val)
            else:
                v = "-"
            self._kv_row(label, v)
        self._section_spacer()

    def _technical_section(self, result: dict[str, Any]) -> None:
        self._section_title("Technical Analysis")

        # SMC
        smc = result.get("smc") or {}
        if isinstance(smc, dict):
            self._kv_row(
                "Order Blocks",
                str(len(smc.get("order_blocks", []))),
            )
            self._kv_row("FVGs", str(len(smc.get("fvgs", []))))
            self._kv_row("Liquidity Grabs", str(len(smc.get("liquidity_grabs", []))))

        # Patterns
        patterns = result.get("patterns") or {}
        if isinstance(patterns, dict):
            detected = patterns.get("detected", [])
            self._kv_row("Patterns Found", str(len(detected)))
            for p in detected[:3]:
                name = p.get("pattern", p.get("name", "Unknown"))
                conf = p.get("confidence", "")
                self._kv_row(f"  {name}", str(conf) if conf else "Detected")

        # QQE signals
        qqe = result.get("qqe") or {}
        if isinstance(qqe, dict):
            for tf, sig in qqe.items():
                if isinstance(sig, dict):
                    self._kv_row(f"QQE ({tf})", str(sig.get("signal", "-")))

        self._section_spacer()

    @staticmethod
    def _fmt_price(value: Any) -> str:
        if value is None:
            return "-"
        try:
            v = float(value)
            return f"${v:,.2f}" if v >= 1000 else f"${v:.2f}"
        except (ValueError, TypeError):
            return str(value)
