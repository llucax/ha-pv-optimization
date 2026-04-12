from __future__ import annotations

from pathlib import Path

from ha_pv_optimization.config import (
    controller_config_from_site_config,
    load_site_config,
    site_config_to_appdaemon_args,
)


def test_load_site_config_and_flatten_to_appdaemon_args(tmp_path: Path) -> None:
    config_path = tmp_path / "site.yaml"
    config_path.write_text(
        "consumption:\n"
        "  entity: sensor.total_consumption_power\n"
        "battery:\n"
        "  power_control_entity: number.noah_limit\n"
        "  max_output_w: 800\n"
        "  power_step_w: 50\n"
        "battery_sensors:\n"
        "  soc_entity: sensor.noah_soc\n"
        "  temperature_entity: sensor.noah_temp\n"
        "  charging_limit_entity: number.noah_charge_limit\n"
        "  heating_entity: binary_sensor.noah_heating\n"
        "inverter:\n"
        "  power_control_entity: number.ez1_limit\n"
        "  max_output_w: 800\n"
        "  min_output_w: 30\n"
        "control:\n"
        "  baseline_load_w: 10\n"
        "  allow_full_soc_inverter_pass_through: true\n"
        "thermal:\n"
        "  normal_min_soc_pct: 15\n"
        "devices:\n"
        "  microwave:\n"
        "    kind: burst_high_power\n"
        "    entity_id: sensor.outlet_microwave_power\n"
        "logging:\n"
        "  debug_entity_prefix: sensor.ha_pv_optimization\n",
        encoding="utf-8",
    )

    site_config = load_site_config(config_path)
    flattened = site_config_to_appdaemon_args(site_config)
    controller_config = controller_config_from_site_config(site_config)

    assert flattened["consumption_entity"] == "sensor.total_consumption_power"
    assert flattened["battery_power_control_entity"] == "number.noah_limit"
    assert flattened["battery_temperature_entity"] == "sensor.noah_temp"
    assert flattened["battery_charging_limit_entity"] == "number.noah_charge_limit"
    assert flattened["battery_heating_entity"] == "binary_sensor.noah_heating"
    assert flattened["inverter_power_control_entity"] == "number.ez1_limit"
    assert flattened["baseline_load_w"] == 10.0
    assert flattened["allow_full_soc_inverter_pass_through"] is True
    assert controller_config.battery_actuator.max_output_w == 800.0
    assert controller_config.allow_full_soc_inverter_pass_through is True
    assert controller_config.thermal_policy.normal_min_soc_pct == 15.0
    assert site_config.devices["microwave"].entity_id == "sensor.outlet_microwave_power"
    assert controller_config.inverter_actuator is not None
    assert controller_config.inverter_actuator.min_output_w == 30.0
