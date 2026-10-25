"""Per-rule tests: one planted violation per rule, plus modal-state cases."""

from gcode_guard import Config, check_text

CLEAN_PROGRAM = """\
%
G21 G90 G17
M3 S1000
G0 Z10
G0 X10 Y0
G1 Z-1 F100
G1 X20
G2 X10 Y10 I-10 J0
G0 Z10
M5
M30
%
"""


def rules(findings):
    return [(f.rule, f.line) for f in findings]


def test_clean_program_zero_findings():
    assert check_text(CLEAN_PROGRAM) == []


# ---------------- GG001: cutting move before any feed rate ----------------

def test_gg001_cut_before_feed_flagged():
    src = "G21 G90\nM3 S1000\nG1 X10\nM5\nM30\n"
    findings = check_text(src)
    assert rules(findings) == [("GG001", 3)]
    assert findings[0].severity == "error"


def test_gg001_feed_in_same_block_counts():
    src = "G21\nM3 S1000\nG1 X10 F200\nM5\nM30\n"
    assert check_text(src) == []


def test_modal_feed_set_once_then_reused():
    src = "G21\nM3 S1000\nG1 X5 F200\nG1 X10\nG1 Y10\nM5\nM30\n"
    assert check_text(src) == []


# ---------------- GG002: cutting move while spindle is off ----------------

def test_gg002_cut_with_spindle_never_started():
    src = "G21 G90\nG1 X10 F100\nM30\n"
    findings = check_text(src)
    assert rules(findings) == [("GG002", 2)]
    assert findings[0].severity == "error"


def test_gg002_cut_after_m5_flagged():
    src = "G21\nM3 S800\nG1 X5 F100\nM5\nG1 X10\nM30\n"
    assert rules(check_text(src)) == [("GG002", 5)]


def test_spindle_restarted_after_m5_ok():
    src = "G21\nM3 S1000\nG1 X5 F100\nM5\nM3 S1200\nG1 X10\nM5\nM30\n"
    assert check_text(src) == []


# ---------------- GG003 / GG004: program end ----------------

def test_gg003_missing_program_end():
    src = "G21\nM3 S1000\nG1 X5 F100\nM5\n"
    findings = check_text(src)
    assert rules(findings) == [("GG003", 4)]
    assert findings[0].severity == "warning"


def test_gg003_m2_is_accepted_as_program_end():
    src = "G21\nM3 S1000\nG1 X5 F100\nM5\nM2\n"
    assert check_text(src) == []


def test_gg004_spindle_left_on_at_end():
    src = "G21\nM3 S1000\nG1 X5 F100\nM30\n"
    findings = check_text(src)
    assert rules(findings) == [("GG004", 4)]
    assert findings[0].severity == "warning"


def test_empty_program_warns_missing_end():
    assert rules(check_text("")) == [("GG003", 1)]


# ---------------- GG005: machine envelope ----------------

def test_gg005_envelope_exceeded_absolute():
    src = "G21\nM3 S1000\nG0 Z10\nG1 X150 F100\nM5\nM30\n"
    findings = check_text(src, Config(x_max=100.0))
    assert rules(findings) == [("GG005", 4)]
    assert findings[0].severity == "error"


def test_gg005_within_limits_ok():
    src = "G21\nM3 S1000\nG0 Z10\nG1 X50 F100\nM5\nM30\n"
    assert check_text(src, Config(x_max=100.0)) == []


def test_gg005_incremental_g91_accumulates():
    src = "G21 G91\nM3 S1000\nG1 X60 F100\nG1 X60\nM5\nM30\n"
    findings = check_text(src, Config(x_max=100.0))
    assert rules(findings) == [("GG005", 4)]


def test_gg005_no_config_means_no_envelope_check():
    src = "G21\nM3 S1000\nG1 X100000 F100\nM5\nM30\n"
    assert check_text(src) == []


def test_gg005_only_configured_axes_are_checked():
    src = "G21\nM3 S1000\nG1 X-50 F100\nG1 Y9999\nM5\nM30\n"
    findings = check_text(src, Config(x_min=-10.0))
    assert rules(findings) == [("GG005", 3)]


# ---------------- GG007: units not declared ----------------

def test_gg007_units_not_declared_warns_once_at_first_move():
    src = "M3 S1000\nG1 X5 F100\nG1 X10\nM5\nM30\n"
    findings = check_text(src)
    assert rules(findings) == [("GG007", 2)]
    assert findings[0].severity == "warning"


def test_gg007_g20_inch_declaration_ok():
    src = "G20\nM3 S1000\nG1 X5 F10\nM5\nM30\n"
    assert check_text(src) == []


# ---------------- GG008: rapid in X/Y below safe Z ----------------

def test_gg008_rapid_xy_below_safe_z():
    src = (
        "G21\nM3 S1000\nG0 Z10\nG0 X10 Y10\nG1 Z-1 F100\n"
        "G0 X20 Y20\nG0 Z10\nM5\nM30\n"
    )
    findings = check_text(src)
    assert rules(findings) == [("GG008", 6)]
    assert findings[0].severity == "warning"


def test_gg008_rapid_z_only_move_not_flagged():
    src = "G21\nM3 S1000\nG1 Z-1 F100\nG0 Z-2\nM5\nM30\n"
    assert check_text(src) == []


def test_gg008_custom_safe_z():
    src = "G21\nM3 S1000\nG0 Z2\nG0 X10 Y10\nM5\nM30\n"
    # Default safe_z=5.0: traversing at Z=2 is below the safe height.
    assert rules(check_text(src)) == [("GG008", 4)]
    # With safe_z lowered to 0 the same program is acceptable.
    assert check_text(src, Config(safe_z=0.0)) == []


# ---------------- parsing behaviour ----------------

def test_comments_are_ignored():
    src = (
        "G21 (units mm) ; setup\n"
        "M3 S1000 (spindle on)\n"
        "G1 X5 F100 ; G1 X9999 would be commented out\n"
        "(G1 X500)\n"
        "M5\nM30\n"
    )
    assert check_text(src) == []


def test_commented_out_m3_does_not_start_spindle():
    src = "G21\n; M3 S1000\nG1 X5 F100\nM30\n"
    assert rules(check_text(src)) == [("GG002", 3)]


def test_lowercase_program_ok():
    src = "g21\nm3 s1000\ng1 x5 f100\nm5\nm30\n"
    assert check_text(src) == []


def test_multiple_findings_on_same_line():
    src = "G21\nG1 X5\nM30\n"
    found = rules(check_text(src))
    assert ("GG001", 2) in found
    assert ("GG002", 2) in found
    assert len(found) == 2
