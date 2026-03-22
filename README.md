# pv_optimization

`pv_optimization` is a reusable Home Assistant / AppDaemon controller for coarse PV and battery power-setpoint optimization.

It is designed for installations where Home Assistant exposes:

- a main consumption sensor in watts
- optionally a net import/export sensor in watts
- one writable power-limit actuator
- optionally battery SoC and discharge-floor entities

The controller smooths demand, applies optional net-balance correction, rate-limits writes, and exposes debug entities in Home Assistant.

## Status and transparency

This project was developed and exercised on a real setup built around:

- a Growatt NOAH 2000 battery
- an APsystems EZ1-M inverter
- Home Assistant with AppDaemon

The code is intentionally more generic than that setup, but it is still opinionated.
It assumes a single live actuator, a coarse control cadence, and a topology where changing the chosen power limit predictably affects household import/export.

See `docs/ASSUMPTIONS.md` for the current fit and limitations.

## What it does

- reads a configurable consumption entity
- optionally reads a net-power entity for import/export correction
- writes a configurable power-control service/entity in coarse steps
- optionally uses battery SoC plus reserve floor as a safety limit
- publishes debug entities for rollout and tuning
- defaults to safe `dry_run` behavior in the AppDaemon wrapper

## Repository layout

- `src/pv_optimization/` - package code
- `tests/` - unit tests for the controller core
- `examples/` - generic AppDaemon, bridge, and systemd examples
- `docs/` - generic install, configuration, and assumptions docs

## Quick start

```bash
uv sync --dev
uv run pytest
uv run ruff check src tests
```

For deployment guidance, start with:

- `docs/INSTALL.md`
- `docs/CONFIGURATION.md`
- `docs/ASSUMPTIONS.md`

## AppDaemon integration

The package contains the AppDaemon class, but a typical deployment still uses a tiny bridge module in the AppDaemon apps directory.

Example bridge file: `examples/pv_optimization_app.py`

Example app config: `examples/apps.yaml.example`

Example AppDaemon config: `examples/appdaemon.yaml.example`

An opinionated Docker + systemd example is included in `examples/systemd/`.
