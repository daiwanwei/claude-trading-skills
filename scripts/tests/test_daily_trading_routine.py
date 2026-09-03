"""Tests for the deterministic daily trading routine runner."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from run_daily_trading_routine import (  # noqa: E402
    RoutineConfig,
    SkillResult,
    SkillSpec,
    StageResult,
    _run_skill,
    acquire_lock,
    create_run_dir,
    load_config,
    main,
    redacted_config,
    release_lock,
    run_circuit_breaker,
    run_market_regime,
    run_routine,
    run_swing_screeners,
    status_exit_code,
)


def _write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "routine.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_config_requires_positive_account_size(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, "account_size = 0\n")

    with pytest.raises(ValueError, match="account_size must be positive"):
        load_config(config_path, project_root=tmp_path)


def test_load_config_applies_safe_defaults(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, "account_size = 100000\n")

    config = load_config(config_path, project_root=tmp_path)

    assert config.risk_pct_per_trade == 0.5
    assert config.max_portfolio_heat_pct == 6.0
    assert config.max_market_data_age_days == 4
    assert config.enable_theme is True
    assert config.enable_momentum_burst is False
    assert config.enable_exhaustion_hammer is False
    assert config.enable_canslim is False
    assert config.timeouts["vcp"] == 420


def test_load_config_defaults_macro_regime_to_disabled(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, "account_size = 100000\n")

    config = load_config(config_path, project_root=tmp_path)

    assert config.enable_macro_regime is False
    assert config.timeouts["macro_regime"] == 240


def test_load_config_rejects_unknown_keys(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        "account_size = 100000\nunexpected_setting = true\n",
    )

    with pytest.raises(ValueError, match="Unknown config key"):
        load_config(config_path, project_root=tmp_path)


def test_load_config_resolves_relative_paths_from_project_root(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        'account_size = 100000\nstate_dir = "state/custom"\noutput_dir = "reports/custom"\n',
    )

    config = load_config(config_path, project_root=tmp_path)

    assert config.state_dir == tmp_path / "state/custom"
    assert config.output_dir == tmp_path / "reports/custom"


def test_redacted_config_omits_account_size(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, "account_size = 123456\n")
    config = load_config(config_path, project_root=tmp_path)

    redacted = redacted_config(config)

    assert "account_size" not in redacted
    assert "123456" not in str(redacted)
    assert redacted["risk_pct_per_trade"] == 0.5


def _spec() -> SkillSpec:
    return SkillSpec(
        key="example",
        name="Example Skill",
        script=Path("skills/example/run.py"),
        args=("--output-dir", "{output_dir}"),
        artifact_glob="example_*.json",
    )


@patch("run_daily_trading_routine.subprocess.run")
def test_run_skill_returns_parsed_artifact(run_mock, tmp_path: Path) -> None:
    output_dir = tmp_path / "output"

    def create_artifact(*_args, **_kwargs):
        (output_dir / "example_result.json").write_text('{"decision": "GO"}')
        return CompletedProcess([], 0, stdout="done", stderr="")

    run_mock.side_effect = create_artifact

    result = _run_skill(_spec(), tmp_path, output_dir, timeout=12)

    assert result.status == "ok"
    assert result.data == {"decision": "GO"}
    assert result.artifact == output_dir / "example_result.json"
    assert run_mock.call_args.kwargs["timeout"] == 12


@patch("run_daily_trading_routine.subprocess.run")
def test_run_skill_reports_timeout(run_mock, tmp_path: Path) -> None:
    run_mock.side_effect = TimeoutExpired(["python"], 7)

    result = _run_skill(_spec(), tmp_path, tmp_path / "output", timeout=7)

    assert result.status == "timeout"
    assert "7s" in result.warning


@patch("run_daily_trading_routine.subprocess.run")
def test_run_skill_redacts_sensitive_values_from_failure(run_mock, tmp_path: Path) -> None:
    run_mock.return_value = CompletedProcess(
        [],
        2,
        stdout="",
        stderr="account 123456 rejected" + ("x" * 500),
    )

    result = _run_skill(
        _spec(),
        tmp_path,
        tmp_path / "output",
        timeout=10,
        sensitive_values=("123456",),
    )

    assert result.status == "error"
    assert "123456" not in result.warning
    assert "[REDACTED]" in result.warning
    assert len(result.warning) <= 330


@patch("run_daily_trading_routine.subprocess.run")
def test_run_skill_reports_missing_artifact(run_mock, tmp_path: Path) -> None:
    run_mock.return_value = CompletedProcess([], 0, stdout="done", stderr="")

    result = _run_skill(_spec(), tmp_path, tmp_path / "output", timeout=10)

    assert result.status == "missing_artifact"


@patch("run_daily_trading_routine.subprocess.run")
def test_run_skill_reports_malformed_json(run_mock, tmp_path: Path) -> None:
    output_dir = tmp_path / "output"

    def create_bad_artifact(*_args, **_kwargs):
        (output_dir / "example_result.json").write_text("not json")
        return CompletedProcess([], 0, stdout="done", stderr="")

    run_mock.side_effect = create_bad_artifact

    result = _run_skill(_spec(), tmp_path, output_dir, timeout=10)

    assert result.status == "invalid_artifact"


@patch("run_daily_trading_routine.os.kill")
def test_acquire_lock_rejects_live_process(kill_mock, tmp_path: Path) -> None:
    lock_path = tmp_path / "routine.lock"
    lock_path.write_text("4321", encoding="utf-8")

    assert acquire_lock(lock_path) is False
    kill_mock.assert_called_once_with(4321, 0)
    assert lock_path.read_text(encoding="utf-8") == "4321"


@patch("run_daily_trading_routine.os.kill", side_effect=ProcessLookupError)
def test_acquire_lock_replaces_stale_process(_kill_mock, tmp_path: Path) -> None:
    lock_path = tmp_path / "routine.lock"
    lock_path.write_text("4321", encoding="utf-8")

    assert acquire_lock(lock_path) is True
    assert int(lock_path.read_text(encoding="utf-8")) > 0


def test_release_lock_removes_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "routine.lock"
    lock_path.write_text("4321", encoding="utf-8")

    release_lock(lock_path)

    assert not lock_path.exists()


def test_create_run_dir_uses_unique_utc_stamp(tmp_path: Path) -> None:
    first = create_run_dir(tmp_path)
    second = create_run_dir(tmp_path)

    assert first != second
    assert first.parent == tmp_path
    assert first.is_dir()
    assert second.is_dir()


def _routine_config(tmp_path: Path, **overrides) -> RoutineConfig:
    values = {
        "account_size": 100000.0,
        "state_dir": tmp_path / "state/theses",
        "output_dir": tmp_path / "reports",
    }
    values.update(overrides)
    return RoutineConfig(**values)


def _market_data(key: str, latest_date: str = "2026-08-07") -> dict:
    if key == "market_breadth":
        return {"metadata": {"data_freshness": {"latest_date": latest_date}}}
    if key == "uptrend":
        return {"metadata": {"latest_data_date": latest_date}}
    if key == "market_top":
        return {"metadata": {"data_freshness": {"breadth_200dma": {"date": latest_date}}}}
    if key == "macro_regime":
        return {
            "metadata": {"generated_at": f"{latest_date} 09:00:00"},
            "composite": {"composite_score": 55.0, "zone": "Neutral"},
            "regime": {"regime_label": "Late Cycle", "confidence": "medium"},
        }
    raise AssertionError(f"unexpected market key: {key}")


def test_market_inputs_feed_exposure_coach(tmp_path: Path) -> None:
    calls: list[SkillSpec] = []

    def fake_runner(spec, _project_root, output_dir, **_kwargs):
        calls.append(spec)
        artifact = output_dir / f"{spec.key}.json"
        if spec.key == "exposure":
            data = {"recommendation": "NEW_ENTRY_ALLOWED", "exposure_ceiling_pct": 61}
        else:
            data = _market_data(spec.key)
        return SkillResult(spec.name, "ok", artifact, data)

    result = run_market_regime(
        _routine_config(tmp_path),
        tmp_path,
        tmp_path / "run",
        as_of=date(2026, 8, 9),
        skill_runner=fake_runner,
    )

    assert result.status == "MARKET_REGIME_ALLOWED"
    exposure_spec = next(spec for spec in calls if spec.key == "exposure")
    assert "--breadth" in exposure_spec.args
    assert any(arg.endswith("market_breadth.json") for arg in exposure_spec.args)
    assert "--uptrend" in exposure_spec.args
    assert any(arg.endswith("uptrend.json") for arg in exposure_spec.args)
    assert "--top-risk" in exposure_spec.args
    assert any(arg.endswith("market_top.json") for arg in exposure_spec.args)


def test_required_market_skill_failure_stops_downstream(tmp_path: Path) -> None:
    called_keys: list[str] = []

    def fake_runner(spec, _project_root, output_dir, **_kwargs):
        called_keys.append(spec.key)
        if spec.key == "market_top":
            return SkillResult(spec.name, "error", None, None, "failed")
        return SkillResult(
            spec.name,
            "ok",
            output_dir / f"{spec.key}.json",
            _market_data(spec.key),
        )

    result = run_market_regime(
        _routine_config(tmp_path),
        tmp_path,
        tmp_path / "run",
        as_of=date(2026, 8, 9),
        skill_runner=fake_runner,
    )

    assert result.status == "FAILED_REQUIRED_SKILL"
    assert "exposure" not in called_keys


def test_market_failure_warnings_follow_spec_order(tmp_path: Path) -> None:
    def fake_runner(spec, _project_root, output_dir, **_kwargs):
        if spec.key in {"market_breadth", "market_top"}:
            return SkillResult(spec.name, "error", None, None, f"{spec.key} failed")
        return SkillResult(
            spec.name,
            "ok",
            output_dir / f"{spec.key}.json",
            _market_data(spec.key),
        )

    result = run_market_regime(
        _routine_config(tmp_path),
        tmp_path,
        tmp_path / "run",
        as_of=date(2026, 8, 9),
        skill_runner=fake_runner,
    )

    assert result.status == "FAILED_REQUIRED_SKILL"
    assert result.warnings == ("market_breadth failed", "market_top failed")


def test_stale_market_data_stops_before_exposure(tmp_path: Path) -> None:
    called_keys: list[str] = []

    def fake_runner(spec, _project_root, output_dir, **_kwargs):
        called_keys.append(spec.key)
        return SkillResult(
            spec.name,
            "ok",
            output_dir / f"{spec.key}.json",
            _market_data(spec.key, latest_date="2026-07-01"),
        )

    result = run_market_regime(
        _routine_config(tmp_path),
        tmp_path,
        tmp_path / "run",
        as_of=date(2026, 8, 9),
        skill_runner=fake_runner,
    )

    assert result.status == "STOPPED_STALE_DATA"
    assert "exposure" not in called_keys


def test_non_permissive_exposure_is_normal_stop(tmp_path: Path) -> None:
    def fake_runner(spec, _project_root, output_dir, **_kwargs):
        if spec.key == "exposure":
            data = {"recommendation": "REDUCE_ONLY", "exposure_ceiling_pct": 40}
        else:
            data = _market_data(spec.key)
        return SkillResult(spec.name, "ok", output_dir / f"{spec.key}.json", data)

    result = run_market_regime(
        _routine_config(tmp_path),
        tmp_path,
        tmp_path / "run",
        as_of=date(2026, 8, 9),
        skill_runner=fake_runner,
    )

    assert result.status == "STOPPED_BY_EXPOSURE_GATE"
    assert result.decision == "REDUCE_ONLY"


def _regime_runner(
    tmp_path: Path,
    called_keys: list[str],
    *,
    exposure: str = "NEW_ENTRY_ALLOWED",
    macro_result: SkillResult | None = None,
    macro_data: dict | None = None,
):
    """Build a fake skill runner for macro-regime market-stage tests."""

    def fake_runner(spec, _project_root, output_dir, **_kwargs):
        called_keys.append(spec.key)
        if spec.key == "macro_regime":
            if macro_result is not None:
                return macro_result
            data = macro_data if macro_data is not None else _market_data(spec.key)
        elif spec.key == "exposure":
            data = {"recommendation": exposure}
        else:
            data = _market_data(spec.key)
        return SkillResult(spec.name, "ok", output_dir / f"{spec.key}.json", data)

    return fake_runner


def test_macro_regime_is_skipped_when_disabled(tmp_path: Path) -> None:
    called_keys: list[str] = []

    result = run_market_regime(
        _routine_config(tmp_path),
        tmp_path,
        tmp_path / "run",
        as_of=date(2026, 8, 9),
        skill_runner=_regime_runner(tmp_path, called_keys),
    )

    assert result.status == "MARKET_REGIME_ALLOWED"
    assert "macro_regime" not in called_keys


def test_macro_regime_runs_when_enabled(tmp_path: Path) -> None:
    called_keys: list[str] = []

    result = run_market_regime(
        _routine_config(tmp_path, enable_macro_regime=True),
        tmp_path,
        tmp_path / "run",
        as_of=date(2026, 8, 9),
        skill_runner=_regime_runner(tmp_path, called_keys),
    )

    assert result.status == "MARKET_REGIME_ALLOWED"
    assert "macro_regime" in called_keys
    assert result.results["macro_regime"].status == "ok"


def _exposure_spec_from(tmp_path: Path, config: RoutineConfig, runner) -> SkillSpec:
    calls: list[SkillSpec] = []

    def recording(spec, project_root, output_dir, **kwargs):
        calls.append(spec)
        return runner(spec, project_root, output_dir, **kwargs)

    run_market_regime(
        config,
        tmp_path,
        tmp_path / "run",
        as_of=date(2026, 8, 9),
        skill_runner=recording,
    )
    return next(spec for spec in calls if spec.key == "exposure")


def test_macro_regime_artifact_is_passed_to_exposure_coach(tmp_path: Path) -> None:
    spec = _exposure_spec_from(
        tmp_path,
        _routine_config(tmp_path, enable_macro_regime=True),
        _regime_runner(tmp_path, []),
    )

    flags = [arg for arg in spec.args if arg.startswith("--")]
    assert flags == ["--breadth", "--uptrend", "--top-risk", "--regime", "--output-dir"]
    regime_path = spec.args[spec.args.index("--regime") + 1]
    assert regime_path.endswith("macro_regime.json")


def test_exposure_omits_regime_when_macro_regime_disabled(tmp_path: Path) -> None:
    spec = _exposure_spec_from(
        tmp_path,
        _routine_config(tmp_path),
        _regime_runner(tmp_path, []),
    )

    assert "--regime" not in spec.args


def test_exposure_omits_regime_when_macro_regime_failed(tmp_path: Path) -> None:
    spec = _exposure_spec_from(
        tmp_path,
        _routine_config(tmp_path, enable_macro_regime=True),
        _regime_runner(
            tmp_path,
            [],
            macro_result=SkillResult(
                "Macro Regime Detector", "error", None, None, "macro regime failed"
            ),
        ),
    )

    assert "--regime" not in spec.args


def test_macro_regime_failure_is_warning_not_stop(tmp_path: Path) -> None:
    called_keys: list[str] = []

    result = run_market_regime(
        _routine_config(tmp_path, enable_macro_regime=True),
        tmp_path,
        tmp_path / "run",
        as_of=date(2026, 8, 9),
        skill_runner=_regime_runner(
            tmp_path,
            called_keys,
            macro_result=SkillResult(
                "Macro Regime Detector", "error", None, None, "macro regime failed"
            ),
        ),
    )

    assert result.status == "MARKET_REGIME_ALLOWED"
    assert result.warnings == ("macro regime failed",)
    assert "exposure" in called_keys


def test_macro_regime_warning_survives_exposure_stop(tmp_path: Path) -> None:
    called_keys: list[str] = []

    result = run_market_regime(
        _routine_config(tmp_path, enable_macro_regime=True),
        tmp_path,
        tmp_path / "run",
        as_of=date(2026, 8, 9),
        skill_runner=_regime_runner(
            tmp_path,
            called_keys,
            exposure="REDUCE_ONLY",
            macro_result=SkillResult(
                "Macro Regime Detector", "timeout", None, None, "macro regime timed out"
            ),
        ),
    )

    assert result.status == "STOPPED_BY_EXPOSURE_GATE"
    assert result.decision == "REDUCE_ONLY"
    assert result.warnings == ("macro regime timed out",)


def test_macro_regime_is_excluded_from_staleness_gate(tmp_path: Path) -> None:
    called_keys: list[str] = []

    result = run_market_regime(
        _routine_config(tmp_path, enable_macro_regime=True),
        tmp_path,
        tmp_path / "run",
        as_of=date(2026, 8, 9),
        skill_runner=_regime_runner(
            tmp_path,
            called_keys,
            macro_data={"metadata": {"generated_at": "2019-01-01 09:00:00"}},
        ),
    )

    assert result.status == "MARKET_REGIME_ALLOWED"


def test_circuit_breaker_allows_only_explicit_trading_allowed(tmp_path: Path) -> None:
    calls: list[tuple[SkillSpec, dict]] = []

    def fake_runner(spec, _project_root, output_dir, **kwargs):
        calls.append((spec, kwargs))
        output_dir.mkdir(parents=True)
        artifact = output_dir / "decision.json"
        artifact.write_text(
            '{"recommendation": "TRADING_ALLOWED", "account_size": 100000, '
            '"warnings": ["account 100000 was evaluated"]}',
            encoding="utf-8",
        )
        return SkillResult(
            spec.name,
            "ok",
            artifact,
            {
                "recommendation": "TRADING_ALLOWED",
                "account_size": 100000,
                "warnings": ["account 100000 was evaluated"],
            },
        )

    result = run_circuit_breaker(
        _routine_config(tmp_path),
        tmp_path,
        tmp_path / "run",
        skill_runner=fake_runner,
    )

    assert result.status == "CIRCUIT_BREAKER_ALLOWED"
    assert result.decision == "TRADING_ALLOWED"
    spec, kwargs = calls[0]
    assert spec.key == "circuit_breaker"
    assert spec.args[spec.args.index("--account-size") + 1] == "100000"
    assert kwargs["sensitive_values"] == ("100000",)
    assert "100000" not in str(result)
    assert result.warnings == ("account [REDACTED] was evaluated",)
    artifact_text = (tmp_path / "run/circuit_breaker/decision.json").read_text(encoding="utf-8")
    assert "account_size" not in artifact_text


@pytest.mark.parametrize("decision", ["COOLDOWN", "HALTED", None])
def test_circuit_breaker_non_allowed_decision_is_normal_stop(
    tmp_path: Path, decision: str | None
) -> None:
    def fake_runner(spec, _project_root, output_dir, **_kwargs):
        return SkillResult(
            spec.name,
            "ok",
            output_dir / "decision.json",
            {"recommendation": decision},
        )

    result = run_circuit_breaker(
        _routine_config(tmp_path),
        tmp_path,
        tmp_path / "run",
        skill_runner=fake_runner,
    )

    assert result.status == "STOPPED_BY_CIRCUIT_BREAKER"
    assert result.decision == decision


def test_circuit_breaker_error_fails_closed(tmp_path: Path) -> None:
    def fake_runner(spec, _project_root, _output_dir, **_kwargs):
        return SkillResult(spec.name, "timeout", None, None, "timed out")

    result = run_circuit_breaker(
        _routine_config(tmp_path),
        tmp_path,
        tmp_path / "run",
        skill_runner=fake_runner,
    )

    assert result.status == "FAILED_REQUIRED_SKILL"
    assert result.warnings == ("timed out",)


def test_default_screeners_run_required_vcp_and_theme_only(tmp_path: Path) -> None:
    called_keys: list[str] = []

    def fake_runner(spec, _project_root, output_dir, **_kwargs):
        called_keys.append(spec.key)
        data = {"results": []} if spec.key == "vcp" else {"themes": {"all": []}}
        return SkillResult(spec.name, "ok", output_dir / f"{spec.key}.json", data)

    result = run_swing_screeners(
        _routine_config(tmp_path),
        tmp_path,
        tmp_path / "run",
        skill_runner=fake_runner,
    )

    assert result.status == "SCREENERS_COMPLETED"
    assert set(called_keys) == {"vcp", "theme"}
    assert result.queue == ()


def test_required_vcp_failure_fails_screener_stage(tmp_path: Path) -> None:
    def fake_runner(spec, _project_root, output_dir, **_kwargs):
        if spec.key == "vcp":
            return SkillResult(spec.name, "timeout", None, None, "vcp timed out")
        return SkillResult(
            spec.name,
            "ok",
            output_dir / "theme.json",
            {"themes": {"all": []}},
        )

    result = run_swing_screeners(
        _routine_config(tmp_path),
        tmp_path,
        tmp_path / "run",
        skill_runner=fake_runner,
    )

    assert result.status == "FAILED_REQUIRED_SKILL"
    assert result.warnings == ("vcp timed out",)


def test_optional_screener_failure_is_warning(tmp_path: Path) -> None:
    def fake_runner(spec, _project_root, output_dir, **_kwargs):
        if spec.key == "momentum_burst":
            assert "--market-gate" in spec.args
            assert "allowed" in spec.args
            return SkillResult(spec.name, "error", None, None, "momentum failed")
        data = {"results": []} if spec.key == "vcp" else {"themes": {"all": []}}
        return SkillResult(spec.name, "ok", output_dir / f"{spec.key}.json", data)

    result = run_swing_screeners(
        _routine_config(tmp_path, enable_momentum_burst=True),
        tmp_path,
        tmp_path / "run",
        skill_runner=fake_runner,
    )

    assert result.status == "SCREENERS_COMPLETED"
    assert result.warnings == ("momentum failed",)


def test_manual_review_queue_is_normalized_and_deterministic(tmp_path: Path) -> None:
    def fake_runner(spec, _project_root, output_dir, **_kwargs):
        artifact = output_dir / f"{spec.key}.json"
        if spec.key == "vcp":
            data = {
                "results": [
                    {
                        "symbol": "bbb",
                        "composite_score": 91,
                        "rating": "Excellent",
                        "execution_state": "Pre-breakout",
                        "entry_ready": False,
                        "distance_from_pivot_pct": -2.5,
                    },
                    {
                        "symbol": "aaa",
                        "composite_score": 82,
                        "rating": "Good",
                        "execution_state": "Breakout",
                        "entry_ready": True,
                        "distance_from_pivot_pct": 1.2,
                    },
                ]
            }
        elif spec.key == "momentum_burst":
            data = {
                "candidates": [
                    {
                        "symbol": "ccc",
                        "setup_score": 97,
                        "rating": "A",
                        "state": "MANUAL_REVIEW",
                    }
                ]
            }
        else:
            data = {"themes": {"all": []}}
        return SkillResult(spec.name, "ok", artifact, data)

    result = run_swing_screeners(
        _routine_config(tmp_path, enable_momentum_burst=True),
        tmp_path,
        tmp_path / "run",
        skill_runner=fake_runner,
    )

    assert [row["symbol"] for row in result.queue] == ["AAA", "CCC", "BBB"]
    assert result.queue[0] == {
        "symbol": "AAA",
        "source_skill": "vcp",
        "score": 82.0,
        "rating": "Good",
        "execution_state": "Breakout",
        "entry_ready": True,
        "pivot_distance_pct": 1.2,
        "artifact_path": str(tmp_path / "run/vcp/vcp.json"),
    }


def test_completed_run_always_writes_stable_redacted_summaries(tmp_path: Path) -> None:
    config = _routine_config(tmp_path)
    market = StageResult("MARKET_REGIME_ALLOWED", decision="NEW_ENTRY_ALLOWED")
    circuit = StageResult("CIRCUIT_BREAKER_ALLOWED", decision="TRADING_ALLOWED")
    screeners = StageResult(
        "SCREENERS_COMPLETED",
        warnings=("optional scanner unavailable",),
        queue=(
            {
                "symbol": "AAA",
                "source_skill": "vcp",
                "score": 88.0,
                "rating": "Good",
                "execution_state": "Pre-breakout",
                "entry_ready": False,
                "pivot_distance_pct": -1.0,
                "artifact_path": "/tmp/vcp.json",
            },
        ),
    )

    summary = run_routine(
        config,
        tmp_path,
        as_of=date(2026, 8, 9),
        market_runner=lambda *_args, **_kwargs: market,
        circuit_runner=lambda *_args, **_kwargs: circuit,
        screener_runner=lambda *_args, **_kwargs: screeners,
    )

    assert summary["schema_version"] == "1.0"
    assert summary["status"] == "COMPLETED_REVIEW_REQUIRED"
    assert summary["market_regime"]["decision"] == "NEW_ENTRY_ALLOWED"
    assert summary["circuit_breaker"]["decision"] == "TRADING_ALLOWED"
    assert summary["candidate_summary"] == {
        "total": 1,
        "entry_ready": 0,
        "by_source": {"vcp": 1},
    }
    assert summary["warnings"] == ["optional scanner unavailable"]
    json_path = Path(summary["artifacts"]["summary_json"])
    markdown_path = Path(summary["artifacts"]["summary_markdown"])
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == summary["status"]
    combined = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    assert "100000" not in combined
    assert "Manual review required" in combined


@pytest.mark.parametrize(
    "market_status",
    ["STOPPED_BY_EXPOSURE_GATE", "STOPPED_STALE_DATA", "FAILED_REQUIRED_SKILL"],
)
def test_market_stop_writes_summary_and_skips_downstream(
    tmp_path: Path, market_status: str
) -> None:
    downstream_called = False

    def forbidden(*_args, **_kwargs):
        nonlocal downstream_called
        downstream_called = True
        raise AssertionError("downstream stage must not run")

    summary = run_routine(
        _routine_config(tmp_path),
        tmp_path,
        as_of=date(2026, 8, 9),
        market_runner=lambda *_args, **_kwargs: StageResult(market_status),
        circuit_runner=forbidden,
        screener_runner=forbidden,
    )

    assert summary["status"] == market_status
    assert downstream_called is False
    assert Path(summary["artifacts"]["summary_json"]).exists()
    assert status_exit_code(market_status) == (1 if market_status == "FAILED_REQUIRED_SKILL" else 0)


def test_circuit_stop_writes_summary_and_skips_screeners(tmp_path: Path) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("screeners must not run")

    summary = run_routine(
        _routine_config(tmp_path),
        tmp_path,
        as_of=date(2026, 8, 9),
        market_runner=lambda *_args, **_kwargs: StageResult(
            "MARKET_REGIME_ALLOWED", decision="NEW_ENTRY_ALLOWED"
        ),
        circuit_runner=lambda *_args, **_kwargs: StageResult(
            "STOPPED_BY_CIRCUIT_BREAKER", decision="COOLDOWN"
        ),
        screener_runner=forbidden,
    )

    assert summary["status"] == "STOPPED_BY_CIRCUIT_BREAKER"
    assert summary["circuit_breaker"]["decision"] == "COOLDOWN"
    assert Path(summary["artifacts"]["summary_markdown"]).exists()


@patch("run_daily_trading_routine.acquire_lock", return_value=False)
def test_overlap_writes_skipped_summary(_lock_mock, tmp_path: Path) -> None:
    summary = run_routine(
        _routine_config(tmp_path),
        tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert summary["status"] == "SKIPPED_OVERLAP"
    assert Path(summary["artifacts"]["summary_json"]).exists()
    assert status_exit_code(summary["status"]) == 0


def test_cli_dry_run_is_redacted_and_does_not_execute(tmp_path: Path, capsys) -> None:
    config_path = _write_config(tmp_path, "account_size = 100000\n")

    with patch("run_daily_trading_routine._run_skill") as run_mock:
        exit_code = main(
            [
                "--project-root",
                str(tmp_path),
                "--config",
                str(config_path),
                "--dry-run",
            ]
        )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert run_mock.call_count == 0
    assert "[REDACTED]" in output
    assert "100000" not in output
    assert "screen_vcp.py" in output
    assert "macro_regime_detector.py" not in output


def test_cli_dry_run_lists_macro_regime_when_enabled(tmp_path: Path, capsys) -> None:
    config_path = _write_config(
        tmp_path,
        "account_size = 100000\nenable_macro_regime = true\n",
    )

    exit_code = main(
        [
            "--project-root",
            str(tmp_path),
            "--config",
            str(config_path),
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "macro_regime_detector.py" in output
    exposure_line = next(line for line in output.splitlines() if "calculate_exposure.py" in line)
    assert "--regime" in exposure_line


def test_cli_dry_run_exposure_omits_regime_when_disabled(tmp_path: Path, capsys) -> None:
    config_path = _write_config(tmp_path, "account_size = 100000\n")

    exit_code = main(["--project-root", str(tmp_path), "--config", str(config_path), "--dry-run"])

    output = capsys.readouterr().out
    assert exit_code == 0
    exposure_line = next(line for line in output.splitlines() if "calculate_exposure.py" in line)
    assert "--regime" not in exposure_line
