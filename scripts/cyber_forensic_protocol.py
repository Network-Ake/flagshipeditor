#!/usr/bin/env python3
"""Local, evidence-producing cyber-forensic audit for FlagshipEditor engines.

The protocol is deliberately offline. It inventories and hashes the beat,
clip, and selector engines; performs AST-based static checks; executes existing
deterministic tests in isolated temporary directories; validates cross-engine
contracts with synthetic data; and compares the result with a reviewed
baseline.

Exit codes are stable for CI:
    0  all mandatory gates passed and no baseline drift
    1  one or more audit/test/invariant gates failed
    2  no hard failure, but a warning, missing baseline, or drift exists
    3  protocol/internal error
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROTOCOL_VERSION = "1.0.0"
SCHEMA_VERSION = 2
EXIT_PASS = 0
EXIT_FAILURE = 1
EXIT_DRIFT = 2
EXIT_PROTOCOL_ERROR = 3

ENGINE_TARGETS = (
    "engine/beat_analysis.py",
    "engine/clip_analysis.py",
    "engine/shot_selector.py",
    "engine/server.py",
)
CROSS_LANGUAGE_TARGETS = (
    "src/js/main/App.tsx",
    "src/js/main/lib/python.ts",
    "src/jsx/aeft/aeft.ts",
)
CRITICAL_TEST_TARGETS = (
    "scripts/test-engine-contracts.py",
    "scripts/test-analysis-jobs.py",
    "scripts/test-server-health.py",
    "scripts/test-cyber-forensic-protocol.py",
)
ANALYSIS_TARGETS = (
    "engine/ANALYSIS-beat.md",
    "engine/ANALYSIS-clip.md",
    "engine/ANALYSIS-selector.md",
)
INVENTORY_PATTERNS = (
    "engine/*.py",
    "engine/requirements*.txt",
    "engine/requirements*.lock",
    "engine/VERSION",
    "engine/ANALYSIS-*.md",
    "engine/CYBER-FORENSIC-SPEC.md",
    "scripts/test-*.py",
    "scripts/test-*.mjs",
    "scripts/cyber_forensic_protocol.py",
    "src/js/main/App.tsx",
    "src/js/main/lib/python.ts",
    "src/jsx/aeft/aeft.ts",
    "styles/*.json",
)

REQUIRED_SYMBOLS: Mapping[str, Tuple[str, ...]] = {
    "engine/beat_analysis.py": (
        "analyze_track",
        "detect_phrase_boundaries",
        "frequency_filter",
    ),
    "engine/clip_analysis.py": (
        "ANALYSIS_SCHEMA_VERSION",
        "classify_clip",
        "compute_visual_scores",
        "find_best_moment",
    ),
    "engine/shot_selector.py": (
        "SECTION_WEIGHTS",
        "SECTION_SCENE_AFFINITY",
        "MIN_CUT_SECONDS",
        "plan_cuts",
        "score_clip",
        "select_best_clips",
    ),
    "engine/server.py": (
        "app",
        "main",
    ),
}

NETWORK_MODULES = {
    "aiohttp",
    "fastapi",
    "ftplib",
    "http.client",
    "httpx",
    "requests",
    "socket",
    "starlette",
    "urllib",
    "urllib.request",
    "uvicorn",
    "websockets",
}
# engine/server.py is the declared network boundary: a FastAPI app served by
# uvicorn on loopback. Any other network-capable import there — and any network
# import at all in the pure analysis engines — is an unexpected surface.
EXPECTED_NETWORK_SURFACE: Mapping[str, Tuple[str, ...]] = {
    "engine/server.py": ("fastapi", "uvicorn"),
}
NONDETERMINISTIC_CALLS = {
    "np.random",
    "numpy.random",
    "random.choice",
    "random.random",
    "random.randrange",
    "random.randint",
    "random.shuffle",
    "random.uniform",
    "secrets.choice",
    "secrets.randbelow",
}

EXISTING_TESTS: Mapping[str, Tuple[str, ...]] = {
    "engine-contracts": ("{python}", "scripts/test-engine-contracts.py"),
    "analysis-jobs": ("{python}", "scripts/test-analysis-jobs.py"),
    "server-health": ("{python}", "scripts/test-server-health.py"),
}


@dataclass
class Finding:
    check: str
    status: str
    severity: str
    message: str
    evidence: List[str] = field(default_factory=list)


@dataclass
class CommandEvidence:
    name: str
    command: List[str]
    status: str
    exit_code: Optional[int]
    duration_ms: int
    stdout_sha256: str
    stderr_sha256: str
    stdout: str
    stderr: str
    timed_out: bool = False


class AuditError(RuntimeError):
    """Raised for a protocol problem rather than an engine finding."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_stamp() -> str:
    """A collision-resistant UTC stamp for immutable run directories."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def detect_engine_python(root: Path) -> Path:
    """Prefer the project's proven engine runtime over the calling Python."""
    candidates = (
        root / "engine" / ".venv" / "bin" / "python",
        root / "engine" / ".venv" / "Scripts" / "python.exe",
        root / "engine" / "runtime" / "python.exe",
        Path(sys.executable),
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise AuditError("No executable Python runtime found for the engine audit")


def runtime_evidence(python_runtime: Path) -> Dict[str, Any]:
    packages: Dict[str, str] = {}
    for distribution in (
        "librosa",
        "numpy",
        "opencv-python",
        "opencv-python-headless",
        "scipy",
        "fastapi",
        "pydantic",
    ):
        try:
            packages[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            packages[distribution] = "missing"
    return {
        "python_executable": str(python_runtime),
        "python_sha256": sha256_file(python_runtime.resolve()),
        "python_version": sys.version,
        "protocol_process_executable": sys.executable,
        "engine_venv_selected": ".venv" in python_runtime.parts,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
    }


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return sha256_bytes(encoded)


def relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        # A path outside the root keeps its full identity: collapsing it to a
        # bare filename made outside-root evidence read as root-relative.
        return path.resolve().as_posix()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def is_nonempty_directory(path: Path) -> bool:
    """Return directory occupancy without ever calling iterdir() on a file."""
    return path.is_dir() and next(path.iterdir(), None) is not None


def collect_inventory(root: Path) -> List[Dict[str, Any]]:
    paths = set()
    for pattern in INVENTORY_PATTERNS:
        for path in root.glob(pattern):
            if path.is_file():
                paths.add(path)
    inventory = []
    for path in sorted(paths, key=lambda item: relative(item, root)):
        raw = path.read_bytes()
        inventory.append(
            {
                "path": relative(path, root),
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
            }
        )
    return inventory


def symbol_table(tree: ast.AST) -> Dict[str, int]:
    symbols: Dict[str, int] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols[node.name] = node.lineno
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    symbols[target.id] = node.lineno
    return symbols


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def imported_modules(tree: ast.AST) -> List[Tuple[str, int]]:
    imports: List[Tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((entry.name, node.lineno) for entry in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.module, node.lineno))
    return imports


def import_bindings(tree: ast.AST) -> Dict[str, str]:
    """Map every locally bound import name to the dotted path it stands for."""
    bindings: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for entry in node.names:
                if entry.asname:
                    bindings[entry.asname] = entry.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for entry in node.names:
                bindings[entry.asname or entry.name] = f"{node.module}.{entry.name}"
    return bindings


def resolved_call_name(func: ast.AST, bindings: Mapping[str, str]) -> str:
    """Resolve a call through import aliases: ``sp.run`` -> ``subprocess.run``."""
    name = dotted_name(func)
    if not name:
        return name
    root_name, separator, remainder = name.partition(".")
    target = bindings.get(root_name)
    if not target:
        return name
    return f"{target}.{remainder}" if separator else target


def static_audit(root: Path) -> Tuple[List[Finding], Dict[str, Any], Dict[str, Any]]:
    findings: List[Finding] = []
    signatures: Dict[str, Any] = {}
    network_boundary: Dict[str, Any] = {
        "declared_surfaces": {
            target: sorted(EXPECTED_NETWORK_SURFACE.get(target, ()))
            for target in ENGINE_TARGETS
        },
        "measured_imports": {},
        "unexpected_imports": {},
    }
    for target in ENGINE_TARGETS:
        path = root / target
        if not path.is_file():
            findings.append(
                Finding("target-present", "fail", "critical", f"Missing engine target: {target}")
            )
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=target)
        except SyntaxError as error:
            findings.append(
                Finding(
                    "ast-parse",
                    "fail",
                    "critical",
                    f"Python syntax failure in {target}",
                    [f"{target}:{error.lineno}:{error.offset}: {error.msg}"],
                )
            )
            continue

        symbols = symbol_table(tree)
        required = REQUIRED_SYMBOLS[target]
        missing = sorted(set(required) - set(symbols))
        if missing:
            findings.append(
                Finding(
                    "required-symbols",
                    "fail",
                    "critical",
                    f"{target} is missing required contract symbols",
                    missing,
                )
            )
        else:
            findings.append(
                Finding(
                    "required-symbols",
                    "pass",
                    "info",
                    f"{target} exposes every required contract symbol",
                    [f"{target}:{symbols[name]} {name}" for name in required],
                )
            )

        signatures[target] = {
            "sha256": sha256_file(path),
            "symbols": {name: symbols[name] for name in sorted(symbols)},
            "ast_sha256": canonical_hash(ast.dump(tree, include_attributes=False)),
        }

        declared = EXPECTED_NETWORK_SURFACE.get(target, ())
        declared_evidence: List[str] = []
        unexpected_evidence: List[str] = []
        for module, line in imported_modules(tree):
            if module in NETWORK_MODULES or any(module.startswith(item + ".") for item in NETWORK_MODULES):
                entry = f"{target}:{line} import {module}"
                if module in declared or any(module.startswith(item + ".") for item in declared):
                    declared_evidence.append(entry)
                else:
                    unexpected_evidence.append(entry)
        network_boundary["measured_imports"][target] = declared_evidence + unexpected_evidence
        if unexpected_evidence:
            network_boundary["unexpected_imports"][target] = unexpected_evidence
        if unexpected_evidence:
            network_message = f"Engine imports undeclared network-capable modules: {target}"
        elif declared_evidence:
            network_message = f"Network imports in {target} match its declared server surface"
        else:
            network_message = f"No network-capable imports found in {target}"
        findings.append(
            Finding(
                "network-surface",
                "fail" if unexpected_evidence else "pass",
                "critical" if unexpected_evidence else "info",
                network_message,
                unexpected_evidence or declared_evidence,
            )
        )

        bindings = import_bindings(tree)
        dangerous: List[str] = []
        nondeterministic: List[str] = []
        shell_true: List[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = resolved_call_name(node.func, bindings)
            if name in {"eval", "exec", "compile"}:
                dangerous.append(f"{target}:{node.lineno} call {name}()")
            if name in NONDETERMINISTIC_CALLS or any(
                name.startswith(prefix + ".") for prefix in ("np.random", "numpy.random")
            ):
                nondeterministic.append(f"{target}:{node.lineno} call {name}()")
            if name in {"subprocess.run", "subprocess.Popen", "subprocess.call"}:
                for keyword in node.keywords:
                    if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                        shell_true.append(f"{target}:{node.lineno} subprocess shell=True")

        findings.append(
            Finding(
                "dynamic-code-execution",
                "fail" if dangerous else "pass",
                "critical" if dangerous else "info",
                "Dynamic code execution found" if dangerous else f"No eval/exec/compile calls in {target}",
                dangerous,
            )
        )
        findings.append(
            Finding(
                "shell-injection-surface",
                "fail" if shell_true else "pass",
                "critical" if shell_true else "info",
                "shell=True subprocess found" if shell_true else f"No shell=True subprocess in {target}",
                shell_true,
            )
        )
        findings.append(
            Finding(
                "selector-determinism-surface",
                "fail" if target.endswith("shot_selector.py") and nondeterministic else "pass",
                "high" if nondeterministic else "info",
                (
                    "Nondeterministic random calls found in selector"
                    if target.endswith("shot_selector.py") and nondeterministic
                    else f"No forbidden random selection calls in {target}"
                ),
                nondeterministic,
            )
        )

    return findings, signatures, network_boundary


def expand_integrity_signatures(
    root: Path,
    signatures: Dict[str, Any],
) -> Dict[str, Any]:
    """Bind the baseline to engines, renderer contracts, auditor, tests and config."""
    targets = set(CROSS_LANGUAGE_TARGETS) | set(CRITICAL_TEST_TARGETS) | {
        "scripts/cyber_forensic_protocol.py",
        "engine/CYBER-FORENSIC-SPEC.md",
        "engine/requirements.txt",
        "engine/requirements-windows.lock",
    }
    targets.update(relative(path, root) for path in (root / "styles").glob("*.json"))
    for target in sorted(targets):
        if target in signatures:
            continue
        path = root / target
        if not path.is_file():
            continue
        digest = sha256_file(path)
        signatures[target] = {
            "sha256": digest,
            "ast_sha256": digest,
            "symbols": {},
        }
    return signatures


def _line_of(source: str, needle: str) -> int:
    for index, line in enumerate(source.splitlines(), 1):
        if needle in line:
            return index
    return 0


def _interface_body(source: str, name: str) -> str:
    match = re.search(rf"interface\s+{re.escape(name)}\s*(?:extends\s+[^{{]+)?\{{(.*?)\n\}}", source, re.S)
    return match.group(1) if match else ""


def _dict_literal_keys(source: str, function_name: str) -> set:
    """Return the literal string keys of the dict a function builds or returns.

    A token search proves a spelling appears somewhere in a file. Reading the
    dict literal out of the function's own AST proves the key is emitted by the
    function that publishes the contract, which is the property the checks below
    actually depend on.
    """
    keys: set = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return keys
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != function_name:
            continue
        for inner in ast.walk(node):
            literal: Optional[ast.Dict] = None
            if isinstance(inner, ast.Return) and isinstance(inner.value, ast.Dict):
                literal = inner.value
            elif isinstance(inner, ast.Assign) and isinstance(inner.value, ast.Dict):
                literal = inner.value
            if literal is None:
                continue
            for key in literal.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
    return keys


def _names_used_in(source: str, function_name: str) -> set:
    """Return every identifier referenced inside one function, from its AST."""
    names: set = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name):
                    names.add(inner.id)
    return names


def _drifted_key(module: Any, attribute: str, value: Any, produce: Any) -> Any:
    """Recompute ``produce()`` with one module setting changed, then restore it.

    A cache identity that claims to bind a setting has to *move* when that
    setting moves. Asserting the claim by changing the setting is the only way
    to know, and the original value is restored whatever happens.
    """
    original = getattr(module, attribute)
    try:
        setattr(module, attribute, value)
        return produce()
    finally:
        setattr(module, attribute, original)


def _shifted_frames(size: int = 96, shift: int = 4) -> list:
    """Two textured frames, the second shifted, so dense flow is non-zero."""
    import numpy as np

    base = np.zeros((size, size, 3), dtype=np.uint8)
    for index in range(0, size, 8):
        base[:, index:index + 4] = 255
        base[index:index + 4, :] = 200
    return [base, np.roll(base, shift, axis=1)]


def resolved_gap_audit(
    root: Path,
    beat: Any,
    clip: Any,
    selector: Any,
    workspace: Path,
) -> List[Finding]:
    """Verify the previously-known evidence gaps by running the engines.

    Each check below used to be a search for a spelling in a source file, which
    proves nothing about behaviour. These call the code: the cache identity is
    re-derived with one setting changed, the flow normalisation is divided out
    by hand, the phrase and energy signals are supplied and withheld, and the
    published contract keys are read from the emitting function's own AST.
    """
    import numpy as np

    findings: List[Finding] = []
    beat_source = (root / "engine" / "beat_analysis.py").read_text(encoding="utf-8")
    clip_source = (root / "engine" / "clip_analysis.py").read_text(encoding="utf-8")
    selector_source = (root / "engine" / "shot_selector.py").read_text(encoding="utf-8")
    beat_keys = _dict_literal_keys(beat_source, "analyze_track")
    clip_keys = _dict_literal_keys(clip_source, "classify_clip")

    # --- B06: the energy curve carries the time base it was measured on ------
    envelope = beat.energy_envelope([0.0, 0.5, 1.0, 0.25], 22050, 512, 2048)
    times = list(envelope.get("energy_times") or [])
    values = list(envelope.get("energy") or [])
    step = 512.0 / 22050.0
    time_base_exact = len(times) == len(values) == 4 and all(
        abs(times[index] - index * step) <= 1e-3 for index in range(len(times))
    )
    nan_envelope = beat.energy_envelope([float("nan"), 1.0], 22050, 512, 2048)
    b06_missing = sorted(
        {"energy", "energy_times", "energy_sample_rate", "energy_hop_length"} - beat_keys
    )
    b06_ok = (
        time_base_exact
        and times == sorted(times)
        and len(set(times)) == len(times)
        and float(envelope.get("energy_sample_rate", 0)) == 22050.0
        and int(envelope.get("energy_hop_length", 0)) == 512
        and all(np.isfinite(value) and value >= 0.0 for value in values)
        and nan_envelope.get("energy_nonfinite_samples") == 1
        and all(np.isfinite(value) for value in nan_envelope.get("energy", []))
        and not b06_missing
    )
    findings.append(
        Finding(
            "B06",
            "pass" if b06_ok else "warn",
            "medium",
            "Energy samples carry an emitted, exact time base"
            if b06_ok
            else "Energy samples are emitted without their calculated time base",
            [
                f"energy_envelope reproduces n*hop/sr within 1ms={time_base_exact}",
                f"non_finite_samples_reported={nan_envelope.get('energy_nonfinite_samples')}",
                f"analyze_track_missing_keys={b06_missing}",
            ],
        )
    )

    # --- B09: musical labels carry method and confidence ---------------------
    grid = [index * 0.5 for index in range(32)]
    measured_phase = beat.estimate_downbeat_phase(grid, [1.0 + index * 2.0 for index in range(8)])
    silent_phase = beat.estimate_downbeat_phase(grid, [])
    sample_rate = 22050
    span = np.arange(sample_rate * 4, dtype=np.float64) / sample_rate
    waveform = (0.1 * np.sin(2.0 * np.pi * 220.0 * span)).astype(np.float32)
    waveform[sample_rate : 2 * sample_rate] *= 6.0
    labelled = beat.assign_section_types(
        [
            {"type": "verse", "start": 0.0, "end": 1.0},
            {"type": "chorus", "start": 1.0, "end": 2.0},
            {"type": "verse", "start": 2.0, "end": 3.0},
            {"type": "verse", "start": 3.0, "end": 4.0},
        ],
        waveform,
        sample_rate,
    )
    provenance = beat.label_provenance("unit", 4.0, "claim")
    drop_provenance = beat.drop_label_provenance(labelled)
    label_sources = {str(section.get("label_source")) for section in labelled}
    phase_shifted = selector.plan_cuts(
        grid,
        [{"type": "verse", "start": 0.0, "end": 8.0}],
        {},
        8.0,
        120.0,
        [],
        [],
        [0.5, 2.5, 4.5, 6.5],
    )
    phase_grid = [
        slot["beatTime"]
        for slot in phase_shifted
        if (slot.get("cutProvenance") or {}).get("origin") == "grid"
    ]
    b09_missing = sorted({"labels", "downbeats"} - beat_keys)
    b09_ok = (
        measured_phase["phase"] == 2
        and measured_phase["method"] == "bass_accent_phase"
        and measured_phase["confidence"] > 0.0
        and silent_phase["confidence"] == 0.0
        and silent_phase["method"] == "assumed_first_beat"
        and label_sources <= {"measured", "measured_energy", "positional"}
        and all(
            0.0 <= float(section.get("label_confidence", -1)) <= 1.0
            and section.get("measured_type")
            for section in labelled
        )
        and provenance["confidence"] == 1.0
        and set(provenance) >= {"method", "confidence", "claim"}
        and drop_provenance["method"] == "measured_energy"
        and drop_provenance["candidates"] == 1
        and bool(phase_grid) and phase_grid[0] == 0.5
        and not b09_missing
    )
    findings.append(
        Finding(
            "B09",
            "pass" if b09_ok else "warn",
            "medium",
            "Musical labels carry a measured method and a bounded confidence"
            if b09_ok
            else "Musical labels remain heuristic and carry no confidence/provenance",
            [
                f"accented_phase_recovered={measured_phase['phase']} confidence={measured_phase['confidence']}",
                f"no_accent_evidence_method={silent_phase['method']}",
                f"section_label_sources={sorted(label_sources)}",
                f"drop_label_method={drop_provenance['method']}",
                f"selector_first_measured_downbeat_cut={phase_grid[0] if phase_grid else None}",
                f"analyze_track_missing_keys={b09_missing}",
            ],
        )
    )

    # --- CACHE-BEAT-PROVENANCE: identity moves when the analysis moves -------
    audio_fixture = workspace / "identity-fixture.wav"
    audio_fixture.write_bytes(b"RIFF" + b"\0" * 64)
    beat_identity = beat.analysis_identity()

    def _beat_key() -> str:
        return beat._beat_cache_key(str(audio_fixture))[3]

    base_beat_key = _beat_key()
    beat_config_key = _drifted_key(
        beat, "BASS_MIN_SPACING_SECONDS", beat.BASS_MIN_SPACING_SECONDS + 0.01, _beat_key
    )
    beat_schema_key = _drifted_key(beat, "BEAT_ANALYSIS_SCHEMA_VERSION", "drift", _beat_key)
    beat_hop_key = _drifted_key(
        beat, "ENERGY_HOP_LENGTH", int(beat.ENERGY_HOP_LENGTH) * 2, _beat_key
    )
    beat_identity_ok = (
        {"schema", "code", "config", "dependencies"} <= set(beat_identity)
        and len(str(beat_identity["code"])) == 64
        and bool(beat_identity["dependencies"])
        and _beat_key() == base_beat_key
        and len({base_beat_key, beat_config_key, beat_schema_key, beat_hop_key}) == 4
    )
    findings.append(
        Finding(
            "CACHE-BEAT-PROVENANCE",
            "pass" if beat_identity_ok else "warn",
            "high",
            "Beat cache identity binds schema, code hash, configuration and dependencies"
            if beat_identity_ok
            else "Beat cache identity omits schema, code hash, and analysis configuration",
            [
                f"identity_fields={sorted(beat_identity)}",
                f"distinct_keys_under_drift={len({base_beat_key, beat_config_key, beat_schema_key, beat_hop_key})}/4",
                f"restored_key_stable={_beat_key() == base_beat_key}",
            ],
        )
    )

    # --- C02: the clip cache key binds every analysis setting ----------------
    clip_fixture = workspace / "identity-fixture.mov"
    clip_fixture.write_bytes(b"\0" * 512)
    clip_identity = clip.analysis_identity()

    def _clip_key() -> str:
        return clip._source_identity(str(clip_fixture))[2]

    base_clip_key = _clip_key()
    clip_samples_key = _drifted_key(clip, "ANALYSIS_SAMPLES", clip.ANALYSIS_SAMPLES + 1, _clip_key)
    clip_dimension_key = _drifted_key(
        clip, "ANALYSIS_MAX_DIMENSION", clip.ANALYSIS_MAX_DIMENSION + 1, _clip_key
    )
    clip_window_key = _drifted_key(clip, "ANALYSIS_SAMPLE_WINDOW", (0.0, 1.0), _clip_key)
    clip_schema_key = _drifted_key(clip, "ANALYSIS_SCHEMA_VERSION", "drift", _clip_key)
    face_root = workspace / "face-model"
    face_root.with_suffix(".prototxt").write_bytes(b"proto-v1")
    face_root.with_suffix(".caffemodel").write_bytes(b"weights-v1")
    original_face_model = os.environ.get("FLAGSHIPEDITOR_FACE_MODEL")
    try:
        os.environ["FLAGSHIPEDITOR_FACE_MODEL"] = str(face_root)
        face_model_key_v1 = _clip_key()
        face_model_file = face_root.with_suffix(".caffemodel")
        face_model_stat = face_model_file.stat()
        face_model_file.write_bytes(b"weights-v2")
        os.utime(
            face_model_file,
            ns=(face_model_stat.st_atime_ns, face_model_stat.st_mtime_ns),
        )
        face_model_key_v2 = _clip_key()
    finally:
        if original_face_model is None:
            os.environ.pop("FLAGSHIPEDITOR_FACE_MODEL", None)
        else:
            os.environ["FLAGSHIPEDITOR_FACE_MODEL"] = original_face_model
    face_model_bound = face_model_key_v1 != face_model_key_v2
    distinct_clip_keys = len(
        {base_clip_key, clip_samples_key, clip_dimension_key, clip_window_key, clip_schema_key}
    )
    clip_identity_ok = (
        {"schema", "code", "config", "tools", "dependencies"} <= set(clip_identity)
        and len(str(clip_identity["code"])) == 64
        and {"ffmpeg", "ffprobe"} <= set(clip_identity["tools"])
        and _clip_key() == base_clip_key
        and distinct_clip_keys == 5
        and face_model_bound
    )
    findings.append(
        Finding(
            "C02",
            "pass" if clip_identity_ok else "warn",
            "high",
            "Clip cache identity binds schema, code, sampling config and tool identity"
            if clip_identity_ok
            else "Clip cache key does not bind every analysis setting/tool identity",
            [
                f"identity_fields={sorted(clip_identity)}",
                f"tool_identities={sorted(clip_identity.get('tools', {}))}",
                f"distinct_keys_under_drift={distinct_clip_keys}/5",
                f"same_path_face_model_replacement_moves_key={face_model_bound}",
            ],
        )
    )

    # --- C06: face results say which detector produced them ------------------
    blank_frame = np.zeros((64, 64, 3), dtype=np.uint8)
    face = clip.detect_faces([blank_frame])
    empty_face = clip.detect_faces([])
    detection_volume = np.zeros((1, 1, 2, 7), dtype=np.float32)
    detection_volume[0, 0, 0] = [0.0, 1.0, 0.9, 0.25, 0.25, 0.75, 0.75]
    detection_volume[0, 0, 1] = [0.0, 1.0, 0.2, 0.0, 0.0, 1.0, 1.0]
    boxes = clip._dnn_face_boxes(detection_volume, 100, 100)
    original_cascade = clip.cv2.CascadeClassifier
    cascade_loads = 0

    class _StubCascade:
        def empty(self):
            return False

        def detectMultiScale(self, *_args, **_kwargs):
            return []

    def _counted_cascade(*_args, **_kwargs):
        nonlocal cascade_loads
        cascade_loads += 1
        return _StubCascade()

    try:
        clip._FACE_DETECTOR_LOCAL.cache = {}
        clip.cv2.CascadeClassifier = _counted_cascade
        cached_face_first = clip.detect_faces([blank_frame])
        cached_face_second = clip.detect_faces([blank_frame])
    finally:
        clip.cv2.CascadeClassifier = original_cascade
        clip._FACE_DETECTOR_LOCAL.cache = {}
    c06_missing = sorted(
        {"face_detector", "face_detector_fallback", "face_detector_confidence_kind"}
        - clip_keys
    )
    c06_ok = (
        str(face.get("face_detector", "")) in {"dnn_caffe", "haar_cascade", "unavailable"}
        and "face_detector_fallback" in face
        and bool(face["has_face"]) == (float(face["face_size_ratio"]) > 0.0)
        and 0.0 <= float(face["face_consistency"]) <= 1.0
        and 0.0 <= float(face["face_detector_confidence"]) <= 1.0
        and face.get("face_detector_confidence_kind") in {"detector_score", "unavailable"}
        and cached_face_first["face_detector_confidence"] == 0.0
        and cached_face_first["face_detector_confidence_kind"] == "unavailable"
        and cached_face_second["face_detector"] == "haar_cascade"
        and cascade_loads == 1
        and str(empty_face.get("face_detector", ""))
        and len(boxes) == 1
        and abs(boxes[0][0] - 0.25) < 1e-9
        and not c06_missing
    )
    findings.append(
        Finding(
            "C06",
            "pass" if c06_ok else "warn",
            "medium",
            "Face results record the detector, its confidence and any fallback"
            if c06_ok
            else "Face results omit detector/fallback provenance",
            [
                f"detector={face.get('face_detector')} fallback={face.get('face_detector_fallback')!r}",
                f"has_face_implies_ratio={bool(face['has_face']) == (float(face['face_size_ratio']) > 0.0)}",
                f"dnn_volume_boxes_above_threshold={len(boxes)}",
                f"haar_loads_for_two_clips_same_thread={cascade_loads}",
                f"haar_confidence_kind={cached_face_first.get('face_detector_confidence_kind')}",
                f"classify_clip_missing_keys={c06_missing}",
            ],
        )
    )

    # --- C10: motion is normalized by elapsed source time --------------------
    descriptors = clip.flow_descriptors(_shifted_frames(), timestamps=[0.0, 2.0])
    normalized_exact = bool(descriptors) and all(
        entry.get("magnitude_per_second") is not None
        and abs(entry["magnitude_per_second"] * entry["elapsed"] - entry["magnitude"]) < 1e-9
        for entry in descriptors
    )
    unnormalized = clip.flow_descriptors(_shifted_frames())
    policy = clip.motion_sample_policy("opencv", [0.0, 2.0], descriptors, 10.0)
    opencv_names = _names_used_in(clip_source, "_extract_frames_opencv_timed")
    ffmpeg_names = _names_used_in(clip_source, "_extract_frames_ffmpeg_timed")
    shared_window = (
        "ANALYSIS_SAMPLE_WINDOW" in opencv_names and "ANALYSIS_SAMPLE_WINDOW" in ffmpeg_names
    )
    c10_missing = sorted(
        {"motion_intensity_per_second", "motion_sample_policy", "motion_sample_times"} - clip_keys
    )
    normalized_library = selector.normalize_motion_evidence(
        [
            {
                "path": "/synthetic/raw-high-rate-low.mov",
                "motion_intensity": 90.0,
                "motion_variance": 30.0,
                "motion_intensity_per_second": 5.0,
                "motion_variance_per_second": 1.0,
                "motion_sample_policy": {"elapsed_normalized": True},
            },
            {
                "path": "/synthetic/raw-low-rate-high.mov",
                "motion_intensity": 5.0,
                "motion_variance": 1.0,
                "motion_intensity_per_second": 50.0,
                "motion_variance_per_second": 10.0,
                "motion_sample_policy": {"elapsed_normalized": True},
            },
        ]
    )
    rate_consumed = (
        normalized_library[1]["_selector_motion_intensity"]
        > normalized_library[0]["_selector_motion_intensity"]
        and selector.score_clip(normalized_library[1], section_type="drop")["scores"]["energy"]
        > selector.score_clip(normalized_library[0], section_type="drop")["scores"]["energy"]
    )
    untrusted_motion = selector.normalize_motion_evidence(
        [
            {
                "path": "/synthetic/untrusted-rate.mov",
                "motion_intensity": 42.0,
                "motion_intensity_per_second": 999.0,
                "motion_sample_policy": {"elapsed_normalized": False},
            }
        ]
    )[0]
    policy_gate_honored = (
        "_selector_motion_intensity" not in untrusted_motion
        and selector.score_clip(untrusted_motion, section_type="drop")["scores"]["energy"]
        == 25.2
    )
    c10_ok = (
        normalized_exact
        and bool(descriptors) and descriptors[0]["elapsed"] == 2.0
        and all("magnitude_per_second" not in entry for entry in unnormalized)
        and policy["elapsed_normalized"] is True
        and policy["consecutive_frames"] is False
        and list(policy["window"]) == list(clip.ANALYSIS_SAMPLE_WINDOW)
        and shared_window
        and rate_consumed
        and policy_gate_honored
        and not c10_missing
    )
    findings.append(
        Finding(
            "C10",
            "pass" if c10_ok else "warn",
            "high",
            "Motion evidence is normalized by elapsed source time and declares its sampling policy"
            if c10_ok
            else "Sparse optical-flow values are not normalized by elapsed source time/decoder policy",
            [
                f"magnitude_per_second_times_elapsed_equals_magnitude={normalized_exact}",
                f"both_decoders_share_sample_window={shared_window}",
                f"policy_declares_normalization={policy['elapsed_normalized']}",
                f"selector_prefers_higher_rate_over_higher_raw_displacement={rate_consumed}",
                f"selector_rejects_unverified_rate_fields={policy_gate_honored}",
                f"classify_clip_missing_keys={c10_missing}",
            ],
        )
    )

    # --- UNUSED_SIGNAL: the selector consumes phrases and the energy curve ---
    signal_beats = [index * 0.5 for index in range(48)]
    signal_sections = [
        {"type": "verse", "start": 0.0, "end": 12.0},
        {"type": "chorus", "start": 12.0, "end": 24.0},
    ]
    without_phrases = selector.plan_cuts(signal_beats, signal_sections, {}, 24.0, 120.0, [])
    with_phrases = selector.plan_cuts(
        signal_beats, signal_sections, {}, 24.0, 120.0, [], [4.0, 8.0, 16.0]
    )

    def _origins(slots: Sequence[Mapping[str, Any]]) -> set:
        return {str((slot.get("cutProvenance") or {}).get("origin")) for slot in slots}

    phrase_consumed = "phrase" not in _origins(without_phrases) and "phrase" in _origins(with_phrases)
    with_downbeats = selector.plan_cuts(
        signal_beats,
        signal_sections,
        {},
        24.0,
        120.0,
        [],
        [],
        [0.5 + index * 2.0 for index in range(12)],
    )
    grid_without = [
        slot["beatTime"]
        for slot in without_phrases
        if (slot.get("cutProvenance") or {}).get("origin") == "grid"
    ]
    grid_with = [
        slot["beatTime"]
        for slot in with_downbeats
        if (slot.get("cutProvenance") or {}).get("origin") == "grid"
    ]
    downbeats_consumed = bool(grid_with) and grid_with != grid_without

    def _energy_clip(index: int, energy_score: float) -> Dict[str, Any]:
        histogram = [0.0] * 32
        histogram[index] = 1.0
        return {
            "path": f"/synthetic/energy-{index}.mov",
            "name": f"energy-{index}.mov",
            "duration": 12.0,
            "scene_type": "performance",
            "usable": True,
            "energy_score": energy_score,
            "motion_intensity": 10.0,
            "motion_variance": 1.0,
            "composition_score": 60.0,
            "sharpness_score": 60.0,
            "brightness_stability": 80.0,
            "histogram": histogram,
        }

    energy_clips = [_energy_clip(0, 5.0), _energy_clip(1, 95.0)]
    energy_times = [index * 24.0 / 480.0 for index in range(480)]
    loud_first = [1.0] * 240 + [0.05] * 240
    quiet_first = [0.05] * 240 + [1.0] * 240
    selection_loud = selector.select_best_clips(
        energy_clips, signal_beats, signal_sections, {}, 24.0, 120.0, [],
        energy=loud_first, energy_times=energy_times,
    )
    selection_quiet = selector.select_best_clips(
        energy_clips, signal_beats, signal_sections, {}, 24.0, 120.0, [],
        energy=quiet_first, energy_times=energy_times,
    )
    selection_none = selector.select_best_clips(
        energy_clips, signal_beats, signal_sections, {}, 24.0, 120.0, []
    )
    loud_paths = [entry["clipPath"] for entry in selection_loud]
    quiet_paths = [entry["clipPath"] for entry in selection_quiet]
    energy_consumed = bool(loud_paths) and loud_paths != quiet_paths
    energy_declared = (
        bool(selection_loud)
        and selection_loud[0]["cutProvenance"]["energySource"] == "measured_curve"
        and bool(selection_none)
        and selection_none[0]["cutProvenance"]["energySource"] == "section_default"
    )
    unused = []
    if not phrase_consumed:
        unused.append("beat.phrase_boundaries")
    if not downbeats_consumed:
        unused.append("beat.downbeats")
    if not (energy_consumed and energy_declared):
        unused.append("beat.energy")
    if '"energy_score"' in clip_source and 'get("energy_score"' not in selector_source:
        unused.append("clip.energy_score")
    if not rate_consumed:
        unused.append("clip.motion_intensity_per_second")
    findings.append(
        Finding(
            "UNUSED_SIGNAL",
            "warn" if unused else "pass",
            "medium",
            "Signals are emitted by upstream engines but ignored by selector"
            if unused
            else "Every audited upstream signal changes selector output when supplied",
            unused
            or [
                f"phrase_boundaries_create_cuts={phrase_consumed}",
                f"downbeats_shift_bar_grid={downbeats_consumed}",
                f"energy_curve_changes_selection={energy_consumed}",
                f"normalized_motion_changes_ranking={rate_consumed}",
                f"energy_source_declared_per_cut={energy_declared}",
            ],
        )
    )

    # --- S12: every cut records where its boundary came from ------------------
    provenance_sections = [
        {"type": "intro", "start": 0.0, "end": 4.0},
        {"type": "verse", "start": 4.0, "end": 12.0},
        {"type": "drop", "start": 12.0, "end": 20.0},
        {"type": "outro", "start": 20.0, "end": 24.0},
    ]
    provenance_onsets = [12.25, 13.0, 14.25, 16.0, 18.25]
    provenance_slots = selector.plan_cuts(
        signal_beats, provenance_sections, {}, 24.0, 120.0, provenance_onsets, [8.0]
    )
    section_starts = {round(float(section["start"]), 6) for section in provenance_sections}
    every_slot_traced = bool(provenance_slots) and all(
        (slot.get("cutProvenance") or {}).get("origin") in selector.CUT_ORIGINS
        for slot in provenance_slots
    )
    boundaries_traced = all(
        slot["cutProvenance"]["origin"] == "boundary"
        for slot in provenance_slots
        if round(float(slot["beatTime"]), 6) in section_starts
    )
    onset_slots = [
        slot for slot in provenance_slots if slot["cutProvenance"]["origin"] == "onset"
    ]
    onsets_traced = bool(onset_slots) and all(
        slot["cutProvenance"]["sourceTime"] in provenance_onsets
        and abs(float(slot["cutProvenance"]["snapDelta"])) <= float(slot["cutProvenance"]["snapTolerance"])
        for slot in onset_slots
    )
    beat_claims_hold = all(
        (not slot["cutProvenance"]["beatAligned"])
        or float(slot["cutProvenance"]["beatDelta"]) <= float(slot["cutProvenance"]["snapTolerance"])
        for slot in provenance_slots
    )
    source_evidence_complete = all(
        slot["cutProvenance"].get("sourceTime") is not None
        and slot["cutProvenance"].get("snapDelta") is not None
        and abs(
            float(slot["beatTime"])
            - float(slot["cutProvenance"]["sourceTime"])
            - float(slot["cutProvenance"]["snapDelta"])
        ) < 1e-6
        for slot in provenance_slots
    )
    selection_traced = bool(selection_loud) and all(
        (entry.get("cutProvenance") or {}).get("origin") in selector.CUT_ORIGINS
        for entry in selection_loud
    )
    s12_ok = (
        every_slot_traced
        and boundaries_traced
        and onsets_traced
        and beat_claims_hold
        and source_evidence_complete
        and selection_traced
    )
    findings.append(
        Finding(
            "S12",
            "pass" if s12_ok else "warn",
            "medium",
            "Every cut records the boundary/onset/phrase/grid evidence behind it"
            if s12_ok
            else "Final cuts do not record boundary/onset/grid provenance after arbitration",
            [
                f"slots_with_declared_origin={every_slot_traced}",
                f"section_boundaries_traced={boundaries_traced}",
                f"onset_cuts_match_input_onsets={onsets_traced} count={len(onset_slots)}",
                f"beat_aligned_claims_within_tolerance={beat_claims_hold}",
                f"all_origins_reconstruct_from_source_time_and_snap={source_evidence_complete}",
                f"selection_carries_provenance={selection_traced}",
            ],
        )
    )
    return findings


def known_gap_audit(root: Path) -> List[Finding]:
    """Expose the cross-language and scope limitations that remain.

    The engine-level gaps this used to search source text for are now verified
    by running the engines in ``resolved_gap_audit``. What is left here is the
    selector-to-After-Effects boundary, which spans three languages and cannot
    be executed locally, and the scope boundary of a v1 preflight.
    """
    findings: List[Finding] = []
    selector_path = root / "engine" / "shot_selector.py"
    app_path = root / "src" / "js" / "main" / "App.tsx"
    client_path = root / "src" / "js" / "main" / "lib" / "python.ts"
    renderer_path = root / "src" / "jsx" / "aeft" / "aeft.ts"
    required = (selector_path, app_path, client_path, renderer_path)
    missing = [relative(path, root) for path in required if not path.is_file()]
    if missing:
        return [
            Finding(
                "S13",
                "fail",
                "critical",
                "Selector-to-renderer audit surfaces are missing",
                missing,
            )
        ]

    selector = selector_path.read_text(encoding="utf-8")
    app = app_path.read_text(encoding="utf-8")
    client = client_path.read_text(encoding="utf-8")
    renderer = renderer_path.read_text(encoding="utf-8")

    app_payload = _interface_body(app, "TimelineCutPayload")
    client_cut = _interface_body(client, "CutDecision")
    renderer_cut = _interface_body(renderer, "TimelineCut")
    selector_emits_source = 'best["sourceStart"]' in selector and 'best["sourceEnd"]' in selector
    app_carries_source = "sourceStart" in app_payload and "sourceEnd" in app_payload
    client_carries_source = "sourceStart" in client_cut and "sourceEnd" in client_cut
    renderer_carries_source = "sourceStart" in renderer_cut and "sourceEnd" in renderer_cut
    append_start = renderer.find("export function appendCutBatch")
    append_end = renderer.find("export function finishComp", append_start)
    append_body = renderer[append_start:append_end]
    renderer_applies_source = "cut.sourceStart" in append_body and (
        "startTime" in append_body or "timeRemap" in append_body
    )
    renderer_ok = (
        selector_emits_source
        and app_carries_source
        and client_carries_source
        and renderer_carries_source
        and renderer_applies_source
    )
    findings.append(
        Finding(
            "S13",
            "pass" if renderer_ok else "fail",
            "critical",
            "Selector best-moment source window reaches and is applied by After Effects" if renderer_ok else "Selector sourceStart/sourceEnd are dropped before rendering; best moment is not applied",
            [
                f"engine/shot_selector.py:{_line_of(selector, 'best[\"sourceStart\"]')} selector emits sourceStart",
                f"src/js/main/lib/python.ts:{_line_of(client, 'export interface CutDecision')} CutDecision source fields={client_carries_source}",
                f"src/js/main/App.tsx:{_line_of(app, 'interface TimelineCutPayload')} payload source fields={app_carries_source}",
                f"src/js/main/App.tsx:{_line_of(app, 'function toPayload')} serialization drops source fields={not app_carries_source}",
                f"src/jsx/aeft/aeft.ts:{_line_of(renderer, 'interface TimelineCut extends')} renderer contract source fields={renderer_carries_source}",
                f"src/jsx/aeft/aeft.ts:{_line_of(renderer, 'clipLayer.startTime = cut.beatTime')} renderer source offset applied={renderer_applies_source}",
            ],
        )
    )

    for check_id, claim in (
        ("ROADMAP-REAL-MEDIA", "Real-media decoder and semantic accuracy are not exercised by preflight"),
        ("ROADMAP-CACHE-REPLAY", "Cached-vs-uncached semantic equality is not exercised by preflight"),
        ("ROADMAP-NATIVE-AE", "Native Windows/After Effects composition inspection is not exercised"),
        ("ROADMAP-ARTISTIC", "Artistic quality has no labelled fixtures or blind human validation"),
        ("ROADMAP-NETWORK-SANDBOX", "The protocol performs no network calls, but child tests are not kernel-level network-sandboxed"),
        ("ROADMAP-PROCESS-CONTAINMENT", "Child output is buffered and timeout handling does not guarantee termination of descendant processes"),
        ("ROADMAP-TS-PARSER", "The S13 contract uses multi-boundary source inspection, not a TypeScript AST parser or native AE execution"),
    ):
        findings.append(Finding(check_id, "warn", "info", claim, ["v1 preflight scope boundary"]))
    return findings


def _isolated_environment(temp_root: Path) -> Dict[str, str]:
    allowed = (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "LANG",
        "LC_ALL",
        "TZ",
    )
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.update(
        {
            "HOME": str(temp_root / "home"),
            "TMPDIR": str(temp_root / "tmp"),
            "FLAGSHIPEDITOR_CACHE": str(temp_root / "cache"),
            "FLAGSHIPEDITOR_THUMBNAILS": str(temp_root / "thumbnails"),
            "FLAGSHIPEDITOR_JOBS_DB": str(temp_root / "jobs.sqlite3"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        }
    )
    for directory in (environment["HOME"], environment["TMPDIR"]):
        Path(directory).mkdir(parents=True, exist_ok=True)
    return environment


def _bounded_output(value: str, limit: int = 16000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n… [truncated {len(value) - limit} characters; full SHA-256 retained]"


def run_command(
    root: Path,
    name: str,
    command: Sequence[str],
    timeout_seconds: int,
    environment: Mapping[str, str],
) -> CommandEvidence:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command),
            cwd=root,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            timeout=timeout_seconds,
            check=False,
        )
        stdout_raw = completed.stdout or b""
        stderr_raw = completed.stderr or b""
        status = "pass" if completed.returncode == 0 else "fail"
        exit_code: Optional[int] = completed.returncode
        timed_out = False
    except subprocess.TimeoutExpired as error:
        stdout_raw = error.stdout or b""
        stderr_raw = error.stderr or b""
        if isinstance(stdout_raw, str):
            stdout_raw = stdout_raw.encode()
        if isinstance(stderr_raw, str):
            stderr_raw = stderr_raw.encode()
        status = "fail"
        exit_code = None
        timed_out = True
        stderr_raw += f"\nProtocol timeout after {timeout_seconds}s".encode()
    duration_ms = int((time.monotonic() - started) * 1000)
    stdout = stdout_raw.decode("utf-8", errors="replace")
    stderr = stderr_raw.decode("utf-8", errors="replace")
    return CommandEvidence(
        name=name,
        command=list(command),
        status=status,
        exit_code=exit_code,
        duration_ms=duration_ms,
        stdout_sha256=sha256_bytes(stdout_raw),
        stderr_sha256=sha256_bytes(stderr_raw),
        stdout=_bounded_output(stdout),
        stderr=_bounded_output(stderr),
        timed_out=timed_out,
    )


def tracked_snapshot(root: Path) -> Dict[str, Any]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "engine", "scripts", "src/js/main", "src/jsx/aeft", "styles"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    files: Dict[str, str] = {}
    if completed.returncode == 0:
        for raw in completed.stdout.split(b"\0"):
            if not raw:
                continue
            path_text = raw.decode("utf-8", errors="surrogateescape")
            path = root / path_text
            files[path_text] = sha256_file(path) if path.is_file() else "missing"
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=no", "--", "engine", "scripts", "src/js/main", "src/jsx/aeft", "styles"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=15,
        check=False,
    )
    return {"files": files, "git_status": status.stdout if status.returncode == 0 else "unavailable"}


