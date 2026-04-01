from __future__ import annotations

from pathlib import Path

import pytest

from ha_pv_optimization.replay import (
    GitReference,
    ReplayDataset,
    ReplayInputError,
    ReplayRunner,
    ReplayScenario,
    append_scorecard_history,
    load_history_csv,
)


def _write_csv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_load_history_csv_groups_entity_samples(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "history.csv",
        "entity_id,state,last_changed\n"
        "sensor.a,1,2026-03-28T06:00:00.000Z\n"
        "sensor.b,2,2026-03-28T06:00:01.000Z\n"
        "sensor.a,3,2026-03-28T06:00:02.000Z\n",
    )

    signals = load_history_csv(csv_path)

    assert sorted(signals) == ["sensor.a", "sensor.b"]
    assert len(signals["sensor.a"].samples) == 2
    assert signals["sensor.a"].samples[0].value == 1.0
    assert signals["sensor.a"].samples[1].value == 3.0
    assert signals["sensor.b"].samples[0].value == 2.0


def test_replay_runner_produces_deterministic_scorecard(tmp_path: Path) -> None:
    consumption_csv = _write_csv(
        tmp_path / "consumption.csv",
        "entity_id,state,last_changed\n"
        "sensor.total_consumption_power,200,2026-03-28T06:00:00.000Z\n"
        "sensor.total_consumption_power,200,2026-03-28T06:00:30.000Z\n"
        "sensor.total_consumption_power,200,2026-03-28T06:01:00.000Z\n",
    )
    inverter_csv = _write_csv(
        tmp_path / "inverter.csv",
        "entity_id,state,last_changed\n"
        "sensor.pv_total_power,190,2026-03-28T06:00:00.000Z\n"
        "sensor.pv_total_power,190,2026-03-28T06:00:30.000Z\n"
        "sensor.pv_total_power,190,2026-03-28T06:01:00.000Z\n",
    )
    per_device_csv = _write_csv(
        tmp_path / "per_device.csv",
        "entity_id,state,last_changed\n"
        "sensor.outlet_microwave_power,0,2026-03-28T06:00:00.000Z\n",
    )

    dataset = ReplayDataset.from_csvs(
        consumption_csv=consumption_csv,
        inverter_output_csv=inverter_csv,
        per_device_csv=per_device_csv,
    )
    runner = ReplayRunner.from_defaults()
    run = runner.run(
        dataset,
        ReplayScenario(
            inverter_output_entity="sensor.pv_total_power",
        ),
    )

    assert run.scorecard.tick_count == 3
    assert run.scorecard.total_write_count == 3
    assert run.scorecard.battery_write_count == 2
    assert run.scorecard.inverter_write_count == 1
    assert run.scorecard.oversupply_energy_wh == 0.0
    assert run.scorecard.undersupply_energy_wh == 0.4166666666666667
    assert run.scorecard.self_consumption_ratio == 0.9166666666666667
    assert run.scorecard.mean_absolute_error_w == 16.666666666666668
    assert run.scorecard.measured_inverter_gap_w == 20.0


def test_load_history_csv_skips_invalid_rows_by_default(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    csv_path = _write_csv(
        tmp_path / "history.csv",
        "entity_id,state,last_changed\n"
        "sensor.a,1,2026-03-28T06:00:00.000Z\n"
        ":qa\n"
        "sensor.a,2,2026-03-28T06:00:01.000Z\n",
    )

    signals = load_history_csv(csv_path)

    assert len(signals["sensor.a"].samples) == 2
    stderr = capsys.readouterr().err
    assert "Invalid replay row" in stderr
    assert "line 3" in stderr


def test_load_history_csv_can_fail_on_invalid_rows(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "history.csv",
        "entity_id,state,last_changed\n:qa\n",
    )

    with pytest.raises(ReplayInputError, match="Invalid replay row"):
        load_history_csv(csv_path, skip_invalid_rows=False)


def test_load_history_csv_reports_missing_file() -> None:
    missing_path = Path("/does/not/exist.csv")

    with pytest.raises(ReplayInputError, match="Replay CSV not found"):
        load_history_csv(missing_path)


def test_append_scorecard_history_creates_csv(tmp_path: Path) -> None:
    consumption_csv = _write_csv(
        tmp_path / "consumption.csv",
        "entity_id,state,last_changed\n"
        "sensor.total_consumption_power,200,2026-03-28T06:00:00.000Z\n"
        "sensor.total_consumption_power,200,2026-03-28T06:00:30.000Z\n",
    )
    dataset = ReplayDataset.from_csvs(consumption_csv=consumption_csv)
    run = ReplayRunner.from_defaults().run(dataset, ReplayScenario())
    history_csv = tmp_path / "history.csv"

    append_scorecard_history(
        history_csv,
        run=run,
        controller_git=GitReference(
            ref="main",
            sha="abc123",
            dirty=False,
            repo_root="/tmp/repo",
        ),
        site_git=None,
        site_config_path=None,
        consumption_csv=consumption_csv,
        inverter_output_csv=None,
        per_device_csv=None,
    )

    text = history_csv.read_text(encoding="utf-8")
    assert "controller_ref" in text
    assert "main" in text
    assert "battery_write_count" in text
