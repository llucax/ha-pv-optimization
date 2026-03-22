# Configuration

## Required AppDaemon arguments

- `consumption_entity` - main load sensor in watts
- `power_control_entity` - numeric actuator state entity

## Strongly recommended inputs

- `net_consumption_entity` - signed import/export signal in watts
- `battery_soc_entity` - battery state of charge in percent if reserve protection matters
- `battery_discharge_limit_entity` - reserve floor in percent if available

## Actuator write settings

- `power_control_service` - optional override for the HA service used to write the actuator
- `power_control_value_key` - service field used for the numeric target, defaults to `value`
- `power_control_label` - optional friendly label for debug output

If `power_control_service` is omitted, the wrapper auto-detects:

- `number.*` -> `number/set_value`
- `input_number.*` -> `input_number/set_value`

Other entity domains must configure `power_control_service` explicitly.

## Output range and quantization

These settings control the actuator range:

- `min_output_w`
- `max_output_w`
- `power_step_w`
- `min_change_w`

The wrapper tries to infer `min_output_w`, `max_output_w`, and `power_step_w` from the actuator entity attributes.

If the entity does not expose a numeric `max`, set `max_output_w` explicitly.

`min_change_w` defaults to `power_step_w` when not set.

## Control behavior

- `control_interval_s` - default `30`
- `consumption_ema_tau_s` - default `75`
- `net_ema_tau_s` - default `45`
- `baseline_load_w` - default `0`
- `deadband_w` - default `50`
- `zero_output_threshold_w` - default `25`
- `fast_export_threshold_w` - default `-80`
- `import_correction_gain` - default `0.35`
- `export_correction_gain` - default `1.0`

## Write-rate protection

- `min_write_interval_s` - default `60`
- `max_increase_per_cycle_w` - default `150`
- `max_decrease_per_cycle_w` - default `300`
- `emergency_max_decrease_per_cycle_w` - default `500`

## Battery protection

- `soc_stop_buffer_pct` - default `3`
- `soc_full_power_buffer_pct` - default `10`
- `soc_min_derate_factor` - default `0.25`

If both `battery_soc_entity` and `battery_discharge_limit_entity` are configured, the controller:

- forces output to `0 W` near the reserve floor
- linearly derates output above that stop band

If either input is missing, the controller skips this protection layer.

## Sign convention and debug output

- `net_export_negative` - default `true`; set to `false` if your net sensor uses the opposite sign
- `debug_entity_prefix` - default `sensor.pv_optimization`
- `dry_run` - default `true` in the AppDaemon wrapper for a safer first rollout

## Example

See `examples/apps.yaml.example` for a complete starting configuration.
