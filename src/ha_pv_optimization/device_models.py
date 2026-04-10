from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class DeviceModelKind(StrEnum):
    BURST_HIGH_POWER = "burst_high_power"
    CYCLIC_HEATER = "cyclic_heater"
    COMPOSITE_KITCHEN_OUTLET = "composite_kitchen_outlet"
    THERMOSTATIC_COMPRESSOR = "thermostatic_compressor"
    SESSION_BASELINE = "session_baseline"
    CONSTANT_BASELINE = "constant_baseline"


class DeviceRunState(StrEnum):
    OFF = "OFF"
    LOW = "LOW"
    HIGH = "HIGH"


@dataclass(frozen=True)
class DeviceModelConfig:
    name: str
    kind: DeviceModelKind
    entity_id: str
    enabled: bool = True
    included_in_total_template: bool = False
    used_for_feed_forward: bool = True
    used_for_baseline_overlay: bool = False
    low_threshold_w: float | None = None
    high_threshold_w: float = 300.0
    enter_persistence_s: float = 2.0
    exit_persistence_s: float = 2.0
    ff_gain: float = 0.9
    ff_hold_s: float = 60.0
    reference_power_w: float | None = None


@dataclass(frozen=True)
class DeviceContribution:
    name: str
    entity_id: str
    kind: DeviceModelKind
    state: DeviceRunState
    power_w: float
    bias_w: float
    transition_bias_w: float
    baseline_overlay_w: float
    confidence: float
    active: bool


@dataclass
class DeviceModelRuntime:
    config: DeviceModelConfig
    current_power_w: float = 0.0
    last_sample_at: datetime | None = None
    state: DeviceRunState = DeviceRunState.OFF
    pending_state: DeviceRunState | None = None
    pending_since: datetime | None = None
    transition_bias_w: float = 0.0
    transition_bias_until: datetime | None = None

    def update_sample(self, timestamp: datetime, power_w: float) -> None:
        self.current_power_w = power_w
        self.last_sample_at = timestamp

    def runtime_state_snapshot(self) -> dict[str, float | str | None]:
        return {
            "current_power_w": self.current_power_w,
            "last_sample_at": None
            if self.last_sample_at is None
            else self.last_sample_at.isoformat(),
            "state": self.state.value,
            "pending_state": None
            if self.pending_state is None
            else self.pending_state.value,
            "pending_since": None
            if self.pending_since is None
            else self.pending_since.isoformat(),
            "transition_bias_w": self.transition_bias_w,
            "transition_bias_until": None
            if self.transition_bias_until is None
            else self.transition_bias_until.isoformat(),
        }

    def load_runtime_state(
        self,
        snapshot: Mapping[str, object],
        *,
        now: datetime,
        age_s: float,
    ) -> None:
        self.current_power_w = float(snapshot.get("current_power_w", 0.0))
        self.last_sample_at = _optional_datetime(snapshot.get("last_sample_at"))
        self.state = _device_run_state(
            snapshot.get("state"), default=DeviceRunState.OFF
        )
        self.pending_state = _device_run_state(
            snapshot.get("pending_state"),
            default=None,
        )
        self.pending_since = _optional_datetime(snapshot.get("pending_since"))
        self.transition_bias_w = float(snapshot.get("transition_bias_w", 0.0))
        self.transition_bias_until = _optional_datetime(
            snapshot.get("transition_bias_until")
        )

        pending_resume_max_age_s = max(
            self.config.enter_persistence_s,
            self.config.exit_persistence_s,
        )
        if age_s > pending_resume_max_age_s:
            self.pending_state = None
            self.pending_since = None

        if self.transition_bias_until is not None and now >= self.transition_bias_until:
            self.transition_bias_w = 0.0
            self.transition_bias_until = None

    def advance(self, now: datetime) -> None:
        observed_state = self._observed_state()
        if observed_state == self.state:
            self.pending_state = None
            self.pending_since = None
        else:
            if self.pending_state != observed_state:
                self.pending_state = observed_state
                self.pending_since = self.last_sample_at or now
            if self.pending_since is not None:
                required_s = self._required_persistence_s(observed_state)
                if (now - self.pending_since).total_seconds() >= required_s:
                    previous_state = self.state
                    self.state = observed_state
                    self.pending_state = None
                    self.pending_since = None
                    self._apply_transition(previous_state=previous_state, now=now)

        if self.transition_bias_until is not None and now >= self.transition_bias_until:
            self.transition_bias_w = 0.0
            self.transition_bias_until = None

    def contribution(self, now: datetime) -> DeviceContribution:
        self.advance(now)
        baseline_overlay_w = self._baseline_overlay_w()
        bias_w = self.transition_bias_w + baseline_overlay_w
        active = bias_w > 0.0
        return DeviceContribution(
            name=self.config.name,
            entity_id=self.config.entity_id,
            kind=self.config.kind,
            state=self.state,
            power_w=self.current_power_w,
            bias_w=bias_w,
            transition_bias_w=self.transition_bias_w,
            baseline_overlay_w=baseline_overlay_w,
            confidence=1.0 if active else 0.0,
            active=active,
        )

    def _observed_state(self) -> DeviceRunState:
        if self.config.kind == DeviceModelKind.CYCLIC_HEATER:
            if self.current_power_w >= self.config.high_threshold_w:
                return DeviceRunState.HIGH
            low_threshold_w = self.config.low_threshold_w or 0.0
            if self.current_power_w >= low_threshold_w:
                return DeviceRunState.LOW
            return DeviceRunState.OFF

        if self.config.kind == DeviceModelKind.CONSTANT_BASELINE:
            low_threshold_w = self.config.low_threshold_w or 0.0
            if self.current_power_w >= low_threshold_w:
                return DeviceRunState.LOW
            return DeviceRunState.OFF

        if self.config.kind == DeviceModelKind.SESSION_BASELINE:
            threshold_w = self.config.high_threshold_w
            if self.current_power_w >= threshold_w:
                return DeviceRunState.HIGH
            return DeviceRunState.OFF

        if self.config.kind == DeviceModelKind.THERMOSTATIC_COMPRESSOR:
            threshold_w = self.config.high_threshold_w
            if self.current_power_w >= threshold_w:
                return DeviceRunState.HIGH
            return DeviceRunState.OFF

        if self.current_power_w >= self.config.high_threshold_w:
            return DeviceRunState.HIGH
        return DeviceRunState.OFF

    def _required_persistence_s(self, observed_state: DeviceRunState) -> float:
        if observed_state == DeviceRunState.HIGH:
            return self.config.enter_persistence_s
        return self.config.exit_persistence_s

    def _apply_transition(
        self,
        *,
        previous_state: DeviceRunState,
        now: datetime,
    ) -> None:
        if self.state == DeviceRunState.HIGH and previous_state != DeviceRunState.HIGH:
            if self.config.used_for_feed_forward:
                reference_power_w = self._reference_power_w()
                self.transition_bias_w = reference_power_w * self.config.ff_gain
                self.transition_bias_until = now + timedelta(
                    seconds=self.config.ff_hold_s
                )
            return

        if previous_state == DeviceRunState.HIGH and self.state != DeviceRunState.HIGH:
            self.transition_bias_w = 0.0
            self.transition_bias_until = None

    def _reference_power_w(self) -> float:
        if self.config.reference_power_w is not None:
            return self.config.reference_power_w
        return self.current_power_w

    def _baseline_overlay_w(self) -> float:
        if not self.config.used_for_baseline_overlay:
            return 0.0
        if self.config.included_in_total_template:
            return 0.0
        if self.state == DeviceRunState.OFF:
            return 0.0
        return self._reference_power_w() * self.config.ff_gain


