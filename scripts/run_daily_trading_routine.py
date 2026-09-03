#!/usr/bin/env python3
"""Run the automatable, fail-closed daily trading workflow stages."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import tomllib


def default_timeouts() -> dict[str, int]:
    """Return workload-specific child-process timeouts in seconds."""
    return {
        "market_breadth": 120,
        "uptrend": 120,
        "market_top": 240,
        "macro_regime": 240,
        "exposure": 120,
        "circuit_breaker": 120,
        "vcp": 420,
        "theme": 240,
        "momentum_burst": 420,
        "exhaustion_hammer": 420,
        "canslim": 420,
    }


@dataclass(frozen=True)
class RoutineConfig:
    """Validated local settings for a scheduled routine run."""

    account_size: float
    risk_pct_per_trade: float = 0.5
    max_portfolio_heat_pct: float = 6.0
    state_dir: Path = Path("state/theses")
    output_dir: Path = Path("reports/daily-trading-routine")
    max_market_data_age_days: int = 4
    enable_macro_regime: bool = False
    enable_theme: bool = True
    enable_momentum_burst: bool = False
    enable_exhaustion_hammer: bool = False
    enable_canslim: bool = False
    timeouts: dict[str, int] = field(default_factory=default_timeouts)


@dataclass(frozen=True)
class SkillSpec:
    """Definition of one child skill invocation and its expected artifact."""

    key: str
    name: str
    script: Path
    args: tuple[str, ...]
    artifact_glob: str
    required: bool = True


@dataclass(frozen=True)
class SkillResult:
    """Structured result of invoking one child skill."""

    name: str
    status: str
    artifact: Path | None
    data: dict[str, Any] | list[Any] | None
    warning: str | None = None


@dataclass(frozen=True)
class StageResult:
    """Outcome of one routine stage and its child artifacts."""

    status: str
    decision: str | None = None
    results: dict[str, SkillResult] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    queue: tuple[dict[str, Any], ...] = ()


_CONFIG_KEYS = {
    "account_size",
    "risk_pct_per_trade",
    "max_portfolio_heat_pct",
    "state_dir",
    "output_dir",
    "max_market_data_age_days",
    "enable_macro_regime",
    "enable_theme",
    "enable_momentum_burst",
    "enable_exhaustion_hammer",
    "enable_canslim",
    "timeouts",
}


def _positive_number(value: Any, *, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _boolean(value: Any, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _resolve_path(value: Any, *, name: str, project_root: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty path")
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_root / path


def load_config(path: Path, *, project_root: Path) -> RoutineConfig:
    """Load and validate a local TOML configuration."""
    project_root = project_root.resolve()
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("configuration must be a TOML table")

    unknown = sorted(set(raw) - _CONFIG_KEYS)
    if unknown:
        raise ValueError(f"Unknown config key(s): {', '.join(unknown)}")
    if "account_size" not in raw:
        raise ValueError("account_size is required")

    timeout_values = default_timeouts()
    overrides = raw.get("timeouts", {})
    if not isinstance(overrides, dict):
        raise ValueError("timeouts must be a TOML table")
    unknown_timeouts = sorted(set(overrides) - set(timeout_values))
    if unknown_timeouts:
        raise ValueError(f"Unknown timeout key(s): {', '.join(unknown_timeouts)}")
    for name, value in overrides.items():
        timeout_values[name] = _positive_int(value, name=f"timeouts.{name}")

    return RoutineConfig(
        account_size=_positive_number(raw["account_size"], name="account_size"),
        risk_pct_per_trade=_positive_number(
            raw.get("risk_pct_per_trade", 0.5), name="risk_pct_per_trade"
        ),
        max_portfolio_heat_pct=_positive_number(
            raw.get("max_portfolio_heat_pct", 6.0), name="max_portfolio_heat_pct"
        ),
        state_dir=_resolve_path(
            raw.get("state_dir", "state/theses"), name="state_dir", project_root=project_root
        ),
        output_dir=_resolve_path(
            raw.get("output_dir", "reports/daily-trading-routine"),
            name="output_dir",
            project_root=project_root,
        ),
        max_market_data_age_days=_positive_int(
            raw.get("max_market_data_age_days", 4), name="max_market_data_age_days"
        ),
        enable_macro_regime=_boolean(
            raw.get("enable_macro_regime", False), name="enable_macro_regime"
        ),
        enable_theme=_boolean(raw.get("enable_theme", True), name="enable_theme"),
        enable_momentum_burst=_boolean(
            raw.get("enable_momentum_burst", False), name="enable_momentum_burst"
        ),
        enable_exhaustion_hammer=_boolean(
            raw.get("enable_exhaustion_hammer", False), name="enable_exhaustion_hammer"
        ),
        enable_canslim=_boolean(raw.get("enable_canslim", False), name="enable_canslim"),
        timeouts=timeout_values,
    )


def redacted_config(config: RoutineConfig) -> dict[str, Any]:
    """Return report-safe configuration without account equity."""
    data = asdict(config)
    data.pop("account_size", None)
    data["state_dir"] = str(config.state_dir)
    data["output_dir"] = str(config.output_dir)
    return data


def _redact_text(text: str, sensitive_values: tuple[str, ...]) -> str:
    redacted = text
    for value in sensitive_values:
        if value:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def _sanitize_text(text: str, sensitive_values: tuple[str, ...]) -> str:
    return _redact_text(text, sensitive_values)[:300]


def _redact_json(value: Any, sensitive_values: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_json(item, sensitive_values)
            for key, item in value.items()
            if key != "account_size"
        }
    if isinstance(value, list):
        return [_redact_json(item, sensitive_values) for item in value]
    if isinstance(value, str):
        for sensitive in sensitive_values:
            if sensitive:
                value = value.replace(sensitive, "[REDACTED]")
    return value


def _run_skill(
    spec: SkillSpec,
    project_root: Path,
    output_dir: Path,
    *,
    timeout: int,
    sensitive_values: tuple[str, ...] = (),
) -> SkillResult:
    """Run one child script and parse its newest matching JSON artifact."""
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_args = tuple(arg.replace("{output_dir}", str(output_dir)) for arg in spec.args)
    script = spec.script if spec.script.is_absolute() else project_root / spec.script
    command = [sys.executable, str(script), *resolved_args]

    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SkillResult(
            spec.name,
            "timeout",
            None,
            None,
            f"{spec.name} timed out after {timeout}s",
        )
    except OSError as exc:
        warning = _sanitize_text(str(exc), sensitive_values)
        return SkillResult(spec.name, "error", None, None, warning)

    # Persist the child's stderr even on success: an exit-0 skill can still have
    # logged warnings (failed endpoints, fallbacks) that explain a degraded run,
    # and those lines are the only record once the child process is gone.
    stderr_log = _redact_text(completed.stderr or "", sensitive_values)
    if stderr_log.strip():
        (output_dir / f"{spec.key}.stderr.log").write_text(stderr_log, encoding="utf-8")

    if completed.returncode != 0:
        stderr = _sanitize_text(completed.stderr or "no stderr", sensitive_values)
        warning = f"{spec.name} exited with code {completed.returncode}: {stderr}"[:330]
        return SkillResult(spec.name, "error", None, None, warning)

    matches = [
        path
        for path in output_dir.glob(spec.artifact_glob)
        if "_history" not in path.stem and path.is_file()
    ]
    if not matches:
        return SkillResult(
            spec.name,
            "missing_artifact",
            None,
            None,
            f"{spec.name} produced no {spec.artifact_glob} artifact",
        )
    artifact = max(matches, key=lambda path: (path.stat().st_mtime_ns, path.name))
    try:
        data = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warning = _sanitize_text(str(exc), sensitive_values)
        return SkillResult(spec.name, "invalid_artifact", artifact, None, warning)
    if not isinstance(data, (dict, list)):
        return SkillResult(
            spec.name,
            "invalid_artifact",
            artifact,
            None,
            "JSON artifact must be an object or array",
        )
    return SkillResult(spec.name, "ok", artifact, data)


def acquire_lock(lock_path: Path) -> bool:
    """Atomically acquire a PID lock, replacing stale lock files."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                existing_pid = int(lock_path.read_text(encoding="utf-8").strip())
                os.kill(existing_pid, 0)
                return False
            except (ValueError, OSError):
                lock_path.unlink(missing_ok=True)
                continue
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
        finally:
            os.close(descriptor)
        return True
    return False