def run_existing_tests(
    root: Path,
    level: str,
    python_runtime: Path,
) -> Tuple[List[CommandEvidence], Finding]:
    before = tracked_snapshot(root)
    if level == "none":
        return [], Finding(
            "TEST-MUTATION",
            "pass",
            "info",
            "No child test ran; tracked source snapshot remained unchanged",
            [f"tracked_files={len(before['files'])}"],
        )
    selected = ["engine-contracts", "server-health"]
    if level == "full":
        selected.insert(1, "analysis-jobs")
    results: List[CommandEvidence] = []
    with tempfile.TemporaryDirectory(prefix="flagship-forensic-tests-") as directory:
        environment = _isolated_environment(Path(directory))
        for name in selected:
            command = tuple(
                str(python_runtime) if value == "{python}" else value
                for value in EXISTING_TESTS[name]
            )
            results.append(
                run_command(root, name, command, 120, environment)
            )
    after = tracked_snapshot(root)
    changed = sorted(
        path
        for path in set(before["files"]) | set(after["files"])
        if before["files"].get(path) != after["files"].get(path)
    )
    status_changed = before["git_status"] != after["git_status"]
    mutation = Finding(
        "TEST-MUTATION",
        "fail" if changed or status_changed else "pass",
        "critical" if changed or status_changed else "info",
        "Child tests mutated tracked project state" if changed or status_changed else "Child tests left all tracked engine/test/render files bit-identical",
        [
            f"tracked_files={len(before['files'])}",
            f"changed={changed}",
            f"git_status_changed={status_changed}",
        ],
    )
    return results, mutation


