# ha-pv-optimization

`ha-pv-optimization` is an opinionated Home Assistant / AppDaemon controller for a Growatt NOAH 2000 battery feeding an APsystems EZ1-M inverter.

It is designed for installations where Home Assistant exposes:

- a main consumption sensor in watts
- optionally a net import/export sensor in watts
- a battery power-limit actuator
- optionally an inverter power-limit actuator on the same output path
- optionally battery SoC and discharge-floor entities

The controller smooths demand, applies optional net-balance correction, drives the battery and inverter as two gates on the same house-serving path, rate-limits writes, and exposes debug entities in Home Assistant.

## Status and transparency

This project was developed and exercised on a real setup built around:

- a Growatt NOAH 2000 battery
- an APsystems EZ1-M inverter
- Home Assistant with AppDaemon

The code remains adaptable, but the defaults, docs, and examples now intentionally assume that NOAH 2000 plus EZ1-M style topology.

See `docs/ASSUMPTIONS.md` for the current fit and limitations.

## What it does

- reads a configurable consumption entity
- optionally reads a net-power entity for import/export correction
- writes a battery output limit and optionally an inverter output limit
- optionally uses battery SoC plus reserve floor as a safety limit on the battery path
- publishes debug entities for rollout and tuning
- defaults to safe `dry_run` behavior in the AppDaemon wrapper

## Repository layout

- `src/ha_pv_optimization/` - package code
- `tests/` - unit tests for the controller core
- `examples/` - AppDaemon, secrets, and systemd examples for the NOAH 2000 plus EZ1-M style deployment
- `docs/` - install, configuration, and assumptions docs for this AppDaemon-focused project

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

The package contains the AppDaemon class itself and is intended to be mounted directly into an AppDaemon deployment.

A tiny bridge module is still included for deployments that prefer AppDaemon to load a one-line file from the apps directory.

Example bridge file: `examples/ha_pv_optimization_app.py`

Example app config: `examples/apps.yaml.example`

Example AppDaemon config: `examples/appdaemon.yaml.example`

Example AppDaemon secrets file: `examples/secrets.yaml.example`

An opinionated Docker + systemd example is included in `examples/systemd/`.
