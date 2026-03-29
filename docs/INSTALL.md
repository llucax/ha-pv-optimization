# Install

This project is an AppDaemon-focused Python package for the NOAH 2000 plus EZ1-M style setup.

It is still installable as a normal Python project for development, but the intended runtime is Home Assistant plus AppDaemon.

The common deployment pattern is:

1. keep this project checked out on the host
2. mount the project into the AppDaemon container
3. expose `src/` through `PYTHONPATH`
4. place a tiny bridge module in the AppDaemon apps directory
5. configure the app instance in `apps.yaml`

## Local development

From the project root:

```bash
uv sync --dev
uv run pytest
uv run ruff check src tests
```

## Bridge module

Copy `examples/ha_pv_optimization_app.py` into your AppDaemon apps directory.

Example target layout:

```text
/srv/ha-pv-optimization/
  appdaemon.yaml
  secrets.yaml
  systemd.env
  apps/
    apps.yaml
    ha_pv_optimization_app.py
```

The bridge module keeps AppDaemon's app loading simple while the real code stays in this package.

## AppDaemon config

Use these files as starting points:

- `examples/appdaemon.yaml.example`
- `examples/secrets.yaml.example`
- `examples/apps.yaml.example`
- `examples/systemd/ha-pv-optimization.service`
- `examples/systemd/ha-pv-optimization.env.example`

## Example file reference

### `examples/appdaemon.yaml.example`

- `secrets` - explicit AppDaemon secrets file path.
- `appdaemon.time_zone` - AppDaemon-wide timezone used for scheduling and timestamps.
- `appdaemon.latitude` - required site latitude in decimal degrees.
- `appdaemon.longitude` - required site longitude in decimal degrees.
- `appdaemon.elevation` - required site elevation in meters.
- `appdaemon.plugins.HASS.type` - AppDaemon plugin type; keep `hass` for Home Assistant.
- `appdaemon.plugins.HASS.ha_url` - Home Assistant base URL that AppDaemon connects to.
- `appdaemon.plugins.HASS.token` - Home Assistant long-lived access token loaded via `!secret`.
- `appdaemon.plugins.HASS.cert_verify` - whether TLS certificates are verified for the Home Assistant endpoint.
- `http`, `admin`, `api` - optional AppDaemon web/UI sections; omit them unless you want AppDaemon's own web UI or API.

### `examples/secrets.yaml.example`

- `ha_token` - Home Assistant long-lived access token used by `examples/appdaemon.yaml.example`.

### `examples/apps.yaml.example`

Every app-specific key is documented in `docs/CONFIGURATION.md`.

The example includes:

- required AppDaemon loading keys: `module`, `class`
- required controller entities: `consumption_entity`, `battery_power_control_entity`
- optional sensors: `net_consumption_entity` (only for a true grid-boundary import/export meter), `battery_actual_power_entity`, `inverter_actual_power_entity`, `battery_soc_entity`, `battery_discharge_limit_entity`
- optional inverter-actuator entity: `inverter_power_control_entity`
- optional actuator overrides: `battery_power_control_service`, `battery_power_control_value_key`, `battery_power_control_label`, `inverter_power_control_service`, `inverter_power_control_value_key`, `inverter_power_control_label`
- optional output range overrides: `battery_min_output_w`, `battery_max_output_w`, `battery_power_step_w`, `inverter_min_output_w`, `inverter_max_output_w`, `inverter_power_step_w`
- control tuning and safety settings such as `control_interval_s`, `deadband_w`, `min_write_interval_s`, `dry_run`, and availability-warning tuning keys

The defaults assume a NOAH 2000 battery gate and an optional EZ1-M inverter gate on the same house-serving power path.

### `examples/ha_pv_optimization_app.py`

- This bridge module has no user-facing config keys.
- Its only job is to expose the packaged controller to AppDaemon from the apps directory.

### `examples/systemd/ha-pv-optimization.env.example`

- `DOCKER_IMAGE` - AppDaemon image tag to run.
- `CONFIG_DIR` - host config directory mounted into the container at `/conf`.
- `PROJECT_DIR` - host checkout of this project mounted into the container.
- `DOCKER_UID` - uid used to run the container process.
- `DOCKER_GID` - gid used to run the container process.

### `examples/systemd/ha-pv-optimization.service`

- `EnvironmentFile=/srv/ha-pv-optimization/systemd.env` - loads the deployment-specific values above.
- `ExecStartPre` cleanup lines stop and remove any previous container with the same name.
- `ExecStartPre` pull line refreshes the configured AppDaemon image before start.
- `--name %n` names the container after the systemd unit.
- `--network=host` lets the container talk to Home Assistant without extra port mapping.
- `--user "$DOCKER_UID:$DOCKER_GID"` runs as the configured non-root uid/gid.
- `--cap-drop=ALL` and `--security-opt=no-new-privileges:true` keep privileges tight.
- `--read-only` and `--tmpfs /tmp` keep the container filesystem mostly immutable.
- `-e PYTHONPATH=/opt/ha-pv-optimization/src` exposes the package source tree to AppDaemon.
- `-v /etc/localtime:/etc/localtime:ro` keeps timezone data aligned with the host.
- `-v "$CONFIG_DIR":/conf` mounts the AppDaemon config directory.
- `-v "$PROJECT_DIR":/opt/ha-pv-optimization:ro` mounts this project read-only.
- `ExecStop=/usr/bin/docker stop %n` stops the running container when the unit stops.

## Opinionated Docker + systemd deployment

The example service file assumes:

- AppDaemon runs in Docker
- the AppDaemon config directory is mounted at `/conf`
- this project is mounted read-only at `/opt/ha-pv-optimization`
- `PYTHONPATH=/opt/ha-pv-optimization/src`

Suggested host layout:

```text
/srv/ha-pv-optimization/
  appdaemon.yaml
  secrets.yaml
  systemd.env
  apps/
    apps.yaml
    ha_pv_optimization_app.py

/srv/ha-pv-optimization-src/
  pyproject.toml
  src/
  docs/
  examples/
```

The service example references `/srv/ha-pv-optimization/systemd.env` for runtime configuration.

## Rollout guidance

Start with `dry_run: true` and verify:

- the configured entities exist
- the debug entities appear
- `sensor.ha_pv_optimization_target_limit` tracks your expectation
- the chosen actuator and measured net power move in the same direction

Only then switch to live writes.