def _synthetic_clips(count: int = 8) -> List[Dict[str, Any]]:
    scene_types = (
        "performance",
        "close_up",
        "b_roll_dynamic",
        "b_roll_static",
        "b_roll_low_light",
        "b_roll_with_face",
        "b_roll",
        "performance",
    )
    clips = []
    for index in range(count):
        histogram = [0.0] * 32
        histogram[index % 32] = 1.0
        clips.append(
            {
                "path": f"/synthetic/clip-{index}.mov",
                "name": f"clip-{index}.mov",
                "duration": 12.0 + index,
                "scene_type": scene_types[index % len(scene_types)],
                "has_face": index % 3 != 2,
                "face_size_ratio": 0.05 + index * 0.015,
                "face_consistency": 0.2 + (index % 4) * 0.2,
                "brightness_stability": 72.0 + index,
                "motion_intensity": 2.0 + index * 2.5,
                "motion_variance": 0.5 + index * 0.6,
                "composition_score": 60.0 + index * 3.0,
                "sharpness_score": 70.0 + index * 2.0,
                "histogram": histogram,
                "thumbnail_id": f"synthetic-{index}",
                "usable": True,
                "width": 1920,
                "height": 1080,
                "fps": 30.0,
                "best_moment": {"best_time": 5.0 + index * 0.2},
            }
        )
    return clips


