"""GG006 arc-radius checks, including plane selection and tolerances."""

from gcode_guard import Config, check_text

HEADER = "G21 G17\nM3 S1000\nG0 Z10\nG0 X20 Y0\nG1 Z-1 F100\n"
FOOTER = "M5\nM30\n"


def rules(findings):
    return [(f.rule, f.line) for f in findings]


def test_arc_valid_passes():
    # Start (20, 0), centre (10, 0) via I-10 J0, end (10, 10): both radii 10.
    src = HEADER + "G2 X10 Y10 I-10 J0\n" + FOOTER
    assert check_text(src) == []


def test_arc_radius_mismatch_flagged():
    # End (10, 5) is only 5 from the centre (10, 0); start radius is 10.
    src = HEADER + "G2 X10 Y5 I-10 J0\n" + FOOTER
    findings = check_text(src)
    assert rules(findings) == [("GG006", 6)]
    assert findings[0].severity == "error"


def test_arc_r_word_is_skipped():
    # R-format arcs carry no explicit centre in the text: not checked.
    src = HEADER + "G2 X10 Y5 R10\n" + FOOTER
    assert check_text(src) == []


def test_arc_g18_plane_valid():
    src = (
        "G21 G18\nM3 S1000\nG0 Z10\nG0 X20\nG1 Z0 F100\n"
        "G2 X10 Z10 I-10 K0\nM5\nM30\n"
    )
    assert check_text(src) == []


def test_arc_g18_plane_mismatch_flagged():
    src = (
        "G21 G18\nM3 S1000\nG0 Z10\nG0 X20\nG1 Z0 F100\n"
        "G2 X10 Z5 I-10 K0\nM5\nM30\n"
    )
    assert rules(check_text(src)) == [("GG006", 6)]


def test_arc_within_default_tolerance_passes():
    # End radius 9.97 vs start radius 10: deviation 0.03 < 0.05 default.
    src = HEADER + "G2 X10 Y9.97 I-10 J0\n" + FOOTER
    assert check_text(src) == []


def test_arc_custom_tolerance_flags_small_deviation():
    src = HEADER + "G2 X10 Y9.97 I-10 J0\n" + FOOTER
    findings = check_text(src, Config(arc_tolerance=0.01))
    assert rules(findings) == [("GG006", 6)]