class DeviceFeedForwardEngine:
    def __init__(self, runtimes: dict[str, DeviceModelRuntime]) -> None:
        self.runtimes = runtimes

    @classmethod
    def from_configs(
        cls,
        configs: dict[str, DeviceModelConfig],
    ) -> DeviceFeedForwardEngine:
        return cls(
            {
                name: DeviceModelRuntime(config=config)
                for name, config in configs.items()
                if config.enabled
            }
        )

    def update_sample(self, name: str, timestamp: datetime, power_w: float) -> None:
        runtime = self.runtimes.get(name)
        if runtime is None:
            return
        runtime.update_sample(timestamp, power_w)

    def contribution_snapshot(
        self,
        now: datetime,
    ) -> tuple[float, tuple[DeviceContribution, ...]]:
        contributions = tuple(
            runtime.contribution(now) for runtime in self.runtimes.values()
        )
        total_bias_w = sum(contribution.bias_w for contribution in contributions)
        return total_bias_w, contributions

    def runtime_state_snapshot(self) -> dict[str, dict[str, float | str | None]]:
        return {
            name: runtime.runtime_state_snapshot()
            for name, runtime in self.runtimes.items()
        }

    def load_runtime_state(
        self,
        snapshots: Mapping[str, Mapping[str, object]],
        *,
        now: datetime,
        age_s: float,
    ) -> None:
        for name, snapshot in snapshots.items():
            runtime = self.runtimes.get(name)
            if runtime is None:
                continue
            runtime.load_runtime_state(snapshot, now=now, age_s=age_s)


def default_device_configs() -> dict[str, DeviceModelConfig]:
    return {
        "microwave": DeviceModelConfig(
            name="microwave",
            kind=DeviceModelKind.BURST_HIGH_POWER,
            entity_id="sensor.outlet_microwave_power",
            high_threshold_w=300.0,
            enter_persistence_s=2.0,
            exit_persistence_s=2.0,
            ff_gain=0.95,
            ff_hold_s=90.0,
        ),
        "under_cabinet_appliances": DeviceModelConfig(
            name="under_cabinet_appliances",
            kind=DeviceModelKind.COMPOSITE_KITCHEN_OUTLET,
            entity_id="sensor.outlet_under_cabinet_appliances_power",
            high_threshold_w=300.0,
            enter_persistence_s=2.0,
            exit_persistence_s=2.0,
            ff_gain=0.90,
            ff_hold_s=90.0,
        ),
        "oven": DeviceModelConfig(
            name="oven",
            kind=DeviceModelKind.CYCLIC_HEATER,
            entity_id="sensor.outlet_oven_power",
            low_threshold_w=20.0,
            high_threshold_w=500.0,
            enter_persistence_s=2.0,
            exit_persistence_s=2.0,
            ff_gain=0.90,
            ff_hold_s=120.0,
        ),
        "dishwasher": DeviceModelConfig(
            name="dishwasher",
            kind=DeviceModelKind.CYCLIC_HEATER,
            entity_id="sensor.outlet_dishwasher_power",
            low_threshold_w=20.0,
            high_threshold_w=500.0,
            enter_persistence_s=3.0,
            exit_persistence_s=3.0,
            ff_gain=0.90,
            ff_hold_s=120.0,
        ),
    }


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value))


def _device_run_state(
    value: object,
    *,
    default: DeviceRunState | None,
) -> DeviceRunState | None:
    if value is None:
        return default
    return DeviceRunState(str(value))


def empty_feed_forward_engine() -> DeviceFeedForwardEngine:
    return DeviceFeedForwardEngine(runtimes={})
