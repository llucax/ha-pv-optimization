from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .controller import PowerControllerCore
from .models import ActuatorInputs, ControllerConfig, ControllerInputs, ControllerResult


class ReplayInputError(ValueError):
    pass


def _parse_timestamp(value: str) -> datetime:
    if value is None:
        raise ReplayInputError("missing last_changed timestamp")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized).astimezone(UTC)


def _coerce_float(value: str) -> float:
    if value is None:
        raise ReplayInputError("missing numeric state value")
    return float(value.strip())


@dataclass(frozen=True)
class TimedSample:
    timestamp: datetime
    value: float


@dataclass(frozen=True)
class PiecewiseConstantSignal:
    entity_id: str
    samples: tuple[TimedSample, ...]

    @property
    def start_time(self) -> datetime:
        return self.samples[0].timestamp

    @property
    def end_time(self) -> datetime:
        return self.samples[-1].timestamp

    def value_at(self, timestamp: datetime) -> float | None:
        if timestamp < self.start_time:
            return None

        latest_value: float | None = None
        for sample in self.samples:
            if sample.timestamp > timestamp:
                break
            latest_value = sample.value
        return latest_value


@dataclass(frozen=True)
class ReplayDataset:
    signals: dict[str, PiecewiseConstantSignal]

    @classmethod
    def from_csvs(
        cls,
        *,
        consumption_csv: Path,
        inverter_output_csv: Path | None = None,
        per_device_csv: Path | None = None,
        skip_invalid_rows: bool = True,
    ) -> ReplayDataset:
        signals: dict[str, PiecewiseConstantSignal] = {}
        for csv_path in (consumption_csv, inverter_output_csv, per_device_csv):
            if csv_path is None:
                continue
            signals.update(
                load_history_csv(csv_path, skip_invalid_rows=skip_invalid_rows)
            )
        return cls(signals=signals)

    def signal(self, entity_id: str) -> PiecewiseConstantSignal:
        try:
            return self.signals[entity_id]
        except KeyError as exc:  # pragma: no cover - trivial exception path
            raise KeyError(f"Replay signal not found: {entity_id}") from exc

    def value_at(self, entity_id: str | None, timestamp: datetime) -> float | None:
        if entity_id is None:
            return None
        signal = self.signals.get(entity_id)
        if signal is None:
            return None
        return signal.value_at(timestamp)


def load_history_csv(
    path: Path,
    *,
    skip_invalid_rows: bool = True,
) -> dict[str, PiecewiseConstantSignal]:
    resolved = path.expanduser().resolve(strict=False)
    if not resolved.exists():
        raise ReplayInputError(
            f"Replay CSV not found: {path} (resolved={resolved}, cwd={Path.cwd()})"
        )

    grouped_samples: dict[str, list[TimedSample]] = {}
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            try:
                entity_id = row["entity_id"]
                if entity_id is None or not entity_id.strip():
                    raise ReplayInputError("missing entity_id")
                sample = TimedSample(
                    timestamp=_parse_timestamp(row["last_changed"]),
                    value=_coerce_float(row["state"]),
                )
            except (KeyError, ReplayInputError, TypeError, ValueError) as exc:
                message = (
                    f"Invalid replay row in {resolved} at line {row_number}: {exc}."
                    f" Row={row!r}"
                )
                if not skip_invalid_rows:
                    raise ReplayInputError(message) from exc
                print(f"WARNING: {message}", file=sys.stderr)
                continue

            grouped_samples.setdefault(entity_id.strip(), []).append(sample)

    if not grouped_samples:
        raise ReplayInputError(f"Replay CSV has no usable rows: {resolved}")

    return {
        entity_id: PiecewiseConstantSignal(
            entity_id=entity_id,
            samples=tuple(sorted(samples, key=lambda sample: sample.timestamp)),
        )
        for entity_id, samples in grouped_samples.items()
    }


@dataclass(frozen=True)
class ReplayScenario:
    consumption_entity: str = "sensor.total_consumption_power"
    inverter_output_entity: str | None = None
    net_consumption_entity: str | None = None
    initial_battery_limit_w: float = 0.0
    initial_inverter_limit_w: float = 0.0
    battery_soc_pct: float | None = None
    battery_discharge_limit_pct: float | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None


@dataclass(frozen=True)
class ReplayTick:
    timestamp: datetime
    consumption_w: float
    effective_target_w: float
    measured_inverter_output_w: float | None
    result: ControllerResult


@dataclass(frozen=True)
class ReplayScorecard:
    duration_s: float
    tick_count: int
    battery_write_count: int
    inverter_write_count: int
    total_write_count: int
    mean_absolute_error_w: float
    mean_signed_error_w: float
    oversupply_energy_wh: float
    undersupply_energy_wh: float
    oversupply_duration_s: float
    undersupply_duration_s: float
    consumption_energy_wh: float
    matched_energy_wh: float
    self_consumption_ratio: float
    measured_inverter_gap_w: float | None


