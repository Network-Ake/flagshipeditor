#!/usr/bin/env python3
"""Deterministic regression tests for the local cyber-forensic protocol."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "scripts" / "cyber_forensic_protocol.py"
SPEC = importlib.util.spec_from_file_location("cyber_forensic_protocol", PROTOCOL_PATH)
assert SPEC and SPEC.loader
protocol = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = protocol
SPEC.loader.exec_module(protocol)


MINIMAL_ENGINES = {
    "beat_analysis.py": """
def frequency_filter(y, sr, cutoff, filter_type): return y
def analyze_track(path, progress_callback=None): return {}
def detect_phrase_boundaries(beats, tempo, sections): return []
""",
    "clip_analysis.py": """
ANALYSIS_SCHEMA_VERSION = 'fixture'
def classify_clip(path, cancel_event=None): return {}
def compute_visual_scores(frames, motion): return {'composition_score': 0, 'energy_score': 0, 'sharpness_score': 0, 'histogram': []}
def find_best_moment(frames, motion, timestamps): return {}
""",
    "shot_selector.py": """
SECTION_WEIGHTS = {}
SECTION_SCENE_AFFINITY = {}
MIN_CUT_SECONDS = 0.15
def plan_cuts(*args, **kwargs): return []
def score_clip(*args, **kwargs): return {}
def select_best_clips(*args, **kwargs): return []
""",
    # Only parsed by the static audit, never imported: the declared ASGI
    # surface can therefore be spelled out without the packages installed.
    "server.py": """
