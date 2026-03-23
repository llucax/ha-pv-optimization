# Configuration

This document describes every AppDaemon app argument used by `examples/apps.yaml.example`.

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

## Required entity inputs

- `consumption_entity` - required main load sensor in watts.
- `power_control_entity` - required writable actuator entity that sets the target power limit.

If either required key is missing, startup fails.

## Recommended and optional entity inputs

- `net_consumption_entity` - optional signed net import/export sensor in watts from a true grid-boundary meter; leave it unset for derived signals such as house consumption minus inverter output.
- `actual_power_entity` - measured power output of the chosen actuator; optional, used for debug/status visibility.
- `battery_soc_entity` - battery state of charge sensor in percent; optional, used for reserve protection.
- `battery_discharge_limit_entity` - battery reserve floor in percent; optional, used together with `battery_soc_entity`.

If either battery protection input is missing, the controller skips the SOC-based protection layer.

## Actuator write settings

- `power_control_service` - optional Home Assistant service override used to write the actuator.
- `power_control_value_key` - service field name for the numeric target; defaults to `value`.
- `power_control_label` - friendly label for debug output; defaults to `power_control_entity`.

If `power_control_service` is omitted, the wrapper auto-detects:

- `number.*` -> `number/set_value`
- `input_number.*` -> `input_number/set_value`

Other actuator domains must set `power_control_service` explicitly.

## Output range and quantization

- `min_output_w` - minimum allowed target in watts; defaults to the actuator's numeric `min` attribute when available, otherwise `0`.
- `max_output_w` - maximum allowed target in watts; defaults to the actuator's numeric `max` attribute when available, otherwise it must be set explicitly.
- `power_step_w` - actuator step size in watts; defaults to the actuator's numeric `step` attribute when available, otherwise `50`.
- `min_change_w` - minimum target delta before a write is sent; defaults to `power_step_w`.

Startup fails if `max_output_w` cannot be determined, or if `max_output_w < min_output_w`.

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

## Write-rate protection

- `min_write_interval_s` - minimum time between writes; default `60`.
- `max_increase_per_cycle_w` - normal maximum increase per control cycle; default `150`.
- `max_decrease_per_cycle_w` - normal maximum decrease per control cycle; default `300`.
- `emergency_max_decrease_per_cycle_w` - faster decrease limit used during strong export; default `500`.

## Battery protection

- `soc_stop_buffer_pct` - stop-output buffer above the configured discharge floor; default `3`.
- `soc_full_power_buffer_pct` - point above the discharge floor where full output is allowed again; default `10`.
- `soc_min_derate_factor` - minimum derate factor inside the SOC ramp region; default `0.25`.

When both battery inputs are present, the controller:

- forces output to `0 W` near the reserve floor
- linearly derates output above that stop band

## Sign convention and debug output

- `net_export_negative` - `true` when export is reported as a negative net value for `net_consumption_entity`; default `true`.
- `debug_entity_prefix` - prefix used for AppDaemon-published debug sensors; default `sensor.ha_pv_optimization`.
- `dry_run` - if `true`, computes targets and publishes debug state without writing the actuator; default `true` in the AppDaemon wrapper.

## Full example key list

The generic example currently includes these keys:

- `module`
- `class`
- `consumption_entity`
- `net_consumption_entity`
- `power_control_entity`
- `actual_power_entity`
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
- `min_change_w`
- `min_write_interval_s`
- `max_increase_per_cycle_w`
- `max_decrease_per_cycle_w`
- `emergency_max_decrease_per_cycle_w`
- `soc_stop_buffer_pct`
- `soc_full_power_buffer_pct`
- `soc_min_derate_factor`
- `net_export_negative`
- `debug_entity_prefix`
- `dry_run`

The same example also documents these optional keys in comments because they are only needed for some actuators:

- `power_control_service`
- `power_control_value_key`
- `min_output_w`
- `max_output_w`
- `power_step_w`
- `power_control_label`

See `examples/apps.yaml.example` for the complete starting configuration.
