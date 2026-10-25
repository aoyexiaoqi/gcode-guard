"""CLI behaviour: exit codes, text and JSON output, --config handling."""

import json

from gcode_guard import check_file
from gcode_guard.cli import main

CLEAN = "G21\nM3 S1000\nG1 X5 F100\nM5\nM30\n"
WITH_ERROR = "G21\nG1 X5\nM30\n"  # GG001 + GG002 on line 2
WARNINGS_ONLY = "G21\nM3 S1000\nG1 X5 F100\nM5\n"  # GG003 only


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_cli_clean_program_exit_zero(tmp_path, capsys):
    program = write(tmp_path, "ok.nc", CLEAN)
    assert main([program]) == 0
    assert "0 error(s), 0 warning(s)" in capsys.readouterr().out


def test_cli_error_program_exit_one(tmp_path, capsys):
    program = write(tmp_path, "bad.nc", WITH_ERROR)
    assert main([program]) == 1
    out = capsys.readouterr().out
    assert "GG001" in out and "GG002" in out


def test_cli_warnings_only_exit_zero(tmp_path):
    program = write(tmp_path, "warn.nc", WARNINGS_ONLY)
    assert main([program]) == 0


def test_cli_json_output_structure(tmp_path, capsys):
    program = write(tmp_path, "bad.nc", WITH_ERROR)
    assert main([program, "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["file"] == program
    assert payload["summary"] == {"errors": 2, "warnings": 0}
    assert {f["rule"] for f in payload["findings"]} == {"GG001", "GG002"}
    for finding in payload["findings"]:
        assert set(finding) == {"rule", "severity", "line", "message"}
        assert finding["line"] == 2
        assert finding["severity"] == "error"


def test_cli_config_envelope_via_file(tmp_path):
    program = write(
        tmp_path, "big.nc", "G21\nM3 S1000\nG1 X150 F100\nM5\nM30\n"
    )
    limits = write(tmp_path, "limits.json", json.dumps({"x_max": 100}))
    assert main([program]) == 0  # no limits configured -> no GG005
    assert main([program, "--config", limits]) == 1


def test_cli_missing_file_exit_two(tmp_path):
    assert main([str(tmp_path / "nope.nc")]) == 2


def test_check_file_api(tmp_path):
    program = write(tmp_path, "bad.nc", WITH_ERROR)
    findings = check_file(program)
    assert [(f.rule, f.line) for f in findings] == [("GG001", 2), ("GG002", 2)]
