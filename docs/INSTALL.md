# Install

This project is a normal Python package for development, but AppDaemon still expects a module inside its apps directory.

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

Copy `examples/pv_optimization_app.py` into your AppDaemon apps directory.

Example target layout:

```text
/srv/pv_optimization/
  appdaemon.yaml
  systemd.env
  apps/
    apps.yaml
    pv_optimization_app.py
```

The bridge module keeps AppDaemon's app loading simple while the real code stays in this package.

## AppDaemon config

Use these files as starting points:

- `examples/appdaemon.yaml.example`
- `examples/apps.yaml.example`
- `examples/systemd/pv-optimization.service`
- `examples/systemd/pv-optimization.env.example`

## Opinionated Docker + systemd deployment

The example service file assumes:

- AppDaemon runs in Docker
- the AppDaemon config directory is mounted at `/conf`
- this project is mounted read-only at `/opt/pv_optimization`
- `PYTHONPATH=/opt/pv_optimization/src`

Suggested host layout:

```text
/srv/pv_optimization/
  appdaemon.yaml
  systemd.env
  apps/
    apps.yaml
    pv_optimization_app.py

/srv/pv_optimization-src/
  pyproject.toml
  src/
  docs/
  examples/
```

The service example references `/srv/pv_optimization/systemd.env` for runtime configuration.

## Rollout guidance

Start with `dry_run: true` and verify:

- the configured entities exist
- the debug entities appear
- `sensor.pv_optimization_target_limit` tracks your expectation
- the chosen actuator and measured net power move in the same direction

Only then switch to live writes.