@dataclass(frozen=True)
class ReplayRun:
    scenario: ReplayScenario
    scorecard: ReplayScorecard
    ticks: tuple[ReplayTick, ...]


class ReplayRunner:
    def __init__(self, config: ControllerConfig) -> None:
        self.config = config

    @classmethod
    def from_defaults(cls) -> ReplayRunner:
        return cls(_default_replay_config())

    def run(self, dataset: ReplayDataset, scenario: ReplayScenario) -> ReplayRun:
        controller = PowerControllerCore(self.config)
        consumption_signal = dataset.signal(scenario.consumption_entity)

        start_time = scenario.start_time or consumption_signal.start_time
        end_time = scenario.end_time or consumption_signal.end_time
        if end_time < start_time:
            raise ValueError(
                "Replay end_time must be greater than or equal to start_time"
            )

        battery_limit_w = scenario.initial_battery_limit_w
        inverter_limit_w = scenario.initial_inverter_limit_w
        current_time = start_time
        ticks: list[ReplayTick] = []

        while current_time <= end_time:
            consumption_w = consumption_signal.value_at(current_time)
            if consumption_w is None:
                current_time += timedelta(seconds=self.config.control_interval_s)
                continue

            result = controller.step(
                ControllerInputs(
                    consumption_w=consumption_w,
                    primary_actuator=ActuatorInputs(current_limit_w=battery_limit_w),
                    trim_actuator=None
                    if self.config.inverter_actuator is None
                    else ActuatorInputs(current_limit_w=inverter_limit_w),
                    net_consumption_w=dataset.value_at(
                        scenario.net_consumption_entity,
                        current_time,
                    ),
                    soc_pct=scenario.battery_soc_pct,
                    discharge_limit_pct=scenario.battery_discharge_limit_pct,
                )
            )

            if result.battery_actuator.applied_limit_w is not None:
                battery_limit_w = result.battery_actuator.applied_limit_w
            if (
                result.inverter_actuator is not None
                and result.inverter_actuator.applied_limit_w is not None
            ):
                inverter_limit_w = result.inverter_actuator.applied_limit_w

            ticks.append(
                ReplayTick(
                    timestamp=current_time,
                    consumption_w=consumption_w,
                    effective_target_w=result.effective_target_w or 0.0,
                    measured_inverter_output_w=dataset.value_at(
                        scenario.inverter_output_entity,
                        current_time,
                    ),
                    result=result,
                )
            )

            current_time += timedelta(seconds=self.config.control_interval_s)

        if not ticks:
            raise ValueError("Replay produced no ticks for the selected scenario")

        return ReplayRun(
            scenario=scenario,
            scorecard=_build_scorecard(ticks),
            ticks=tuple(ticks),
        )


def _build_scorecard(ticks: list[ReplayTick]) -> ReplayScorecard:
    if len(ticks) == 1:
        durations_s = [0.0]
    else:
        durations_s = [
            max(0.0, (ticks[index + 1].timestamp - tick.timestamp).total_seconds())
            for index, tick in enumerate(ticks[:-1])
        ]
        durations_s.append(durations_s[-1])

    total_duration_s = sum(durations_s)
    weighted_absolute_error = 0.0
    weighted_signed_error = 0.0
    oversupply_energy_wh = 0.0
    undersupply_energy_wh = 0.0
    oversupply_duration_s = 0.0
    undersupply_duration_s = 0.0
    consumption_energy_wh = 0.0
    matched_energy_wh = 0.0
    measured_gap_sum = 0.0
    measured_gap_duration_s = 0.0
    battery_write_count = 0
    inverter_write_count = 0

    for tick, duration_s in zip(ticks, durations_s, strict=True):
        error_w = tick.effective_target_w - tick.consumption_w
        weighted_absolute_error += abs(error_w) * duration_s
        weighted_signed_error += error_w * duration_s

        oversupply_w = max(0.0, error_w)
        undersupply_w = max(0.0, -error_w)
        oversupply_energy_wh += oversupply_w * duration_s / 3600.0
        undersupply_energy_wh += undersupply_w * duration_s / 3600.0
        if oversupply_w > 0:
            oversupply_duration_s += duration_s
        if undersupply_w > 0:
            undersupply_duration_s += duration_s

        consumption_energy_wh += tick.consumption_w * duration_s / 3600.0
        matched_energy_wh += (
            min(tick.effective_target_w, tick.consumption_w) * duration_s / 3600.0
        )

        if tick.measured_inverter_output_w is not None:
            measured_gap_sum += (
                abs(tick.effective_target_w - tick.measured_inverter_output_w)
                * duration_s
            )
            measured_gap_duration_s += duration_s

        if tick.result.battery_actuator.action == "write":
            battery_write_count += 1
        if (
            tick.result.inverter_actuator is not None
            and tick.result.inverter_actuator.action == "write"
        ):
            inverter_write_count += 1

    mean_absolute_error_w = 0.0
    mean_signed_error_w = 0.0
    if total_duration_s > 0:
        mean_absolute_error_w = weighted_absolute_error / total_duration_s
        mean_signed_error_w = weighted_signed_error / total_duration_s

    self_consumption_ratio = 1.0
    if consumption_energy_wh > 0:
        self_consumption_ratio = matched_energy_wh / consumption_energy_wh

    measured_inverter_gap_w = None
    if measured_gap_duration_s > 0:
        measured_inverter_gap_w = measured_gap_sum / measured_gap_duration_s

    return ReplayScorecard(
        duration_s=total_duration_s,
        tick_count=len(ticks),
        battery_write_count=battery_write_count,
        inverter_write_count=inverter_write_count,
        total_write_count=battery_write_count + inverter_write_count,
        mean_absolute_error_w=mean_absolute_error_w,
        mean_signed_error_w=mean_signed_error_w,
        oversupply_energy_wh=oversupply_energy_wh,
        undersupply_energy_wh=undersupply_energy_wh,
        oversupply_duration_s=oversupply_duration_s,
        undersupply_duration_s=undersupply_duration_s,
        consumption_energy_wh=consumption_energy_wh,
        matched_energy_wh=matched_energy_wh,
        self_consumption_ratio=self_consumption_ratio,
        measured_inverter_gap_w=measured_inverter_gap_w,
    )


