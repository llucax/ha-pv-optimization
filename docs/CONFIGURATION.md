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
- `battery_charging_limit_entity` - battery max-SOC rail entity in percent; optional until thermal/SOC rail control is enabled.
- `battery_heating_entity` - optional NOAH heating-status binary sensor.
- `battery_high_temp_alarm_entity` - optional high-temperature alarm binary sensor or problem entity; when active it pushes the controller into the `VERY_HOT` state.

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
- `baseline_load_w` - constant load offset added to the target calculation; default `0`.
- `zero_output_threshold_w` - target values below this are snapped to `0`; default `25`.

The current aggregate controller is command-state based. It uses the time-weighted metrics published by the AppDaemon wrapper and the following tuning fields:

- `command_step_w` - internal path-cap quantization step before actuator translation; default `10`.
- `command_lockout_s` - seconds to suppress additional fast/slow trim after a fast event; default `12`.
- `slow_up_deadband_w` - slow upward trim deadband; default `80`.
- `slow_down_deadband_w` - slow downward trim deadband; default `-40`.
- `minor_up_event_threshold_w` - aggregate step threshold for a smaller upward event; default `150`.
- `major_up_event_threshold_w` - aggregate step threshold for a larger upward event; default `400`.
- `down_event_threshold_w` - aggregate step threshold for a downward event; default `-150`.
- `minor_up_persistence_s` - persistence requirement for a minor upward event; default `3`.
- `major_up_persistence_s` - persistence requirement for a major upward event; default `2`.
- `down_event_persistence_s` - persistence requirement for a downward event; default `3`.
- `minor_up_multiplier` - multiplier applied to a minor upward event delta; default `0.75`.
- `major_up_multiplier` - multiplier applied to a major upward event delta; default `0.90`.
- `down_event_multiplier` - multiplier applied to a downward event delta; default `0.90`.
- `slow_up_gain` - gain for slow upward trim; default `0.50`.
- `slow_up_max_step_w` - maximum upward trim per cycle; default `100`.
- `slow_down_guard_w` - extra downward trim guard added to the fast error magnitude; default `20`.
- `slow_down_max_step_w` - maximum downward trim per cycle; default `300`.
- `visible_oversupply_one_sample_w` - immediate severe oversupply threshold based on visible load minus inverter output; default `-120`.
- `visible_oversupply_two_sample_w` - moderate oversupply threshold that must persist twice; default `-60`.
- `visible_oversupply_max_cut_w` - maximum cut used by the oversupply safeguard; default `500`.

Legacy EMA/net-correction knobs remain in the config surface for compatibility with older configs and the preview metrics, but the current Stage 8 aggregate loop primarily relies on the command-state/event-path fields above plus the time-weighted metrics from the wrapper.

## Logging

- `control_cycle_log` - optional AppDaemon user-log name for per-cycle `Control cycle ...` diagnostics.
- `control_cycle_log_level` - level used for those cycle diagnostics; default `DEBUG`.
- `thermal_log` - optional AppDaemon user-log name for periodic thermal heartbeat diagnostics.
- `thermal_log_level` - level used for those thermal heartbeat diagnostics; default `DEBUG`.

If `control_cycle_log` is not set, the per-cycle diagnostics stay on the main AppDaemon log at the configured `control_cycle_log_level`. If it is set, those lines are routed to the named AppDaemon user log instead. When that user log is defined without a `filename`, AppDaemon writes it to stdout so it still appears in `journalctl` without creating a separate file.

Thermal state transitions are still logged at `INFO` on the main log. The optional `thermal_log` is for lower-priority thermal heartbeats and detailed subsystem visibility when you want to debug thermal behavior without increasing the noise on the main log.

## Write-rate protection

- `battery_min_write_interval_s` - minimum time between battery-actuator writes; default `60`.
- `battery_max_increase_per_cycle_w` - normal maximum battery-actuator increase per control cycle; default `150`.
- `battery_max_decrease_per_cycle_w` - normal maximum battery-actuator decrease per control cycle; default `300`.
- `battery_emergency_max_decrease_per_cycle_w` - faster battery-actuator decrease limit used during strong export; default `500`.
- `inverter_min_write_interval_s` - minimum time between inverter-actuator writes; default `60`.
- `inverter_max_increase_per_cycle_w` - normal maximum inverter-actuator increase per control cycle; default `150`.
- `inverter_max_decrease_per_cycle_w` - normal maximum inverter-actuator decrease per control cycle; default `300`.
- `inverter_emergency_max_decrease_per_cycle_w` - faster inverter-actuator decrease limit used during strong export; default `500`.