def run_cross_engine_invariants(root: Path) -> Tuple[List[Finding], Dict[str, Any]]:
    findings: List[Finding] = []
    metrics: Dict[str, Any] = {}
    runtime_temp = tempfile.TemporaryDirectory(prefix="flagship-forensic-invariants-")
    runtime_root = Path(runtime_temp.name)
    isolated_values = {
        "FLAGSHIPEDITOR_CACHE": str(runtime_root / "cache"),
        "FLAGSHIPEDITOR_THUMBNAILS": str(runtime_root / "thumbnails"),
        "FLAGSHIPEDITOR_JOBS_DB": str(runtime_root / "jobs.sqlite3"),
    }
    previous_environment = {key: os.environ.get(key) for key in isolated_values}
    previous_dont_write_bytecode = sys.dont_write_bytecode
    os.environ.update(isolated_values)
    sys.dont_write_bytecode = True
    engine_path = str(root / "engine")
    inserted = False
    if engine_path not in sys.path:
        sys.path.insert(0, engine_path)
        inserted = True
    module_names = ("beat_analysis", "clip_analysis", "shot_selector")
    previous_modules = {name: sys.modules.get(name) for name in module_names}
    for name in module_names:
        sys.modules.pop(name, None)
    try:
        beat = importlib.import_module("beat_analysis")
        clip = importlib.import_module("clip_analysis")
        selector = importlib.import_module("shot_selector")

        # The engine-level evidence gaps are verified by running the engines,
        # not by searching their source for a spelling.
        findings.extend(resolved_gap_audit(root, beat, clip, selector, runtime_root))

        expected_section_types = {"intro", "verse", "chorus", "drop", "bridge", "outro"}
        weighted_types = set(selector.SECTION_WEIGHTS)
        affinity_types = set(selector.SECTION_SCENE_AFFINITY)
        section_gap = sorted(expected_section_types - weighted_types)
        affinity_gap = sorted(expected_section_types - affinity_types)
        weight_sums = {
            section: round(sum(float(value) for value in weights.values()), 12)
            for section, weights in sorted(selector.SECTION_WEIGHTS.items())
        }
        invalid_weights = {
            section: total for section, total in weight_sums.items() if abs(total - 1.0) > 1e-9
        }
        section_ok = not section_gap and not affinity_gap and not invalid_weights
        findings.append(
            Finding(
                "section-contract",
                "pass" if section_ok else "fail",
                "critical" if not section_ok else "info",
                "Beat/clip/selector section vocabulary is aligned" if section_ok else "Section vocabulary or weights drifted",
                [
                    f"required={sorted(expected_section_types)}",
                    f"missing_weights={section_gap}",
                    f"missing_affinities={affinity_gap}",
                    f"weight_sums={weight_sums}",
                ],
            )
        )

        import numpy as np

        frames = [
            np.zeros((72, 128, 3), dtype=np.uint8),
            np.full((72, 128, 3), 180, dtype=np.uint8),
        ]
        visual = clip.compute_visual_scores(frames, motion=4.0)
        required_visual = {"composition_score", "energy_score", "sharpness_score", "histogram"}
        visual_ok = required_visual.issubset(visual) and len(visual.get("histogram", [])) == 32
        visual_ok = visual_ok and abs(sum(visual.get("histogram", [])) - 1.0) < 1e-9
        findings.append(
            Finding(
                "clip-selector-feature-contract",
                "pass" if visual_ok else "fail",
                "critical" if not visual_ok else "info",
                "Clip features satisfy selector input contracts" if visual_ok else "Clip feature contract failed",
                [f"keys={sorted(visual)}", f"histogram_bins={len(visual.get('histogram', []))}"],
            )
        )

        duration = 24.0
        tempo = 120.0
        beats = [index * 0.5 for index in range(48)]
        sections = [
            {"type": "intro", "start": 0.0, "end": 4.0},
            {"type": "verse", "start": 4.0, "end": 12.0},
            {"type": "drop", "start": 12.0, "end": 20.0},
            {"type": "outro", "start": 20.0, "end": 24.0},
        ]
        bass_onsets = [12.25, 13.0, 14.25, 16.0, 18.25]
        style = {
            "cut_strategy": {
                "intro": {"cut_interval": "4_beats"},
                "verse": {"cut_interval": "4_beats"},
                "drop": {"cut_interval": "1_beat", "double_time_on_808": False},
                "outro": {"cut_interval": "4_beats"},
            }
        }
        slots = selector.plan_cuts(beats, sections, style, duration, tempo, bass_onsets)
        slots_again = selector.plan_cuts(beats, sections, style, duration, tempo, bass_onsets)
        boundaries = {section["start"] for section in sections}
        slot_starts = {float(slot["beatTime"]) for slot in slots}
        contiguous = bool(slots) and abs(float(slots[0]["beatTime"])) < 1e-9
        contiguous = contiguous and abs(float(slots[-1]["endTime"]) - duration) < 1e-9
        contiguous = contiguous and all(
            abs(float(left["endTime"]) - float(right["beatTime"])) < 1e-9
            for left, right in zip(slots, slots[1:])
        )
        min_length = min(
            (float(slot["endTime"]) - float(slot["beatTime"]) for slot in slots),
            default=0.0,
        )
        timeline_ok = (
            slots == slots_again
            and boundaries.issubset(slot_starts)
            and contiguous
            and min_length >= float(selector.MIN_CUT_SECONDS) - 1e-9
        )
        findings.append(
            Finding(
                "timeline-invariants",
                "pass" if timeline_ok else "fail",
                "critical" if not timeline_ok else "info",
                "Cut planner is deterministic and tiles the full timeline" if timeline_ok else "Cut timeline invariant failed",
                [
                    f"slot_count={len(slots)}",
                    f"boundary_count={len(boundaries)}",
                    f"minimum_slot_seconds={round(min_length, 6)}",
                    f"contiguous={contiguous}",
                    f"deterministic={slots == slots_again}",
                ],
            )
        )

        clips = _synthetic_clips()
        selected = selector.select_best_clips(
            clips, beats, sections, style, duration, tempo, bass_onsets, seed=7
        )
        selected_again = selector.select_best_clips(
            clips, beats, sections, style, duration, tempo, bass_onsets, seed=7
        )
        selected_third = selector.select_best_clips(
            clips, beats, sections, style, duration, tempo, bass_onsets, seed=7
        )
        paths = [entry.get("clipPath") for entry in selected]
        repeat_violations = sum(
            1
            for index, path in enumerate(paths)
            if path in paths[max(0, index - int(selector.REPEAT_WINDOW)):index]
        )
        selection_ok = (
            len(selected) == len(slots)
            and selected == selected_again
            and selected == selected_third
        )
        selection_ok = selection_ok and repeat_violations == 0
        valid_paths = {item["path"] for item in clips}
        clip_durations = {item["path"]: float(item["duration"]) for item in clips}
        score_keys = {"composition", "energy", "variety", "sharpness", "stability", "face_quality"}
        source_window_failures = []
        score_failures = []
        alternative_failures = []
        for entry in selected:
            path = entry.get("clipPath")
            source_start = float(entry.get("sourceStart", -1))
            source_end = float(entry.get("sourceEnd", -1))
            target_span = float(entry.get("endTime", 0)) - float(entry.get("beatTime", 0))
            clip_duration = clip_durations.get(path, -1.0)
            if not (
                0.0 <= source_start <= source_end <= clip_duration + 1e-9
                and source_end - source_start >= target_span - 1e-9
            ):
                source_window_failures.append(path)
            component_scores = entry.get("scores") or {}
            if set(component_scores) != score_keys or not all(
                isinstance(value, (int, float))
                and np.isfinite(value)
                and 0.0 <= float(value) <= 100.0
                for value in component_scores.values()
            ) or not (0.0 <= float(entry.get("score", -1)) <= 100.0):
                score_failures.append(path)
            alternatives = entry.get("alternatives") or []
            alternative_paths = [item.get("clipPath") for item in alternatives]
            if (
                path in alternative_paths
                or len(alternative_paths) != len(set(alternative_paths))
                or any(item not in valid_paths for item in alternative_paths)
                or any(
                    not isinstance(item.get("score"), (int, float))
                    or not np.isfinite(item.get("score"))
                    or not 0.0 <= float(item.get("score")) <= 100.0
                    for item in alternatives
                )
            ):
                alternative_failures.append(path)
        selection_ok = selection_ok and not (
            source_window_failures or score_failures or alternative_failures
        )
        findings.append(
            Finding(
                "selection-invariants",
                "pass" if selection_ok else "fail",
                "critical" if not selection_ok else "info",
                "Selector output is deterministic, bounded, and non-repeating" if selection_ok else "Selector output invariant failed",
                [
                    f"selection_count={len(selected)}",
                    f"slot_count={len(slots)}",
                    f"repeat_violations={repeat_violations}",
                    f"three_run_deterministic={selected == selected_again == selected_third}",
                    f"source_window_failures={source_window_failures}",
                    f"score_failures={score_failures}",
                    f"alternative_failures={alternative_failures}",
                ],
            )
        )

        duplicate_clips = clips + [dict(clips[0])]
        duplicate_rejected = False
        try:
            duplicate_output = selector.select_best_clips(
                duplicate_clips, beats, sections, style, duration, tempo, bass_onsets, seed=7
            )
        except (TypeError, ValueError):
            duplicate_rejected = True
            duplicate_output = []
        findings.append(
            Finding(
                "S04-DUPLICATE-IDENTITY",
                "pass" if duplicate_rejected else "fail",
                "critical" if not duplicate_rejected else "info",
                "Duplicate clip identities are explicitly rejected" if duplicate_rejected else "Selector silently accepts duplicate clip paths and corrupts identity accounting",
                [
                    f"input_count={len(duplicate_clips)}",
                    f"unique_paths={len({item['path'] for item in duplicate_clips})}",
                    f"output_count={len(duplicate_output)}",
                ],
            )
        )

        phrase_beats = [index * 0.5 for index in range(128)]
        phrase_sections = [
            {"type": "verse", "start": 0.0, "end": 32.0},
            {"type": "chorus", "start": 32.0, "end": 64.0},
        ]
        phrase_downbeats = [0.5 + index * 2.0 for index in range(32)]
        phrase_boundaries = beat.detect_phrase_boundaries(
            phrase_beats, tempo, phrase_sections, phrase_downbeats
        )
        phrase_times = [float(item["time"]) for item in phrase_boundaries]
        phrase_ok = (
            bool(phrase_times)
            and phrase_times[0] == 8.5
            and phrase_times == sorted(phrase_times)
            and all(0.0 <= value <= 64.0 for value in phrase_times)
        )
        findings.append(
            Finding(
                "beat-selector-time-contract",
                "pass" if phrase_ok else "fail",
                "high" if not phrase_ok else "info",
                "Beat-derived phrase times are ordered and bounded" if phrase_ok else "Beat time contract failed",
                [
                    f"phrase_boundary_count={len(phrase_times)}",
                    f"first_phrase_anchored_to_measured_downbeat={phrase_times[0] if phrase_times else None}",
                ],
            )
        )

        metrics = {
            "section_weight_sums": weight_sums,
            "visual_feature_keys": sorted(visual),
            "visual_histogram_bins": len(visual.get("histogram", [])),
            "slot_count": len(slots),
            "slot_sha256": canonical_hash(slots),
            "selection_count": len(selected),
            "selection_sha256": canonical_hash(selected),
            "selection_three_run_equal": selected == selected_again == selected_third,
            "duplicate_identity_rejected": duplicate_rejected,
            "phrase_boundary_count": len(phrase_times),
            "phrase_boundaries_sha256": canonical_hash(phrase_times),
        }
    except Exception as error:
        findings.append(
            Finding(
                "cross-engine-runtime",
                "fail",
                "critical",
                f"Cross-engine audit raised {type(error).__name__}: {error}",
                [traceback.format_exc(limit=12)],
            )
        )
    finally:
        for name in module_names:
            sys.modules.pop(name, None)
            if previous_modules[name] is not None:
                sys.modules[name] = previous_modules[name]
        if inserted:
            try:
                sys.path.remove(engine_path)
            except ValueError:
                pass
        sys.dont_write_bytecode = previous_dont_write_bytecode
        for key, previous in previous_environment.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
        runtime_temp.cleanup()
    return findings, metrics


