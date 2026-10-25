"""gcode-guard: a static checker for CNC G-code programs.

Public API:

    from gcode_guard import check_text, check_file, Config

    findings = check_text(source)                 # list[Finding]
    findings = check_file("program.nc", config)   # with envelope limits

Each :class:`Finding` carries a stable rule ID (GG001..GG008), a severity
(``"error"`` or ``"warning"``), a 1-based line number and a message.
"""

from .checker import (
    ARC_RADIUS_MISMATCH,
    ENVELOPE_EXCEEDED,
    ERROR,
    FEED_NOT_SET,
    MISSING_PROGRAM_END,
    RAPID_BELOW_SAFE_Z,
    SPINDLE_LEFT_ON,
    SPINDLE_OFF_CUT,
    UNITS_NOT_DECLARED,
    WARNING,
    Config,
    Finding,
    check_file,
    check_text,
)

__version__ = "0.1.0"

__all__ = [
    "ARC_RADIUS_MISMATCH",
    "ENVELOPE_EXCEEDED",
    "ERROR",
    "FEED_NOT_SET",
    "MISSING_PROGRAM_END",
    "RAPID_BELOW_SAFE_Z",
    "SPINDLE_LEFT_ON",
    "SPINDLE_OFF_CUT",
    "UNITS_NOT_DECLARED",
    "WARNING",
    "Config",
    "Finding",
    "check_file",
    "check_text",
    "__version__",
]
