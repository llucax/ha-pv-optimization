# Configuration

This document describes every AppDaemon app argument used by `examples/apps.yaml.example`.

The defaults documented here are intentionally tuned around a Growatt NOAH 2000 battery plus APsystems EZ1-M inverter style deployment, even though the entity names in the example remain adaptable.

The example block is one AppDaemon app instance:

```yaml
ha_pv_optimization:
  module: ha_pv_optimization_app
  class: HaPvOptimization
  ...
```

## App identity and loading

- `ha_pv_optimization` - the instance name in `apps.yaml`; you can rename it if you want a different AppDaemon app id.
- `module` - Python module AppDaemon imports; keep `ha_pv_optimization_app` when using the provided bridge module.
- `class` - class name AppDaemon instantiates; keep `HaPvOptimization`.
- `site_config_path` - optional path to a typed site config YAML file; when set, the wrapper loads controller/entity defaults from that file before applying explicit AppDaemon arg overrides.

## Required entity inputs

- `consumption_entity` - required main load sensor in watts.
- `battery_power_control_entity` - required writable battery/base actuator entity that sets the coarse DC-side limit.

If either required key is missing, startup fails.

## Recommended and optional entity inputs

- `net_consumption_entity` - optional signed net import/export sensor in watts from a true grid-boundary meter; leave it unset for derived signals such as house consumption minus inverter output.
- `battery_actual_power_entity` - measured power output of the battery actuator; optional, used for debug/status visibility.
- `inverter_power_control_entity` - optional inverter output-limit entity used as a second gate on the same house-serving power path.
- `inverter_actual_power_entity` - measured power output of the inverter actuator; optional, used for debug/status visibility.
- `battery_temperature_entity` - optional battery temperature sensor in celsius; used for time-weighted temperature metrics today and later thermal policy stages.
- `battery_soc_entity` - battery state of charge sensor in percent; optional, used for reserve protection.
- `battery_discharge_limit_entity` - battery reserve floor in percent; optional, used together with `battery_soc_entity`.

If either battery protection input is missing, the controller skips the SOC-based protection layer. When enabled, the SOC protection applies to the battery actuator. When the battery actuator is temporarily unavailable but the inverter actuator is still available, the controller can continue in inverter-only mode.

## Actuator write settings

- `battery_power_control_service` - optional Home Assistant service override used to write the battery actuator.
- `battery_power_control_value_key` - service field name for the battery actuator numeric target; defaults to `value`.
- `battery_power_control_label` - friendly label for battery-actuator debug output; defaults to `battery_power_control_entity`.
- `inverter_power_control_service` - optional Home Assistant service override used to write the inverter actuator.
- `inverter_power_control_value_key` - service field name for the inverter-actuator numeric target; defaults to `value`.
- `inverter_power_control_label` - friendly label for inverter-actuator debug output; defaults to `inverter_power_control_entity`.

If `power_control_service` is omitted, the wrapper auto-detects:

- `number.*` -> `number/set_value`
- `input_number.*` -> `input_number/set_value`

Other actuator domains must set `power_control_service` explicitly.

## Output range and quantization

- `battery_min_output_w` - minimum allowed battery-actuator target in watts; defaults to the battery entity's numeric `min` attribute when available, otherwise `0`.
- `battery_max_output_w` - maximum allowed battery-actuator target in watts; defaults to the battery entity's numeric `max` attribute when available, otherwise it must be set explicitly.
- `battery_power_step_w` - battery-actuator step size in watts; defaults to the battery entity's numeric `step` attribute when available, otherwise `50`.
- `battery_min_change_w` - minimum battery-actuator target delta before a write is sent; defaults to `battery_power_step_w`.
- `inverter_min_output_w` - minimum allowed inverter-actuator target in watts; defaults to the inverter entity's numeric `min` attribute when available.
- `inverter_max_output_w` - maximum allowed inverter-actuator target in watts; defaults to the inverter entity's numeric `max` attribute when available.
- `inverter_power_step_w` - inverter-actuator step size in watts; defaults to the inverter entity's numeric `step` attribute when available, otherwise `50`.
- `inverter_min_change_w` - minimum inverter-actuator target delta before a write is sent; defaults to `inverter_power_step_w`.

Requested path-cap values are floored to each actuator's configured step so translated commands never overshoot the shared target and accidentally increase probable feed-in.

Startup fails if a configured actuator cannot determine `max_output_w`, or if an actuator's max is lower than its min.

## Control behavior

- `control_interval_s` - seconds between control cycles; default `30`.
- `consumption_ema_tau_s` - smoothing time constant for `consumption_entity`; default `75`.
- `net_ema_tau_s` - smoothing time constant for `net_consumption_entity` when configured; default `45`.
- `baseline_load_w` - constant load offset added to the target calculation; default `0`.
- `deadband_w` - residual error band where no corrective action is taken; default `50`.
- `zero_output_threshold_w` - target values below this are snapped to `0`; default `25`.
- `fast_export_threshold_w` - export threshold that triggers aggressive downward correction when `net_consumption_entity` is configured; default `-80`.
- `import_correction_gain` - gain applied when correcting import when `net_consumption_entity` is configured; default `0.35`.
- `export_correction_gain` - gain applied when correcting export when `net_consumption_entity` is configured; default `1.0`.