def baseline_payload(
    signatures: Mapping[str, Any],
    contract_metrics: Mapping[str, Any],
    accepted_reason: str,
) -> Dict[str, Any]:
    targets = {
        path: {
            "sha256": detail["sha256"],
            "ast_sha256": detail["ast_sha256"],
        }
        for path, detail in sorted(signatures.items())
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "accepted_at": utc_now(),
        "accepted_reason": accepted_reason,
        "targets": targets,
        "contract_metrics": dict(contract_metrics),
        "contract_sha256": canonical_hash(contract_metrics),
    }


def compare_baseline(
    baseline: Mapping[str, Any],
    signatures: Mapping[str, Any],
    contract_metrics: Mapping[str, Any],
) -> Dict[str, Any]:
    expected_targets = baseline.get("targets") or {}
    current_targets = {
        path: {"sha256": detail["sha256"], "ast_sha256": detail["ast_sha256"]}
        for path, detail in sorted(signatures.items())
    }
    changed = []
    missing = []
    added = []
    for path in sorted(set(expected_targets) | set(current_targets)):
        if path not in current_targets:
            missing.append(path)
        elif path not in expected_targets:
            added.append(path)
        elif expected_targets[path] != current_targets[path]:
            changed.append(
                {
                    "path": path,
                    "expected": expected_targets[path],
                    "actual": current_targets[path],
                }
            )
    expected_contract = str(baseline.get("contract_sha256", ""))
    actual_contract = canonical_hash(contract_metrics)
    return {
        "status": "drift" if changed or missing or added or expected_contract != actual_contract else "match",
        "changed": changed,
        "missing": missing,
        "added": added,
        "contract_expected_sha256": expected_contract,
        "contract_actual_sha256": actual_contract,
        "contract_changed": expected_contract != actual_contract,
    }


