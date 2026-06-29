"""
Chart pattern detection using scipy.signal.find_peaks.

Detects:
- Double Top / Double Bottom
- Head and Shoulders / Inverse H&S
- Symmetrical, Ascending, Descending Triangles
- Falling Wedge / Rising Wedge
- Rounded Bottom / Rounded Top
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from scipy import stats

from mirai_core import config


def _find_peaks_config(close: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Return (peaks, troughs) indices."""
    prom = close.std() * config.PATTERN_PROMINENCE_FACTOR
    peaks, _ = find_peaks(
        close.values, distance=config.PATTERN_DISTANCE, prominence=prom
    )
    troughs, _ = find_peaks(
        -close.values, distance=config.PATTERN_DISTANCE, prominence=prom
    )
    return peaks, troughs


def detect_double_top(
    close: pd.Series,
) -> dict | None:
    """Detect Double Top pattern.

    Two peaks within DOUBLE_TOP_TOLERANCE of each other, with a trough between them.
    Bearish signal.
    """
    peaks, _ = _find_peaks_config(close)
    if len(peaks) >= 2:
        p1, p2 = float(close.iloc[peaks[-2]]), float(close.iloc[peaks[-1]])
        if abs(p1 - p2) / p1 < config.DOUBLE_TOP_TOLERANCE and p1 > 0:
            confirmed = bool(float(close.iloc[-1]) < p2)
            return {
                "pattern": "Double Top",
                "signal": "Bearish",
                "confirmed": confirmed,
                "levels": {"neck": min(p1, p2)},
            }
    return None


def detect_double_bottom(
    close: pd.Series,
) -> dict | None:
    """Detect Double Bottom pattern."""
    _, troughs = _find_peaks_config(close)
    if len(troughs) >= 2:
        t1, t2 = float(close.iloc[troughs[-2]]), float(close.iloc[troughs[-1]])
        if abs(t1 - t2) / t1 < config.DOUBLE_BOTTOM_TOLERANCE and t1 > 0:
            confirmed = bool(float(close.iloc[-1]) > t2)
            return {
                "pattern": "Double Bottom",
                "signal": "Bullish",
                "confirmed": confirmed,
                "levels": {"neck": max(t1, t2)},
            }
    return None


def detect_head_and_shoulders(
    close: pd.Series,
) -> dict | None:
    """Detect Head and Shoulders top pattern.

    3 peaks, middle highest, shoulders roughly equal.
    """
    peaks, _ = _find_peaks_config(close)
    if len(peaks) >= 3:
        v1, v2, v3 = (
            float(close.iloc[peaks[-3]]),
            float(close.iloc[peaks[-2]]),
            float(close.iloc[peaks[-1]]),
        )
        if (
            v2 > v1
            and v2 > v3
            and abs(v1 - v3) / v1 < config.HANDS_SHOULDER_EQUALITY
            and v1 > 0
        ):
            confirmed = bool(float(close.iloc[-1]) < min(v1, v3))
            return {
                "pattern": "Head and Shoulders",
                "signal": "Bearish",
                "confirmed": confirmed,
                "levels": {"neckline": min(v1, v3)},
            }
    return None


def detect_inverse_head_and_shoulders(
    close: pd.Series,
) -> dict | None:
    """Detect Inverse Head and Shoulders bottom pattern."""
    _, troughs = _find_peaks_config(close)
    if len(troughs) >= 3:
        v1, v2, v3 = (
            float(close.iloc[troughs[-3]]),
            float(close.iloc[troughs[-2]]),
            float(close.iloc[troughs[-1]]),
        )
        if (
            v2 < v1
            and v2 < v3
            and abs(v1 - v3) / v1 < config.HANDS_SHOULDER_EQUALITY
            and v1 > 0
        ):
            confirmed = bool(float(close.iloc[-1]) > max(v1, v3))
            return {
                "pattern": "Inverse H&S",
                "signal": "Bullish",
                "confirmed": confirmed,
                "levels": {"neckline": max(v1, v3)},
            }
    return None


