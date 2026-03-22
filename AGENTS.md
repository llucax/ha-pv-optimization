# AGENTS.md

## Scope
This directory is the generic, public-safe `pv_optimization` project.

It contains a reusable Home Assistant / AppDaemon controller for coarse PV and battery power-setpoint optimization.

Do not place installation-specific data here.

## Privacy and repository boundary
- Keep entity examples generic.
- Do not add hostnames, serial numbers, real IPs, real domains, or private Home Assistant paths here.
- Do not copy support snapshots from a real installation into this project.
- Site-specific notes belong in the private site repository, not here.

## Project structure
- `src/pv_optimization/` - installable Python package
- `tests/` - unit tests for the pure controller logic
- `examples/` - generic AppDaemon and deployment examples
- `docs/` - generic install, configuration, and assumptions docs

## Architecture expectations
- Keep the Home Assistant / AppDaemon wrapper thin.
- Keep decision logic in `src/pv_optimization/core.py` as pure Python.
- Document assumptions explicitly when adding new behavior.
- Prefer configurability over device-specific branching.
- Preserve safe behavior: clamping, deadbands, slew limits, minimum write intervals, and `dry_run`.

## App assumptions
- The controller is intentionally opinionated, not universal.
- It assumes one live power-control actuator at a time.
- It assumes a numeric actuator that accepts a non-negative power limit.
- It assumes the actuator affects the same electrical boundary measured by the configured consumption/net sensors.
- It is designed for coarse control on the order of tens of seconds, not fast inverter EMS loops.

## Development workflow
Use commands from this directory.

### Install dev environment
```bash
uv sync --dev
```

### Lint
```bash
uv run ruff check src tests
```

### Format
```bash
uv run ruff format src tests
```

### Tests
```bash
uv run pytest
```

## Documentation rules
- Keep `README.md` focused on the generic project.
- Keep `docs/ASSUMPTIONS.md` current when topology or actuator assumptions change.
- Keep `docs/CONFIGURATION.md` current when config keys change.
- Keep `docs/INSTALL.md` current when deployment guidance changes.

## Practical guidance
- Prefer small, targeted edits.
- Add or update tests when changing controller behavior.
- If a new feature only works for one vendor or topology, call that out clearly in the docs.