## Thermal policy

- `thermal_normal_min_soc_pct` - desired discharge-floor rail in the `NORMAL` state; default `15`.
- `thermal_normal_max_soc_pct` - desired charging-limit rail in the `NORMAL` state; default `95`.
- `thermal_normal_cap_limit_w` - battery-side output cap in the `NORMAL` state; default `800`.
- `thermal_hot_enter_t30_c` - enter `HOT` when the 30-minute temperature mean reaches this threshold; default `35`.
- `thermal_hot_exit_t30_c` - allow exit from `HOT` when the 30-minute temperature mean stays below this threshold; default `33`.
- `thermal_hot_exit_hold_s` - seconds below the `HOT` exit threshold before leaving `HOT`; default `3600`.
- `thermal_hot_min_soc_pct` - desired discharge-floor rail in `HOT`; default `15`.
- `thermal_hot_max_soc_pct` - desired charging-limit rail in `HOT`; default `90`.
- `thermal_hot_cap_limit_w` - battery-side output cap in `HOT`; default `800`.
- `thermal_very_hot_enter_t30_c` - enter `VERY_HOT` when the 30-minute temperature mean reaches this threshold; default `40`.
- `thermal_very_hot_enter_t5_c` - enter `VERY_HOT` when the 5-minute temperature mean reaches this threshold; default `45`.
- `thermal_very_hot_exit_t30_c` - allow exit from `VERY_HOT` when the 30-minute temperature mean stays below this threshold; default `38`.
- `thermal_very_hot_exit_t5_c` - allow exit from `VERY_HOT` when the 5-minute temperature mean stays below this threshold; default `43`.
- `thermal_very_hot_exit_hold_s` - seconds below the `VERY_HOT` exit thresholds before leaving `VERY_HOT`; default `3600`.
- `thermal_very_hot_min_soc_pct` - desired discharge-floor rail in `VERY_HOT`; default `20`.
- `thermal_very_hot_max_soc_pct` - desired charging-limit rail in `VERY_HOT`; default `85`.
- `thermal_very_hot_cap_limit_w` - battery-side output cap in `VERY_HOT`; default `400`.

These thermal state outputs now drive:

- the battery-side cap ceiling used by the controller
- the desired `number.growatt_noah_2000_discharge_limit` target
- the desired `number.growatt_noah_2000_charging_limit` target

## Device feed-forward

Per-device feed-forward is configured through the typed `devices:` section in `site.yaml`, not through flat AppDaemon args.

Each device entry supports:

- `kind` - one of:
  - `burst_high_power`
  - `cyclic_heater`
  - `composite_kitchen_outlet`
- `entity_id` - Home Assistant power entity for that device or outlet
- `enabled` - whether the device model is active
- `low_threshold_w` - optional low threshold used by `cyclic_heater`
- `high_threshold_w` - threshold for the high-power state
- `enter_persistence_s` - seconds required before entering the active state
- `exit_persistence_s` - seconds required before leaving the active state
- `ff_gain` - multiplier applied to the observed device power when the transition bias activates
- `ff_hold_s` - how long the temporary feed-forward bias stays active after a high-power transition

For this site, the current feed-forward device set enables:

- microwave
- under-cabinet appliances (composite outlet)
- oven
- dishwasher

The controller publishes these device-feed-forward diagnostics in the status entity:

- `device_feed_forward_w`
- `active_device_feed_forward`
- `device_contributions`

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

Dual-gate planning diagnostics are also published, including `degraded_mode`, `degraded_reasons`, `battery_command_mismatch_reason`, `battery_command_mismatch_w`, `inverter_command_mismatch_reason`, and `inverter_command_mismatch_w`.

Current mismatch classification is heuristic:

- `probable_rejected_command` means the actuator still matches the pre-command observed value after the grace window, so the controller write appears not to have taken effect.
- `probable_external_override` means the actuator moved away from the controller target to a third value after the grace window, which likely indicates either a schedule override or a manual override.

Thermal/SOC diagnostics are also published, including `thermal_state`, `desired_min_soc_pct`, `desired_max_soc_pct`, `battery_cap_limit_w`, `battery_min_soc_action`, and `battery_max_soc_action`.

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