def git_evidence(root: Path) -> Dict[str, Any]:
    def run(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "engine_status": run("status", "--short", "--", "engine", "scripts"),
    }


def _status_counts(findings: Iterable[Finding]) -> Dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for finding in findings:
        counts[finding.status] = counts.get(finding.status, 0) + 1
    return counts


def render_markdown(report: Mapping[str, Any]) -> str:
    verdict = report["verdict"]
    lines = [
        "# FlagshipEditor — Cyber-Forensic Engine Report",
        "",
        f"- Verdict: **{verdict['status']}**",
        f"- Exit code: `{verdict['exit_code']}`",
        f"- Generated: `{report['generated_at']}`",
        f"- Protocol: `{report['protocol_version']}`",
        f"- Commit: `{report['provenance'].get('commit') or 'unavailable'}`",
        f"- Network boundary: {sum(len(entries) for entries in report.get('network_boundary', {}).get('unexpected_imports', {}).values())} "
        "undeclared network-capable import(s) measured; see `network_boundary` and Limitations",
        "",
        "## Gate summary",
        "",
        f"- Static/cross-engine checks: {report['summary']['finding_counts']}",
        f"- Existing dynamic tests: {report['summary']['test_counts']}",
        f"- Baseline: `{report['baseline']['status']}`",
        f"- Inventory: {len(report['inventory'])} files hashed with SHA-256",
        "",
        "## Findings",
        "",
    ]
    for finding in report["findings"]:
        marker = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}.get(finding["status"], finding["status"].upper())
        lines.append(f"- **{marker}** `{finding['check']}` — {finding['message']}")
        for evidence in finding.get("evidence", [])[:8]:
            flattened = str(evidence).replace("\n", " ").strip()
            lines.append(f"  - `{flattened}`")
    lines.extend(["", "## Existing dynamic tests", ""])
    if not report["tests"]:
        lines.append("- Not executed by request (`--tests none`).")
    for test in report["tests"]:
        lines.append(
            f"- **{test['status'].upper()}** `{test['name']}` — exit={test['exit_code']}, "
            f"stdout_sha256=`{test['stdout_sha256']}`, stderr_sha256=`{test['stderr_sha256']}`"
        )
    lines.extend(["", "## Baseline drift", ""])
    baseline = report["baseline"]
    lines.append(f"- Status: **{baseline['status']}**")
    for path in baseline.get("missing", []):
        lines.append(f"- Missing: `{path}`")
    for path in baseline.get("added", []):
        lines.append(f"- Added: `{path}`")
    for changed in baseline.get("changed", []):
        lines.append(
            f"- Changed: `{changed['path']}` — expected `{changed['expected']['sha256']}`, "
            f"actual `{changed['actual']['sha256']}`"
        )
    if baseline.get("contract_changed"):
        lines.append(
            f"- Contract fingerprint changed: `{baseline.get('contract_expected_sha256')}` → "
            f"`{baseline.get('contract_actual_sha256')}`"
        )
    lines.extend(["", "## Engine SHA-256", ""])
    inventory_by_path = {item["path"]: item for item in report["inventory"]}
    for path in ENGINE_TARGETS:
        item = inventory_by_path.get(path)
        if item:
            lines.append(f"- `{path}` — `{item['sha256']}` ({item['bytes']} bytes)")
    lines.extend(["", "## Limitations", ""])
    for limitation in report.get("limitations", []):
        lines.append(f"- {limitation}")
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "A PASS proves only the checked source integrity, static gates, synthetic cross-engine "
            "contracts, and local tests listed above. It does not prove subjective edit quality, "
            "native After Effects behavior, real-media accuracy, or claims from the analysis notes "
            "that lack fixtures or human validation.",
            "",
        ]
    )
    return "\n".join(lines)