import uvicorn
from fastapi import FastAPI
app = 'fixture'
def main(port=None): return 0
""",
}


def make_fixture(root: Path) -> None:
    (root / "engine").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    for name, source in MINIMAL_ENGINES.items():
        (root / "engine" / name).write_text(source.strip() + "\n", encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="forensic-protocol-regression-") as directory:
        fixture = Path(directory)
        make_fixture(fixture)
        output = fixture / "evidence"
        baseline = fixture / "baseline.json"
        common = [
            "--project-root", str(fixture),
            "--output", str(output),
            "--baseline", str(baseline),
            "--tests", "none",
            "--skip-invariants",
            "--overwrite-output",
        ]

        created = protocol.main(
            [*common, "--update-baseline", "--accept-baseline", "deterministic regression fixture"]
        )
        assert created == protocol.EXIT_PASS
        first_report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        assert first_report["verdict"]["status"] == "PASS"
        boundary = first_report["network_boundary"]
        assert boundary["declared_surfaces"]["engine/server.py"] == ["fastapi", "uvicorn"]
        assert boundary["measured_imports"]["engine/server.py"] == [
            "engine/server.py:1 import uvicorn",
            "engine/server.py:2 import fastapi",
        ]
        assert boundary["measured_imports"]["engine/beat_analysis.py"] == []
        assert boundary["unexpected_imports"] == {}
        assert any(
            "declared scope boundaries" in limitation
            for limitation in first_report["limitations"]
        )
        assert first_report["summary"]["test_counts"] == {"pass": 0, "fail": 0, "not_run": 3}
        assert len(first_report["signatures"]) == 4
        assert (output / "SHA256SUMS").is_file()
        sealed, errors = protocol.verify_seal(output)
        assert sealed, errors

        (output / "report.md").write_text("tampered\n", encoding="utf-8")
        sealed, errors = protocol.verify_seal(output)
        assert not sealed and "hash mismatch: report.md" in errors

        repeat = protocol.main(common)
        assert repeat == protocol.EXIT_PASS

        selector = fixture / "engine" / "shot_selector.py"
        selector.write_text(selector.read_text(encoding="utf-8") + "\nDRIFT_MARKER = True\n", encoding="utf-8")
        drift = protocol.main(common)
        assert drift == protocol.EXIT_DRIFT
        drift_report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        assert drift_report["baseline"]["status"] == "drift"
        assert [item["path"] for item in drift_report["baseline"]["changed"]] == [
            "engine/shot_selector.py"
        ]

        selector.write_text(selector.read_text(encoding="utf-8") + "\neval('1 + 1')\n", encoding="utf-8")
        failed = protocol.main(common)
        assert failed == protocol.EXIT_FAILURE
        failure_report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        assert any(
            finding["check"] == "dynamic-code-execution" and finding["status"] == "fail"
            for finding in failure_report["findings"]
        )

        # Aliased subprocess calls with shell=True must be resolved and caught.
        selector.write_text(
            selector.read_text(encoding="utf-8")
            + "\nimport subprocess as _sp"
            + "\nfrom subprocess import Popen as _spawn"
            + "\ndef _fixture_shell():"
            + "\n    _sp.run(['x'], shell=True)"
            + "\n    _spawn(['x'], shell=True)\n",
            encoding="utf-8",
        )
        aliased = protocol.main(common)
        assert aliased == protocol.EXIT_FAILURE
        aliased_report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        shell_findings = [
            finding
            for finding in aliased_report["findings"]
            if finding["check"] == "shell-injection-surface" and finding["status"] == "fail"
        ]
        assert shell_findings and len(shell_findings[0]["evidence"]) == 2

        # A network-capable import outside the declared server surface fails.
        server = fixture / "engine" / "server.py"
        server.write_text(server.read_text(encoding="utf-8") + "\nimport ftplib\n", encoding="utf-8")
        undeclared = protocol.main(common)
        assert undeclared == protocol.EXIT_FAILURE
        undeclared_report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        assert any(
            finding["check"] == "network-surface"
            and finding["status"] == "fail"
            and any("ftplib" in evidence for evidence in finding["evidence"])
            for finding in undeclared_report["findings"]
        )
        assert list(undeclared_report["network_boundary"]["unexpected_imports"]) == [
            "engine/server.py"
        ]

        # Evidence paths outside the project root keep their full identity
        # instead of collapsing to a bare filename.
        outside = fixture.parent / "flagship-forensic-outside" / "evidence.json"
        assert protocol.relative(outside, fixture) == outside.resolve().as_posix()
        assert protocol.relative(fixture / "engine" / "server.py", fixture) == "engine/server.py"

        missing_fixture = fixture / "missing-baseline-fixture"
        make_fixture(missing_fixture)
        missing_output = missing_fixture / "evidence"
        missing_exit = protocol.main(
            [
                "--project-root", str(missing_fixture),
                "--output", str(missing_output),
                "--baseline", str(missing_fixture / "absent.json"),
                "--tests", "none",
                "--skip-invariants",
            ]
        )
        assert missing_exit == protocol.EXIT_DRIFT
        missing_report = json.loads((missing_output / "report.json").read_text(encoding="utf-8"))
        assert missing_report["verdict"]["status"] == "WARN"
        assert missing_report["baseline"]["status"] == "missing"

        immutable_fixture = fixture / "immutable-fixture"
        make_fixture(immutable_fixture)
        immutable_output = immutable_fixture / "evidence"
        immutable_output.mkdir(parents=True)
        (immutable_output / "existing.txt").write_text("sealed\n", encoding="utf-8")
        immutable_exit = protocol.main(
            [
                "--project-root", str(immutable_fixture),
                "--output", str(immutable_output),
                "--tests", "none",
                "--skip-invariants",
            ]
        )
        assert immutable_exit == protocol.EXIT_PROTOCOL_ERROR
        assert (immutable_output / "existing.txt").read_text(encoding="utf-8") == "sealed\n"
        assert sorted(path.name for path in immutable_output.iterdir()) == ["existing.txt"]

        output_file = fixture / "evidence-is-a-file"
        output_file.write_text("do not replace\n", encoding="utf-8")
        output_file_exit = protocol.main(
            [
                "--project-root", str(immutable_fixture),
                "--output", str(output_file),
                "--tests", "none",
                "--skip-invariants",
            ]
        )
        assert output_file_exit == protocol.EXIT_PROTOCOL_ERROR
        assert output_file.read_text(encoding="utf-8") == "do not replace\n"

    print("Cyber-forensic protocol regression tests passed (baseline, drift, failure precedence, evidence).")


if __name__ == "__main__":
    main()