## Logging

- `control_cycle_log` - optional AppDaemon user-log name for per-cycle `Control cycle ...` diagnostics.
- `control_cycle_log_level` - level used for those cycle diagnostics; default `DEBUG`.

If `control_cycle_log` is not set, the per-cycle diagnostics stay on the main AppDaemon log at the configured `control_cycle_log_level`. If it is set, those lines are routed to the named AppDaemon user log instead. When that user log is defined without a `filename`, AppDaemon writes it to stdout so it still appears in `journalctl` without creating a separate file.

## Write-rate protection

- `battery_min_write_interval_s` - minimum time between battery-actuator writes; default `60`.
- `battery_max_increase_per_cycle_w` - normal maximum battery-actuator increase per control cycle; default `150`.
- `battery_max_decrease_per_cycle_w` - normal maximum battery-actuator decrease per control cycle; default `300`.
- `battery_emergency_max_decrease_per_cycle_w` - faster battery-actuator decrease limit used during strong export; default `500`.
- `inverter_min_write_interval_s` - minimum time between inverter-actuator writes; default `60`.
- `inverter_max_increase_per_cycle_w` - normal maximum inverter-actuator increase per control cycle; default `150`.
- `inverter_max_decrease_per_cycle_w` - normal maximum inverter-actuator decrease per control cycle; default `300`.
- `inverter_emergency_max_decrease_per_cycle_w` - faster inverter-actuator decrease limit used during strong export; default `500`.

## Battery protection

- `soc_stop_buffer_pct` - stop-output buffer above the configured discharge floor; default `3`.
- `soc_full_power_buffer_pct` - point above the discharge floor where full output is allowed again; default `10`.
- `soc_min_derate_factor` - minimum derate factor inside the SOC ramp region; default `0.25`.

When both battery inputs are present, the controller:

- forces the battery actuator to `0 W` near the reserve floor
- linearly derates the battery actuator above that stop band

## Sign convention and debug output

- `net_export_negative` - `true` when export is reported as a negative net value for `net_consumption_entity`; default `true`.
- `debug_entity_prefix` - prefix used for AppDaemon-published debug sensors; default `sensor.ha_pv_optimization`.
- `dry_run` - if `true`, computes targets and publishes debug state without writing the actuator; default `true` in the AppDaemon wrapper.

When required entities disappear, the status entity also reports availability-oriented attributes such as `availability_state`, `expected_missing_reason`, `warning_active`, and missing timestamps so you can distinguish expected overnight/reserve windows from unexpected outages.

The status entity also publishes time-weighted preview metrics alongside the current EMA-based controller metrics, including `tw_consumption_fast_mean_w`, `tw_consumption_slow_q20_w`, `tw_consumption_pre_event_median_w`, `tw_net_fast_mean_w`, `tw_net_slow_q20_w`, and, when configured, `battery_temperature_t5_c` and `battery_temperature_t30_c`.

## Availability-aware warning behavior

- `availability_warning_grace_s` - seconds to wait before warning after an expected-missing condition clears; default `900`.
- `availability_idle_output_threshold_w` - output threshold treated as effectively idle when inferring expected missing power-control entities; default `20`.
- `availability_low_sun_elevation_deg` - sun elevation below which low-output power-control gaps are still treated as expected; default `10`.

## Full example key list

The generic example currently includes these keys:

- `module`
- `class`
- `site_config_path`
- `consumption_entity`
- `net_consumption_entity`
- `battery_power_control_entity`
- `battery_actual_power_entity`
- `inverter_power_control_entity`
- `inverter_actual_power_entity`
- `battery_temperature_entity`
- `battery_soc_entity`
- `battery_discharge_limit_entity`
- `baseline_load_w`
- `control_interval_s`
- `consumption_ema_tau_s`
- `net_ema_tau_s`
- `deadband_w`
- `zero_output_threshold_w`
- `fast_export_threshold_w`
- `import_correction_gain`
- `export_correction_gain`
- `battery_min_change_w`
- `battery_min_write_interval_s`
- `battery_max_increase_per_cycle_w`
- `battery_max_decrease_per_cycle_w`
- `battery_emergency_max_decrease_per_cycle_w`
- `soc_stop_buffer_pct`
- `soc_full_power_buffer_pct`
- `soc_min_derate_factor`
- `net_export_negative`
- `debug_entity_prefix`
- `dry_run`

The same example also documents these optional keys in comments because they are only needed for some actuators:

- `battery_power_control_service`
- `battery_power_control_value_key`
- `battery_min_output_w`
- `battery_max_output_w`
- `battery_power_step_w`
- `battery_power_control_label`
- `inverter_power_control_service`
- `inverter_power_control_value_key`
- `inverter_min_output_w`
- `inverter_max_output_w`
- `inverter_power_step_w`
- `inverter_power_control_label`
- `inverter_min_change_w`
- `inverter_min_write_interval_s`
- `inverter_max_increase_per_cycle_w`
- `inverter_max_decrease_per_cycle_w`
- `inverter_emergency_max_decrease_per_cycle_w`
- `availability_warning_grace_s`
- `availability_idle_output_threshold_w`
- `availability_low_sun_elevation_deg`

See `examples/apps.yaml.example` for the minimal AppDaemon app block and `examples/site.yaml.example` for the typed site configuration file.