def release_lock(lock_path: Path) -> None:
    """Release a routine PID lock if present."""
    lock_path.unlink(missing_ok=True)


def create_run_dir(output_root: Path) -> Path:
    """Create and return a unique UTC-stamped run directory."""
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root / f"{timestamp}-{uuid4().hex[:8]}"
    run_dir.mkdir()
    return run_dir


SkillRunner = Callable[..., SkillResult]


def _market_specs(config: RoutineConfig) -> tuple[SkillSpec, ...]:
    specs = [
        SkillSpec(
            key="market_breadth",
            name="Market Breadth",
            script=Path("skills/market-breadth-analyzer/scripts/market_breadth_analyzer.py"),
            args=("--output-dir", "{output_dir}"),
            artifact_glob="market_breadth_*.json",
        ),
        SkillSpec(
            key="uptrend",
            name="Uptrend Analyzer",
            script=Path("skills/uptrend-analyzer/scripts/uptrend_analyzer.py"),
            args=("--output-dir", "{output_dir}"),
            artifact_glob="uptrend_analysis_*.json",
        ),
        SkillSpec(
            key="market_top",
            name="Market Top Detector",
            script=Path("skills/market-top-detector/scripts/market_top_detector.py"),
            args=("--output-dir", "{output_dir}"),
            artifact_glob="market_top_*.json",
        ),
    ]
    if config.enable_macro_regime:
        specs.append(
            SkillSpec(
                key="macro_regime",
                name="Macro Regime Detector",
                script=Path("skills/macro-regime-detector/scripts/macro_regime_detector.py"),
                args=("--output-dir", "{output_dir}"),
                artifact_glob="macro_regime_*.json",
                required=False,
            )
        )
    return tuple(specs)


