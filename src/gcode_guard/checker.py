"""Core static checker for CNC G-code programs.

The checker parses a program line by line, tracks the modal machine state
(units, distance mode, plane, feed rate, spindle state/speed and the current
X/Y/Z position) and applies a small set of documented safety/consistency
rules.  It is a *static* checker: it never executes or simulates cutting, it
only reasons about the program text and the tracked modal state.

Rule list (stable IDs):

- GG001 (error)   cutting move (G1/G2/G3) before any feed rate (F) is set
- GG002 (error)   cutting move while the spindle is off (no M3/M4, or after M5)
- GG003 (warning) program ends without M2/M30
- GG004 (warning) program ends with the spindle still on (no M5)
- GG005 (error)   move target outside the configured machine envelope
- GG006 (error)   arc (G2/G3) radius inconsistency between start and end point
- GG007 (warning) units not declared (no G20/G21 before the first move)
- GG008 (warning) rapid (G0) move in X/Y while Z is below the safe-Z height

Only the Python standard library is used.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ERROR = "error"
WARNING = "warning"

FEED_NOT_SET = "GG001"
SPINDLE_OFF_CUT = "GG002"
MISSING_PROGRAM_END = "GG003"
SPINDLE_LEFT_ON = "GG004"
ENVELOPE_EXCEEDED = "GG005"
ARC_RADIUS_MISMATCH = "GG006"
UNITS_NOT_DECLARED = "GG007"
RAPID_BELOW_SAFE_Z = "GG008"

DEFAULT_ARC_TOLERANCE = 0.05
DEFAULT_SAFE_Z = 5.0

# Plane -> (axis1, axis2, offset1, offset2) used for arc radius checks.
_PLANES = {
    17: ("X", "Y", "I", "J"),  # G17 XY plane
    18: ("X", "Z", "I", "K"),  # G18 XZ plane
    19: ("Y", "Z", "J", "K"),  # G19 YZ plane
}

_ENVELOPE_KEYS = ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")
_CONFIG_KEYS = set(_ENVELOPE_KEYS) | {"safe_z", "arc_tolerance"}

_WORD_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))")


@dataclass
class Finding:
    """One rule violation (or warning) at a specific program line."""

    rule: str
    severity: str  # ERROR or WARNING
    line: int  # 1-based line number in the source program
    message: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "line": self.line,
            "message": self.message,
        }


@dataclass
class Config:
    """Checker configuration: machine envelope limits and tolerances.

    Envelope limits are ``None`` when not configured; axes without limits
    are simply not checked (GG005).  ``safe_z`` is the rapid-traverse safe
    height used by GG008 and ``arc_tolerance`` the allowed radius deviation
    used by GG006, both expressed in the program's own units.
    """

    x_min: Optional[float] = None
    x_max: Optional[float] = None
    y_min: Optional[float] = None
    y_max: Optional[float] = None
    z_min: Optional[float] = None
    z_max: Optional[float] = None
    safe_z: float = DEFAULT_SAFE_Z
    arc_tolerance: float = DEFAULT_ARC_TOLERANCE

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Config":
        unknown = set(data) - _CONFIG_KEYS
        if unknown:
            raise ValueError(
                "unknown config key(s): %s (known: %s)"
                % (", ".join(sorted(unknown)), ", ".join(sorted(_CONFIG_KEYS)))
            )
        values: Dict[str, object] = {}
        for key, value in data.items():
            if value is not None:
                value = float(value)  # type: ignore[arg-type]
            values[key] = value
        return cls(**values)  # type: ignore[arg-type]

    @classmethod
    def from_json(cls, path) -> "Config":
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_dict(json.loads(text))

    def limit_for(self, axis: str) -> Tuple[Optional[float], Optional[float]]:
        return (
            getattr(self, axis.lower() + "_min"),
            getattr(self, axis.lower() + "_max"),
        )


def strip_comments(line: str) -> str:
    """Remove ``( ... )`` comments and ``;`` end-of-line comments."""
    out: List[str] = []
    in_paren = False
    for ch in line:
        if in_paren:
            if ch == ")":
                in_paren = False
            continue
        if ch == "(":
            in_paren = True
            continue
        if ch == ";":
            break
        out.append(ch)
    return "".join(out)


def parse_words(text: str) -> List[Tuple[str, float]]:
    """Extract ``(letter, value)`` words such as ``('G', 1.0)`` or ``('X', -2.5)``."""
    return [(letter.upper(), float(num)) for letter, num in _WORD_RE.findall(text)]


def _code(value: float) -> Optional[int]:
    """Return the integer code for a G/M word value, or None if fractional."""
    return int(value) if float(value).is_integer() else None


def check_text(source: str, config: Optional[Config] = None) -> List[Finding]:
    """Check G-code source text and return findings sorted by line, then rule."""
    cfg = config if config is not None else Config()
    findings: List[Finding] = []
    lines = source.splitlines()

    # Modal machine state.  The machine is assumed to start at the origin
    # (X0 Y0 Z0) with the spindle off and no feed rate set.
    units: Optional[str] = None  # "G20" or "G21" once declared
    absolute = True  # G90 default; G91 switches to incremental
    plane = 17  # G17 default
    feed: Optional[float] = None
    spindle_on = False
    spindle_speed: Optional[float] = None  # tracked state (S word)
    pos = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    motion: Optional[int] = None  # modal motion code 0..3
    program_end_seen = False
    units_warned = False

    for lineno, raw in enumerate(lines, start=1):
        text = strip_comments(raw).strip()
        if not text or text == "%":
            continue
        words = parse_words(text)
        if not words:
            continue

        letters = {letter for letter, _ in words}
        g_codes = [_code(v) for letter, v in words if letter == "G"]
        m_codes = [_code(v) for letter, v in words if letter == "M"]
        axes = {letter: v for letter, v in words if letter in "XYZ"}
        offsets = {letter: v for letter, v in words if letter in "IJK"}

        # ---- modal state updates from this block (applied before the move,
        # so e.g. "G1 X10 F200" counts as having a feed rate) ----
        for g in g_codes:
            if g == 20:
                units = "G20"
            elif g == 21:
                units = "G21"
            elif g == 90:
                absolute = True
            elif g == 91:
                absolute = False
            elif g in _PLANES:
                plane = g
        for letter, value in words:
            if letter == "F":
                feed = value
            elif letter == "S":
                spindle_speed = value
        for m in m_codes:
            if m in (3, 4):
                spindle_on = True
            elif m == 5:
                spindle_on = False
            elif m in (2, 30):
                program_end_seen = True

        # ---- effective motion for this block (explicit G word wins,
        # otherwise the modal motion code applies when axis words exist) ----
        block_motion: Optional[int] = None
        for g in g_codes:
            if g in (0, 1, 2, 3):
                block_motion = g
        if block_motion is not None:
            motion = block_motion
        eff_motion = block_motion if block_motion is not None else motion

        if eff_motion is None or not axes:
            continue  # not a move: nothing else to check on this block

        start = dict(pos)
        target = dict(pos)
        for axis, value in axes.items():
            target[axis] = value if absolute else pos[axis] + value

        # GG007: units must be declared before the first move.
        if units is None and not units_warned:
            findings.append(
                Finding(
                    UNITS_NOT_DECLARED,
                    WARNING,
                    lineno,
                    "units not declared (no G20/G21) before first move",
                )
            )
            units_warned = True

        if eff_motion in (1, 2, 3):
            # Cutting move.
            if feed is None:
                findings.append(
                    Finding(
                        FEED_NOT_SET,
                        ERROR,
                        lineno,
                        "cutting move (G%d) before any feed rate (F) has been set"
                        % eff_motion,
                    )
                )
            if not spindle_on:
                findings.append(
                    Finding(
                        SPINDLE_OFF_CUT,
                        ERROR,
                        lineno,
                        "cutting move (G%d) while spindle is off "
                        "(no M3/M4 active)" % eff_motion,
                    )
                )
            if eff_motion in (2, 3):
                arc_finding = _check_arc(cfg, plane, start, target, offsets, letters, lineno)
                if arc_finding is not None:
                    findings.append(arc_finding)
        elif eff_motion == 0:
            # GG008: rapid traverse in X/Y below the safe-Z height.
            if ("X" in axes or "Y" in axes) and target["Z"] < cfg.safe_z:
                findings.append(
                    Finding(
                        RAPID_BELOW_SAFE_Z,
                        WARNING,
                        lineno,
                        "rapid move (G0) in X/Y at Z=%.3f below safe Z=%.3f"
                        % (target["Z"], cfg.safe_z),
                    )
                )

        # GG005: envelope limits apply to the move target, any motion type.
        exceeded = []
        for axis in axes:
            lo, hi = cfg.limit_for(axis)
            value = target[axis]
            if lo is not None and value < lo:
                exceeded.append("%s=%.3f < min %.3f" % (axis, value, lo))
            if hi is not None and value > hi:
                exceeded.append("%s=%.3f > max %.3f" % (axis, value, hi))
        if exceeded:
            findings.append(
                Finding(
                    ENVELOPE_EXCEEDED,
                    ERROR,
                    lineno,
                    "move exceeds machine envelope: " + "; ".join(exceeded),
                )
            )

        pos = target

    last_line = max(1, len(lines))
    if not program_end_seen:
        findings.append(
            Finding(
                MISSING_PROGRAM_END,
                WARNING,
                last_line,
                "program ends without M2/M30",
            )
        )
    if spindle_on:
        findings.append(
            Finding(
                SPINDLE_LEFT_ON,
                WARNING,
                last_line,
                "program ends with spindle still on (no M5)",
            )
        )

    findings.sort(key=lambda f: (f.line, f.rule))
    return findings


def _check_arc(
    cfg: Config,
    plane: int,
    start: Dict[str, float],
    target: Dict[str, float],
    offsets: Dict[str, float],
    letters,
    lineno: int,
) -> Optional[Finding]:
    """GG006: compare start->center and end->center distances for G2/G3.

    Only center-format arcs (I/J/K words) are checked; R-word arcs carry no
    explicit center in the program text and are skipped.
    """
    if "R" in letters:
        return None
    axis1, axis2, off1, off2 = _PLANES[plane]
    if off1 not in offsets and off2 not in offsets:
        return None
    center1 = start[axis1] + offsets.get(off1, 0.0)
    center2 = start[axis2] + offsets.get(off2, 0.0)
    r_start = math.hypot(start[axis1] - center1, start[axis2] - center2)
    r_end = math.hypot(target[axis1] - center1, target[axis2] - center2)
    if abs(r_start - r_end) > cfg.arc_tolerance:
        return Finding(
            ARC_RADIUS_MISMATCH,
            ERROR,
            lineno,
            "arc radius mismatch: start radius %.3f vs end radius %.3f "
            "(tolerance %.3f)" % (r_start, r_end, cfg.arc_tolerance),
        )
    return None


def check_file(path, config: Optional[Config] = None) -> List[Finding]:
    """Check a G-code file on disk and return its findings."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return check_text(text, config)