def write_evidence(output_dir: Path, report: Dict[str, Any]) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    markdown_path = output_dir / "report.md"
    manifest_json_path = output_dir / "manifest.json"
    checks_path = output_dir / "checks.jsonl"
    manifest_path = output_dir / "SHA256SUMS"
    seal_path = output_dir / "SHA256SUMS.sha256"
    json_content = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    markdown_content = render_markdown(report)
    manifest_content = json.dumps(
        {
            "schema_version": report["schema_version"],
            "protocol_version": report["protocol_version"],
            "generated_at": report["generated_at"],
            "runtime": report["runtime"],
            "provenance": report["provenance"],
            "inventory": report["inventory"],
            "baseline_path": report["baseline_path"],
            "baseline_sha256": report["baseline_sha256"],
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    checks_content = "".join(
        json.dumps(item, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        for item in report["findings"]
    )
    atomic_write(json_path, json_content)
    atomic_write(markdown_path, markdown_content)
    atomic_write(manifest_json_path, manifest_content)
    atomic_write(checks_path, checks_content)
    sealed_paths = (checks_path, manifest_json_path, json_path, markdown_path)
    manifest = "".join(f"{sha256_file(path)}  {path.name}\n" for path in sealed_paths)
    atomic_write(manifest_path, manifest)
    atomic_write(seal_path, f"{sha256_file(manifest_path)}  {manifest_path.name}\n")
    return {
        "json": str(json_path),
        "markdown": str(markdown_path),
        "manifest": str(manifest_path),
        "manifest_json": str(manifest_json_path),
        "checks": str(checks_path),
        "seal": str(seal_path),
    }


def verify_seal(output_dir: Path) -> Tuple[bool, List[str]]:
    """Verify every sealed artifact and the checksum-manifest seal."""
    errors: List[str] = []
    manifest_path = output_dir / "SHA256SUMS"
    seal_path = output_dir / "SHA256SUMS.sha256"
    if not manifest_path.is_file() or not seal_path.is_file():
        return False, ["missing SHA256SUMS or SHA256SUMS.sha256"]

    def entries(path: Path) -> List[Tuple[str, str]]:
        parsed = []
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", line)
            if not match:
                errors.append(f"malformed checksum line in {path.name}")
                continue
            parsed.append((match.group(1), match.group(2)))
        return parsed

    for expected, filename in entries(manifest_path):
        artifact = output_dir / filename
        if not artifact.is_file():
            errors.append(f"missing artifact: {filename}")
        elif sha256_file(artifact) != expected:
            errors.append(f"hash mismatch: {filename}")
    seal_entries = entries(seal_path)
    if seal_entries != [(sha256_file(manifest_path), manifest_path.name)]:
        errors.append("SHA256SUMS seal mismatch")
    return not errors, errors


def _write_protocol_error_safely(output_dir: Path, error: BaseException) -> None:
    failure = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": utc_now(),
        "limitations": [
            "The protocol failed before measuring the network boundary; that it performs no network calls itself is a declared scope boundary, not a measured runtime property.",
        ],
        "verdict": {"status": "PROTOCOL_ERROR", "exit_code": EXIT_PROTOCOL_ERROR},
        "error": f"{type(error).__name__}: {error}",
    }
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write(
            output_dir / "protocol-error.json",
            json.dumps(failure, indent=2, sort_keys=True) + "\n",
        )
    except Exception:
        # The original error remains authoritative; never replace it with a
        # secondary reporting-path failure.
        pass


def build_parser(default_root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=default_root)
    parser.add_argument("--output", type=Path, help="Explicit evidence directory (default is a new immutable run directory)")
    parser.add_argument("--overwrite-output", action="store_true", help="Allow replacing an explicit evidence directory; intended for deterministic tests only")
    parser.add_argument("--baseline", type=Path, help="Reviewed baseline JSON (default: engine/forensics/baseline.json)")
    parser.add_argument("--tests", choices=("none", "core", "full"), default="full")
    parser.add_argument("--skip-invariants", action="store_true", help="Fixture/test harness only; never use for release evidence")
    parser.add_argument("--update-baseline", action="store_true", help="Write a reviewed baseline only if all mandatory gates pass")
    parser.add_argument("--accept-baseline", default="", help="Required human-readable reason with --update-baseline")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    default_root = Path(__file__).resolve().parents[1]
    args = build_parser(default_root).parse_args(argv)
    root = args.project_root.resolve()
    baseline_path = (args.baseline or (root / "engine" / "forensics" / "baseline.json")).resolve()
    preliminary_output = (args.output or (root / "engine" / "forensics" / "runs" / run_stamp())).resolve()
    output_dir = preliminary_output
    try:
        if not root.is_dir():
            raise AuditError(f"Project root does not exist: {root}")
        inventory = collect_inventory(root)
        findings, signatures, network_boundary = static_audit(root)
        signatures = expand_integrity_signatures(root, signatures)
        if not args.skip_invariants:
            findings.extend(known_gap_audit(root))
        provenance = git_evidence(root)
        if args.output is None:
            engine_identity = canonical_hash(
                {path: detail["sha256"] for path, detail in sorted(signatures.items())}
            )[:10]
            commit_identity = (provenance.get("commit") or "nogit")[:8]
            output_dir = (
                root / "engine" / "forensics" / "runs" /
                f"{run_stamp()}-{commit_identity}-{engine_identity}"
            ).resolve()
        if output_dir.exists() and not output_dir.is_dir():
            raise AuditError(f"Evidence output exists and is not a directory: {output_dir}")
        if is_nonempty_directory(output_dir) and not args.overwrite_output:
            raise AuditError(
                f"Evidence directory is non-empty and sealed runs are immutable: {output_dir}"
            )
        if args.skip_invariants:
            invariant_findings: List[Finding] = []
            contract_metrics: Dict[str, Any] = {"skipped": True}
        else:
            invariant_findings, contract_metrics = run_cross_engine_invariants(root)
        findings.extend(invariant_findings)
        python_runtime = detect_engine_python(root)
        tests, mutation_finding = run_existing_tests(root, args.tests, python_runtime)
        findings.append(mutation_finding)
        failing_findings = [finding for finding in findings if finding.status == "fail"]
        failing_tests = [test for test in tests if test.status == "fail"]

        if args.update_baseline:
            if not args.accept_baseline.strip():
                raise AuditError("--update-baseline requires --accept-baseline with a review reason")
            if failing_findings or failing_tests:
                raise AuditError("Refusing to update baseline while mandatory gates fail")
            payload = baseline_payload(signatures, contract_metrics, args.accept_baseline.strip())
            atomic_write(
                baseline_path,
                json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
            )

        if baseline_path.is_file():
            baseline_document = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline = compare_baseline(baseline_document, signatures, contract_metrics)
            baseline_sha256 = sha256_file(baseline_path)
        else:
            baseline = {
                "status": "missing",
                "changed": [],
                "missing": [],
                "added": [],
                "contract_expected_sha256": "",
                "contract_actual_sha256": canonical_hash(contract_metrics),
                "contract_changed": False,
            }
            baseline_sha256 = ""
            findings.append(
                Finding(
                    "BASELINE-MISSING",
                    "warn",
                    "high",
                    "No reviewed baseline exists; drift comparison is unavailable",
                    [relative(baseline_path, root)],
                )
            )
            failing_findings = [finding for finding in findings if finding.status == "fail"]

        if failing_findings or failing_tests:
            exit_code = EXIT_FAILURE
            status = "FAIL"
        elif baseline["status"] in {"drift", "missing"} or any(
            finding.status == "warn" for finding in findings
        ):
            exit_code = EXIT_DRIFT
            status = "WARN"
        else:
            exit_code = EXIT_PASS
            status = "PASS"

        finding_counts = _status_counts(findings)
        test_counts = {
            "pass": sum(test.status == "pass" for test in tests),
            "fail": sum(test.status == "fail" for test in tests),
            # Every known dynamic test that this run did not execute, whether
            # skipped by --tests none or excluded by --tests core.
            "not_run": max(0, len(EXISTING_TESTS) - len(tests)),
        }
        report = {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "generated_at": utc_now(),
            "limitations": [
                "No real media fixture is decoded by the forensic cross-engine invariant gate.",
                "No native Windows or After Effects host is exercised.",
                "No subjective edit-quality claim is inferred from passing tests.",
                "Analysis-note claims marked as requiring validation remain unproven.",
                "network_boundary.measured_imports is a static AST measurement; that the protocol itself performs no network calls, and that child tests are not kernel-level network-sandboxed, are declared scope boundaries, not measured runtime properties.",
            ],
            "network_boundary": network_boundary,
            "project": "FlagshipEditor",
            "verdict": {"status": status, "exit_code": exit_code},
            "summary": {
                "finding_counts": finding_counts,
                "test_counts": test_counts,
                "engine_count": sum(path in signatures for path in ENGINE_TARGETS),
                "integrity_target_count": len(signatures),
                "inventory_count": len(inventory),
            },
            "provenance": provenance,
            "runtime": runtime_evidence(python_runtime),
            "inventory": inventory,
            "signatures": signatures,
            "findings": [asdict(finding) for finding in findings],
            "contract_metrics": contract_metrics,
            "tests": [asdict(test) for test in tests],
            "baseline_path": relative(baseline_path, root),
            "baseline_sha256": baseline_sha256,
            "baseline": baseline,
        }
        paths = write_evidence(output_dir, report)
        print(
            json.dumps(
                {
                    "status": status,
                    "exit_code": exit_code,
                    "evidence": {key: str(Path(value).resolve()) for key, value in paths.items()},
                    "finding_counts": finding_counts,
                    "test_counts": test_counts,
                    "baseline": baseline["status"],
                },
                sort_keys=True,
            )
        )
        return exit_code
    except Exception as error:
        output_is_sealed = (
            is_nonempty_directory(output_dir)
            and not args.overwrite_output
        )
        if not output_is_sealed:
            _write_protocol_error_safely(output_dir, error)
        print(f"Cyber-forensic protocol error: {error}", file=sys.stderr)
        return EXIT_PROTOCOL_ERROR


def _reexec_with_engine_runtime(argv: Sequence[str]) -> None:
    """Re-enter through engine/.venv before importing librosa/OpenCV engines."""
    if os.environ.get("FLAGSHIPEDITOR_FORENSIC_RUNTIME") == "1":
        return
    default_root = Path(__file__).resolve().parents[1]
    root = default_root
    if "--project-root" in argv:
        index = list(argv).index("--project-root")
        if index + 1 < len(argv):
            root = Path(argv[index + 1]).resolve()
    runtime = detect_engine_python(root)
    if runtime.resolve() == Path(sys.executable).resolve():
        return
    environment = dict(os.environ)
    environment["FLAGSHIPEDITOR_FORENSIC_RUNTIME"] = "1"
    os.execve(str(runtime), [str(runtime), str(Path(__file__).resolve()), *argv], environment)


if __name__ == "__main__":
    _reexec_with_engine_runtime(sys.argv[1:])
    raise SystemExit(main())