def _source_date(key: str, data: dict[str, Any] | list[Any] | None) -> date | None:
    if not isinstance(data, dict):
        return None
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return None
    raw: Any = None
    if key == "market_breadth":
        freshness = metadata.get("data_freshness")
        if isinstance(freshness, dict):
            raw = freshness.get("latest_date")
    elif key == "uptrend":
        raw = metadata.get("latest_data_date")
    elif key == "market_top":
        freshness = metadata.get("data_freshness")
        breadth = freshness.get("breadth_200dma") if isinstance(freshness, dict) else None
        if isinstance(breadth, dict):
            raw = breadth.get("date")
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def run_market_regime(
    config: RoutineConfig,
    project_root: Path,
    run_dir: Path,
    *,
    as_of: date,
    skill_runner: SkillRunner = _run_skill,
) -> StageResult:
    """Run Market Regime inputs and evaluate the Exposure Coach gate."""
    results: dict[str, SkillResult] = {}
    specs = _market_specs(config)
    with ThreadPoolExecutor(max_workers=len(specs)) as executor:
        futures = {
            executor.submit(
                skill_runner,
                spec,
                project_root,
                run_dir / spec.key,
                timeout=config.timeouts[spec.key],
            ): spec
            for spec in specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                results[spec.key] = future.result()
            except Exception as exc:  # pragma: no cover - defensive thread boundary
                results[spec.key] = SkillResult(
                    spec.name, "error", None, None, _sanitize_text(str(exc), ())
                )

    # Iterate specs, not the completion-ordered results dict, so warning order
    # is identical across replays of the same run.
    required_keys = {spec.key for spec in specs if spec.required}
    failures = [spec.key for spec in specs if results[spec.key].status != "ok"]
    required_failures = [key for key in failures if key in required_keys]
    if required_failures:
        warnings = tuple(
            results[key].warning or f"{results[key].name} failed" for key in required_failures
        )
        return StageResult("FAILED_REQUIRED_SKILL", results=results, warnings=warnings)

    # Optional regime inputs are informational: a failure never gates the day.
    optional_warnings = tuple(
        results[key].warning or f"{results[key].name} failed"
        for key in failures
        if key not in required_keys
    )

    stale: list[str] = []
    for key in ("market_breadth", "uptrend", "market_top"):
        source_date = _source_date(key, results[key].data)
        if source_date is None:
            stale.append(f"{key}: missing source date")
            continue
        age_days = (as_of - source_date).days
        if age_days < 0 or age_days > config.max_market_data_age_days:
            stale.append(f"{key}: source date {source_date.isoformat()} is {age_days} days old")
    if stale:
        return StageResult(
            "STOPPED_STALE_DATA",
            results=results,
            warnings=optional_warnings + tuple(stale),
        )

    exposure_args = [
        "--breadth",
        str(results["market_breadth"].artifact),
        "--uptrend",
        str(results["uptrend"].artifact),
        "--top-risk",
        str(results["market_top"].artifact),
    ]
    # `regime` carries the largest weight in exposure-coach and counts as one of
    # its critical inputs, so pass it whenever the optional detector produced a
    # usable artifact. When it is disabled or failed, exposure-coach handles the
    # absence itself by lowering confidence.
    macro = results.get("macro_regime")
    if macro is not None and macro.status == "ok" and macro.artifact is not None:
        exposure_args += ["--regime", str(macro.artifact)]
    exposure_args += ["--output-dir", "{output_dir}"]

    exposure_spec = SkillSpec(
        key="exposure",
        name="Exposure Coach",
        script=Path("skills/exposure-coach/scripts/calculate_exposure.py"),
        args=tuple(exposure_args),
        artifact_glob="exposure_posture_*.json",
    )
    exposure = skill_runner(
        exposure_spec,
        project_root,
        run_dir / "exposure",
        timeout=config.timeouts["exposure"],
    )
    results["exposure"] = exposure
    if exposure.status != "ok" or not isinstance(exposure.data, dict):
        warning = exposure.warning or "Exposure Coach produced invalid data"
        return StageResult(
            "FAILED_REQUIRED_SKILL",
            results=results,
            warnings=optional_warnings + (warning,),
        )

    decision = exposure.data.get("recommendation")
    if decision != "NEW_ENTRY_ALLOWED":
        return StageResult(
            "STOPPED_BY_EXPOSURE_GATE",
            decision=str(decision) if decision is not None else None,
            results=results,
            warnings=optional_warnings,
        )
    return StageResult(
        "MARKET_REGIME_ALLOWED",
        decision="NEW_ENTRY_ALLOWED",
        results=results,
        warnings=optional_warnings,
    )


def run_circuit_breaker(
    config: RoutineConfig,
    project_root: Path,
    run_dir: Path,
    *,
    skill_runner: SkillRunner = _run_skill,
) -> StageResult:
    """Evaluate account-level drawdown controls before running screeners."""
    account_size = f"{config.account_size:g}"
    spec = SkillSpec(
        key="circuit_breaker",
        name="Drawdown Circuit Breaker",
        script=Path("skills/drawdown-circuit-breaker/scripts/check_circuit_breaker.py"),
        args=(
            "--state-dir",
            str(config.state_dir),
            "--account-size",
            account_size,
            "--output-dir",
            "{output_dir}",
            "--json-only",
        ),
        artifact_glob="circuit_breaker_decision_*.json",
    )
    result = skill_runner(
        spec,
        project_root,
        run_dir / "circuit_breaker",
        timeout=config.timeouts["circuit_breaker"],
        sensitive_values=(account_size,),
    )
    results = {spec.key: result}
    if result.status != "ok" or not isinstance(result.data, dict):
        warning = result.warning or "Drawdown Circuit Breaker produced invalid data"
        return StageResult("FAILED_REQUIRED_SKILL", results=results, warnings=(warning,))

    safe_data = _redact_json(result.data, (account_size,))
    if result.artifact is not None and result.artifact.exists():
        try:
            result.artifact.write_text(
                json.dumps(safe_data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            warning = _sanitize_text(str(exc), (account_size,))
            return StageResult("FAILED_REQUIRED_SKILL", results={}, warnings=(warning,))
    result = SkillResult(result.name, result.status, result.artifact, safe_data)
    results[spec.key] = result
    raw_warnings = safe_data.get("warnings")
    stage_warnings = (
        tuple(str(warning) for warning in raw_warnings) if isinstance(raw_warnings, list) else ()
    )

    decision = result.data.get("recommendation")
    if decision != "TRADING_ALLOWED":
        return StageResult(
            "STOPPED_BY_CIRCUIT_BREAKER",
            decision=str(decision) if decision is not None else None,
            results=results,
            warnings=stage_warnings,
        )
    return StageResult(
        "CIRCUIT_BREAKER_ALLOWED",
        decision="TRADING_ALLOWED",
        results=results,
        warnings=stage_warnings,
    )


def _screener_specs(config: RoutineConfig) -> tuple[SkillSpec, ...]:
    specs = [
        SkillSpec(
            key="vcp",
            name="VCP Screener",
            script=Path("skills/vcp-screener/scripts/screen_vcp.py"),
            args=("--output-dir", "{output_dir}"),
            artifact_glob="vcp_screener_*.json",
        )
    ]
    if config.enable_theme:
        specs.append(
            SkillSpec(
                key="theme",
                name="Theme Detector",
                script=Path("skills/theme-detector/scripts/theme_detector.py"),
                args=(
                    "--output-dir",
                    "{output_dir}",
                    "--history-file",
                    str(config.output_dir / "theme_detector_history.json"),
                ),
                artifact_glob="theme_detector_*.json",
                required=False,
            )
        )
    if config.enable_momentum_burst:
        specs.append(
            SkillSpec(
                key="momentum_burst",
                name="Momentum Burst Screener",
                script=Path(
                    "skills/stockbee-momentum-burst-screener/scripts/screen_momentum_burst.py"
                ),
                args=(
                    "--fmp-universe",
                    "--market-gate",
                    "allowed",
                    "--output-dir",
                    "{output_dir}",
                ),
                artifact_glob="stockbee_momentum_burst_*.json",
                required=False,
            )
        )
    if config.enable_exhaustion_hammer:
        specs.append(
            SkillSpec(
                key="exhaustion_hammer",
                name="Exhaustion Hammer Screener",
                script=Path(
                    "skills/stockbee-exhaustion-hammer-screener/scripts/screen_exhaustion_hammer.py"
                ),
                args=(
                    "--fmp-universe",
                    "--market-gate",
                    "allowed",
                    "--output-dir",
                    "{output_dir}",
                ),
                artifact_glob="stockbee_exhaustion_hammer_*.json",
                required=False,
            )
        )
    if config.enable_canslim:
        specs.append(
            SkillSpec(
                key="canslim",
                name="CANSLIM Screener",
                script=Path("skills/canslim-screener/scripts/screen_canslim.py"),
                args=("--output-dir", "{output_dir}"),
                artifact_glob="canslim_screener_*.json",
                required=False,
            )
        )
    return tuple(specs)


def _candidate_rows(key: str, result: SkillResult) -> list[dict[str, Any]] | None:
    if key == "theme":
        return [] if isinstance(result.data, dict) else None
    if not isinstance(result.data, dict):
        return None
    field_name = "candidates" if key in {"momentum_burst", "exhaustion_hammer"} else "results"
    rows = result.data.get(field_name)
    return rows if isinstance(rows, list) else None


def _funnel_warning(name: str, data: Any) -> str | None:
    """Warn when a screener funnel drops from a positive count straight to zero.

    That shape is what a data outage looks like from the outside - the skill
    still exits 0 and still writes a well-formed, empty report. Stages are read
    in artifact order, so this works for any screener that emits a funnel.
    """
    metadata = data.get("metadata") if isinstance(data, dict) else None
    funnel = metadata.get("funnel") if isinstance(metadata, dict) else None
    if not isinstance(funnel, dict):
        return None
    previous_stage: str | None = None
    previous_count = 0
    for stage, count in funnel.items():
        if isinstance(count, bool) or not isinstance(count, int):
            return None
        if count == 0 and previous_count > 0:
            return (
                f"{name} funnel collapsed at {stage}: "
                f"{previous_stage}={previous_count} but {stage}=0 - "
                "verify data availability before trusting an empty result"
            )
        previous_stage, previous_count = stage, count
    return None


def _normalize_candidate(
    key: str, row: dict[str, Any], artifact: Path | None
) -> dict[str, Any] | None:
    symbol = row.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    execution_state = row.get("execution_state", row.get("state"))
    if execution_state == "REJECTED":
        return None
    raw_score = row.get("composite_score", row.get("setup_score"))
    score: float | None = None
    if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
        parsed_score = float(raw_score)
        if math.isfinite(parsed_score):
            score = parsed_score
    pivot_distance = row.get("distance_from_pivot_pct")
    if not isinstance(pivot_distance, (int, float)) or isinstance(pivot_distance, bool):
        pivot_distance = None
    return {
        "symbol": symbol.strip().upper(),
        "source_skill": key,
        "score": score,
        "rating": row.get("rating"),
        "execution_state": execution_state,
        "entry_ready": row.get("entry_ready") is True,
        "pivot_distance_pct": (float(pivot_distance) if pivot_distance is not None else None),
        "artifact_path": str(artifact) if artifact is not None else None,
    }


def run_swing_screeners(
    config: RoutineConfig,
    project_root: Path,
    run_dir: Path,
    *,
    skill_runner: SkillRunner = _run_skill,
) -> StageResult:
    """Run configured screeners and build an informational review queue."""
    specs = _screener_specs(config)
    results: dict[str, SkillResult] = {}
    with ThreadPoolExecutor(max_workers=len(specs)) as executor:
        futures = {
            executor.submit(
                skill_runner,
                spec,
                project_root,
                run_dir / spec.key,
                timeout=config.timeouts[spec.key],
            ): spec
            for spec in specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                results[spec.key] = future.result()
            except Exception as exc:  # pragma: no cover - defensive thread boundary
                results[spec.key] = SkillResult(
                    spec.name, "error", None, None, _sanitize_text(str(exc), ())
                )

    warnings: list[str] = []
    queue: list[dict[str, Any]] = []
    required_failure = False
    for spec in specs:
        result = results[spec.key]
        if result.status != "ok":
            warning = result.warning or f"{spec.name} failed"
            warnings.append(warning)
            required_failure = required_failure or spec.required
            continue
        rows = _candidate_rows(spec.key, result)
        if rows is None:
            warnings.append(f"{spec.name} artifact has an invalid candidate schema")
            required_failure = required_failure or spec.required
            continue
        funnel_warning = _funnel_warning(spec.name, result.data)
        if funnel_warning:
            warnings.append(funnel_warning)
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized = _normalize_candidate(spec.key, row, result.artifact)
            if normalized is not None:
                queue.append(normalized)

    if required_failure:
        return StageResult("FAILED_REQUIRED_SKILL", results=results, warnings=tuple(warnings))
    queue.sort(
        key=lambda row: (
            not row["entry_ready"],
            -(row["score"] if row["score"] is not None else float("-inf")),
            row["symbol"],
            row["source_skill"],
        )
    )
    return StageResult(
        "SCREENERS_COMPLETED",
        results=results,
        warnings=tuple(warnings),
        queue=tuple(queue),
    )


def _stage_payload(stage: StageResult | None) -> dict[str, Any]:
    if stage is None:
        return {}
    return {
        "status": stage.status,
        "decision": stage.decision,
        "warnings": list(stage.warnings),
        "skills": {
            key: {
                "name": result.name,
                "status": result.status,
                "artifact": str(result.artifact) if result.artifact is not None else None,
            }
            for key, result in sorted(stage.results.items())
        },
    }


def _candidate_summary(queue: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    by_source: dict[str, int] = {}
    for row in queue:
        source = str(row.get("source_skill", "unknown"))
        by_source[source] = by_source.get(source, 0) + 1
    return {
        "total": len(queue),
        "entry_ready": sum(row.get("entry_ready") is True for row in queue),
        "by_source": dict(sorted(by_source.items())),
    }


def _summary_artifacts(*stages: StageResult | None) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for stage in stages:
        if stage is None:
            continue
        for key, result in stage.results.items():
            if result.artifact is not None:
                artifacts[key] = str(result.artifact)
    return dict(sorted(artifacts.items()))


def _build_summary(
    run_dir: Path,
    status: str,
    *,
    market: StageResult | None = None,
    circuit: StageResult | None = None,
    screeners: StageResult | None = None,
    extra_warnings: tuple[str, ...] = (),
) -> dict[str, Any]:
    queue = screeners.queue if screeners is not None else ()
    warnings = [
        warning
        for stage in (market, circuit, screeners)
        if stage is not None
        for warning in stage.warnings
    ]
    warnings.extend(extra_warnings)
    return {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "market_regime": _stage_payload(market),
        "circuit_breaker": _stage_payload(circuit),
        "candidate_summary": _candidate_summary(queue),
        "manual_review_queue": list(queue),
        "warnings": warnings,
        "artifacts": _summary_artifacts(market, circuit, screeners),
    }


_STATUS_HEADINGS = {
    "COMPLETED_REVIEW_REQUIRED": "Manual review required",
    "STOPPED_BY_EXPOSURE_GATE": "Stopped by exposure gate",
    "STOPPED_STALE_DATA": "Stopped because market data is stale",
    "STOPPED_BY_CIRCUIT_BREAKER": "Stopped by circuit breaker",
    "FAILED_REQUIRED_SKILL": "Required workflow failed",
    "SKIPPED_OVERLAP": "Skipped because another run is active",
}


def _summary_markdown(summary: dict[str, Any]) -> str:
    status = str(summary["status"])
    heading = _STATUS_HEADINGS.get(status, status.replace("_", " ").title())
    lines = [
        f"# Daily Trading Routine — {heading}",
        "",
        f"- Status: `{status}`",
        f"- Run: `{summary['run_id']}`",
        f"- Generated: `{summary['generated_at']}`",
    ]
    market = summary.get("market_regime") or {}
    circuit = summary.get("circuit_breaker") or {}
    if market:
        lines.append(f"- Exposure decision: `{market.get('decision') or 'n/a'}`")
    if circuit:
        lines.append(f"- Circuit-breaker decision: `{circuit.get('decision') or 'n/a'}`")

    candidates = summary.get("manual_review_queue") or []
    lines.extend(["", "## Manual review queue", ""])
    if candidates:
        lines.append("| Symbol | Source | Score | Rating | State | Entry ready | Pivot % |")
        lines.append("| --- | --- | ---: | --- | --- | --- | ---: |")
        for row in candidates:
            score = row.get("score")
            pivot = row.get("pivot_distance_pct")
            lines.append(
                "| {symbol} | {source} | {score} | {rating} | {state} | {ready} | {pivot} |".format(
                    symbol=row.get("symbol", ""),
                    source=row.get("source_skill", ""),
                    score="" if score is None else score,
                    rating=row.get("rating") or "",
                    state=row.get("execution_state") or "",
                    ready="yes" if row.get("entry_ready") is True else "no",
                    pivot="" if pivot is None else pivot,
                )
            )
    else:
        lines.append("No candidates were queued.")

    lines.extend(["", "## Warnings", ""])
    warnings = summary.get("warnings") or []
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("None.")
    lines.extend(
        [
            "",
            "> This queue is informational. Review weekly charts manually before any trade decision.",
            "",
        ]
    )
    return "\n".join(lines)


def write_summary(summary: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Atomically write the stable JSON and Markdown summaries."""
    json_path = run_dir / "summary.json"
    markdown_path = run_dir / "summary.md"
    summary["artifacts"]["summary_json"] = str(json_path)
    summary["artifacts"]["summary_markdown"] = str(markdown_path)
    json_temp = run_dir / ".summary.json.tmp"
    markdown_temp = run_dir / ".summary.md.tmp"
    json_temp.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_temp.write_text(_summary_markdown(summary), encoding="utf-8")
    json_temp.replace(json_path)
    markdown_temp.replace(markdown_path)
    return summary


MarketStageRunner = Callable[..., StageResult]


def run_routine(
    config: RoutineConfig,
    project_root: Path,
    *,
    as_of: date | None = None,
    market_runner: MarketStageRunner = run_market_regime,
    circuit_runner: MarketStageRunner = run_circuit_breaker,
    screener_runner: MarketStageRunner = run_swing_screeners,
) -> dict[str, Any]:
    """Run each gate in order and persist a summary for every started run."""
    project_root = project_root.resolve()
    run_dir = create_run_dir(config.output_dir)
    lock_path = config.output_dir / ".daily-trading-routine.lock"
    if not acquire_lock(lock_path):
        return write_summary(_build_summary(run_dir, "SKIPPED_OVERLAP"), run_dir)

    market: StageResult | None = None
    circuit: StageResult | None = None
    screeners: StageResult | None = None
    sensitive_values = (f"{config.account_size:g}",)
    try:
        market = market_runner(config, project_root, run_dir, as_of=as_of or date.today())
        if market.status != "MARKET_REGIME_ALLOWED":
            return write_summary(_build_summary(run_dir, market.status, market=market), run_dir)

        circuit = circuit_runner(config, project_root, run_dir)
        if circuit.status != "CIRCUIT_BREAKER_ALLOWED":
            return write_summary(
                _build_summary(run_dir, circuit.status, market=market, circuit=circuit),
                run_dir,
            )

        screeners = screener_runner(config, project_root, run_dir)
        status = (
            "COMPLETED_REVIEW_REQUIRED"
            if screeners.status == "SCREENERS_COMPLETED"
            else screeners.status
        )
        return write_summary(
            _build_summary(
                run_dir,
                status,
                market=market,
                circuit=circuit,
                screeners=screeners,
            ),
            run_dir,
        )
    except Exception as exc:  # noqa: BLE001 - preserve a failed-run summary
        warning = _sanitize_text(str(exc), sensitive_values)
        return write_summary(
            _build_summary(
                run_dir,
                "FAILED_REQUIRED_SKILL",
                market=market,
                circuit=circuit,
                screeners=screeners,
                extra_warnings=(warning,),
            ),
            run_dir,
        )
    finally:
        release_lock(lock_path)


def status_exit_code(status: str) -> int:
    """Translate a routine status into its CLI exit code."""
    return 1 if status.startswith("FAILED_") else 0


def _dry_run_lines(config: RoutineConfig) -> list[str]:
    lines = ["Validated daily trading routine plan:"]
    for spec in _market_specs(config):
        lines.append(f"- {spec.name}: {spec.script} {' '.join(spec.args)}")
    regime_arg = " --regime <artifact>" if config.enable_macro_regime else ""
    lines.append(
        "- Exposure Coach: skills/exposure-coach/scripts/calculate_exposure.py "
        "--breadth <artifact> --uptrend <artifact> --top-risk <artifact>"
        f"{regime_arg} --output-dir <run-dir>"
    )
    lines.append(
        "- Drawdown Circuit Breaker: "
        "skills/drawdown-circuit-breaker/scripts/check_circuit_breaker.py "
        f"--state-dir {config.state_dir} --account-size [REDACTED] "
        "--output-dir <run-dir> --json-only"
    )
    for spec in _screener_specs(config):
        lines.append(f"- {spec.name}: {spec.script} {' '.join(spec.args)}")
    lines.append("- Stop before weekly-chart review; no orders, sizing, plans, or thesis writes.")
    return lines


def _parse_as_of(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--as-of must use YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the fail-closed daily market and swing-review routine"
    )
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--project-root", type=Path, default=default_root)
    parser.add_argument(
        "--config", type=Path, default=Path("config/daily-trading-routine.local.toml")
    )
    parser.add_argument("--as-of", type=_parse_as_of)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = args.project_root.expanduser().resolve()
    config_path = args.config.expanduser()
    if not config_path.is_absolute():
        config_path = project_root / config_path
    try:
        config = load_config(config_path, project_root=project_root)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("\n".join(_dry_run_lines(config)))
        return 0

    summary = run_routine(config, project_root, as_of=args.as_of)
    print(f"Status: {summary['status']}")
    print(f"JSON summary: {summary['artifacts']['summary_json']}")
    print(f"Markdown summary: {summary['artifacts']['summary_markdown']}")
    if args.verbose:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return status_exit_code(str(summary["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