def detect_triangles(
    close: pd.Series,
) -> list[dict]:
    """Detect triangle patterns by comparing peak and trough slopes.

    Returns list of detected triangles.
    """
    peaks, troughs = _find_peaks_config(close)
    triangles: list[dict] = []

    if len(peaks) >= 2 and len(troughs) >= 2:
        # Slope of last 2 peaks
        x_p = np.array([peaks[-2], peaks[-1]])
        y_p = np.array([float(close.iloc[peaks[-2]]), float(close.iloc[peaks[-1]])])
        # Slope of last 2 troughs
        x_t = np.array([troughs[-2], troughs[-1]])
        y_t = np.array(
            [float(close.iloc[troughs[-2]]), float(close.iloc[troughs[-1]])]
        )

        if x_p[0] != x_p[1] and x_t[0] != x_t[1]:
            peak_slope = (y_p[1] - y_p[0]) / (x_p[1] - x_p[0])
            trough_slope = (y_t[1] - y_t[0]) / (x_t[1] - x_t[0])

            # Symmetrical triangle: peaks descending, troughs ascending
            if peak_slope < 0 and trough_slope > 0:
                triangles.append(
                    {
                        "pattern": "Symmetrical Triangle",
                        "signal": "Breakout pending",
                        "confirmed": False,
                    }
                )
            # Ascending triangle: troughs rising, peaks flat/rising
            elif trough_slope > 0 and peak_slope >= 0:
                triangles.append(
                    {
                        "pattern": "Ascending Triangle",
                        "signal": "Bullish",
                        "confirmed": False,
                    }
                )
            # Descending triangle: peaks falling, troughs flat/falling
            elif peak_slope < 0 and trough_slope <= 0:
                triangles.append(
                    {
                        "pattern": "Descending Triangle",
                        "signal": "Bearish",
                        "confirmed": False,
                    }
                )

    return triangles


def detect_wedges(
    close: pd.Series,
) -> list[dict]:
    """Detect rising and falling wedges via linear regression on swing points."""
    peaks, troughs = _find_peaks_config(close)
    wedges: list[dict] = []

    if len(peaks) >= 2 and len(troughs) >= 2:
        # Peak line
        x_p = np.array([peaks[-2], peaks[-1]])
        y_p = np.array([float(close.iloc[peaks[-2]]), float(close.iloc[peaks[-1]])])
        # Trough line
        x_t = np.array([troughs[-2], troughs[-1]])
        y_t = np.array(
            [float(close.iloc[troughs[-2]]), float(close.iloc[troughs[-1]])]
        )

        if x_p[0] != x_p[1] and x_t[0] != x_t[1]:
            peak_slope = (y_p[1] - y_p[0]) / (x_p[1] - x_p[0])
            trough_slope = (y_t[1] - y_t[0]) / (x_t[1] - x_t[0])

            # Falling wedge: both slopes negative, trough slope > peak slope (converging)
            if peak_slope < 0 and trough_slope < 0 and trough_slope > peak_slope:
                wedges.append(
                    {
                        "pattern": "Falling Wedge",
                        "signal": "Bullish",
                        "confirmed": False,
                    }
                )
            # Rising wedge: both slopes positive, peak slope < trough slope (converging)
            elif peak_slope > 0 and trough_slope > 0 and peak_slope > trough_slope:
                wedges.append(
                    {
                        "pattern": "Rising Wedge",
                        "signal": "Bearish",
                        "confirmed": False,
                    }
                )

    return wedges


def detect_rounded(
    close: pd.Series,
    volume: pd.Series | None = None,
) -> list[dict]:
    """Detect rounded bottom / top via volume + price smoothness analysis."""
    patterns: list[dict] = []
    if len(close) < 30:
        return patterns

    recent = close.tail(20)
    recent_vol = volume.tail(20) if volume is not None else None

    # Check for low volatility (rounded shape)
    price_std = recent.std()

    if price_std > 0 and recent_vol is not None:
        # Volume pattern for rounded bottom: declining then rising
        vol_chunks = np.array_split(recent_vol.values, 4)
        if len(vol_chunks) == 4:
            first_half = np.mean(vol_chunks[0]) + np.mean(vol_chunks[1])
            second_half = np.mean(vol_chunks[2]) + np.mean(vol_chunks[3])
            # Rounded bottom: volume decreased then increased
            if second_half > first_half * 1.1:
                # Check price is making a rounded shape (low std + recent uptick)
                if float(recent.iloc[-1]) > float(recent.iloc[0]):
                    patterns.append(
                        {
                            "pattern": "Rounded Bottom",
                            "signal": "Bullish",
                            "confirmed": False,
                        }
                    )
            # Rounded top: volume declining
            if first_half > second_half * 1.1:
                if float(recent.iloc[-1]) < float(recent.iloc[0]):
                    patterns.append(
                        {
                            "pattern": "Rounded Top",
                            "signal": "Bearish",
                            "confirmed": False,
                        }
                    )

    return patterns


def detect(
    df: pd.DataFrame,
) -> list[dict]:
    """Run all pattern detectors on a DataFrame.

    Args:
        df: DataFrame with at least a 'Close' column (and optionally 'Volume').

    Returns:
        List of detected pattern dicts.
    """
    close = df["Close"]
    volume = df.get("Volume")

    patterns: list[dict] = []
    for detector in [
        detect_double_top,
        detect_double_bottom,
        detect_head_and_shoulders,
        detect_inverse_head_and_shoulders,
    ]:
        result = detector(close)
        if result:
            patterns.append(result)

    patterns.extend(detect_triangles(close))
    patterns.extend(detect_wedges(close))
    patterns.extend(detect_rounded(close, volume))

    return patterns