def _default_replay_config() -> ControllerConfig:
    from .models import ActuatorConfig

    return ControllerConfig(
        primary_actuator=ActuatorConfig(
            label="battery",
            min_output_w=0.0,
            max_output_w=800.0,
            power_step_w=50.0,
            min_change_w=50.0,
            min_write_interval_s=60.0,
            max_increase_per_cycle_w=150.0,
            max_decrease_per_cycle_w=300.0,
            emergency_max_decrease_per_cycle_w=500.0,
        ),
        trim_actuator=ActuatorConfig(
            label="inverter",
            min_output_w=30.0,
            max_output_w=800.0,
            power_step_w=25.0,
            min_change_w=25.0,
            min_write_interval_s=15.0,
            max_increase_per_cycle_w=300.0,
            max_decrease_per_cycle_w=300.0,
            emergency_max_decrease_per_cycle_w=500.0,
        ),
        baseline_load_w=10.0,
        control_interval_s=30.0,
        consumption_ema_tau_s=75.0,
        net_ema_tau_s=45.0,
        deadband_w=50.0,
        zero_output_threshold_w=25.0,
        fast_export_threshold_w=-80.0,
        import_correction_gain=0.35,
        export_correction_gain=1.0,
        soc_stop_buffer_pct=3.0,
        soc_full_power_buffer_pct=10.0,
        soc_min_derate_factor=0.25,
        net_export_negative=True,
        dry_run=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay the current controller against trace CSVs"
    )
    parser.add_argument("--consumption-csv", type=Path, required=True)
    parser.add_argument("--inverter-output-csv", type=Path)
    parser.add_argument("--per-device-csv", type=Path)
    parser.add_argument(
        "--consumption-entity", default="sensor.total_consumption_power"
    )
    parser.add_argument("--inverter-output-entity")
    parser.add_argument("--net-consumption-entity")
    parser.add_argument("--initial-battery-limit-w", type=float, default=0.0)
    parser.add_argument("--initial-inverter-limit-w", type=float, default=0.0)
    parser.add_argument("--battery-soc-pct", type=float)
    parser.add_argument("--battery-discharge-limit-pct", type=float)
    parser.add_argument(
        "--strict-csv",
        action="store_true",
        help="Fail on malformed CSV rows instead of skipping them with warnings.",
    )
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)

    try:
        dataset = ReplayDataset.from_csvs(
            consumption_csv=args.consumption_csv,
            inverter_output_csv=args.inverter_output_csv,
            per_device_csv=args.per_device_csv,
            skip_invalid_rows=not args.strict_csv,
        )
        scenario = ReplayScenario(
            consumption_entity=args.consumption_entity,
            inverter_output_entity=args.inverter_output_entity,
            net_consumption_entity=args.net_consumption_entity,
            initial_battery_limit_w=args.initial_battery_limit_w,
            initial_inverter_limit_w=args.initial_inverter_limit_w,
            battery_soc_pct=args.battery_soc_pct,
            battery_discharge_limit_pct=args.battery_discharge_limit_pct,
        )
        run = ReplayRunner.from_defaults().run(dataset, scenario)
    except ReplayInputError as exc:
        parser.exit(2, f"Replay input error: {exc}\n")

    payload = asdict(run.scorecard)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output_json is not None:
        args.output_json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
