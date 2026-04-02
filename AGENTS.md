# AGENTS.md

This repository contains an opinionated Home Assistant / AppDaemon controller for a Growatt NOAH 2000 battery feeding an APsystems EZ1-M inverter.

This file is for coding agents working in this repo.

## Repository boundary
- Keep the project adaptable, but let defaults and docs assume the NOAH 2000 plus EZ1-M style setup.
- Do not add installation-specific data, hostnames, serial numbers, real IPs, real domains, secrets, or local Home Assistant paths.
- Do not copy support snapshots or operational telemetry into the repo.

## Project layout
- `src/ha_pv_optimization/` - installable package code.
- `src/ha_pv_optimization/models.py` - typed controller config, inputs, and results.
- `src/ha_pv_optimization/config.py` - typed site config models, loader, and conversion helpers.
- `src/ha_pv_optimization/signals.py` - pure signal math, time-weighted series, and reusable helpers.
- `src/ha_pv_optimization/device_models.py` - reusable per-device feed-forward models and runtime state.
- `src/ha_pv_optimization/controller.py` - pure controller orchestration and decision logic.
- `src/ha_pv_optimization/core.py` - compatibility re-export layer for the controller API.
- `src/ha_pv_optimization/appdaemon.py` - AppDaemon wrapper; keep it thin.
- `src/ha_pv_optimization/replay.py` - CSV trace loading, replay execution, and baseline scorecards.
- `tests/` - unit tests for the core logic.
- `tests/test_signals.py` - focused tests for time-weighted signal handling.
- `tests/test_device_models.py` - focused tests for per-device feed-forward model transitions and contributions.
- `docs/` - assumptions, configuration, and install guidance.
- `examples/` - opinionated AppDaemon and systemd examples for the NOAH 2000 plus EZ1-M style deployment.

## Architecture expectations
- Keep control logic pure and deterministic in `src/ha_pv_optimization/controller.py`, `src/ha_pv_optimization/models.py`, and `src/ha_pv_optimization/signals.py`.
- Keep Home Assistant / AppDaemon integration as translation and I/O glue only.
- Keep typed site config loading in `src/ha_pv_optimization/config.py`; avoid spreading YAML parsing across the wrapper and replay code.
- Prefer device-specific defaults and config names that match the battery-plus-inverter gate model used by this project.
- Preserve safety behavior: clamping, deadbands, slew limits, minimum write intervals, and `dry_run`.
- Document changed assumptions whenever behavior, topology fit, or config semantics change.

## Environment and tooling
- Python version: 3.11+.
- Package/build backend: Hatchling.
- Dependency manager and task runner: `uv`.
- Lint/format tool: Ruff.
- Test framework: Pytest.

## Setup commands
Run commands from the repository root.

```bash
uv sync --dev
```

## Build commands
- Build the package: `uv build`
- Check `pyproject.toml` before changing packaging metadata or build settings.

## Lint and format commands
- Check lint: `uv run ruff check src tests`
- Apply safe lint fixes: `uv run ruff check --fix src tests`
- Format code: `uv run ruff format src tests`
- Recommended validation after edits:

```bash
uv run ruff check src tests
uv run ruff format src tests
uv run pytest
```

## Test commands
- Run all tests: `uv run pytest`
- Run one test file: `uv run pytest tests/test_core.py`
- Run one test by node id: `uv run pytest tests/test_core.py::test_fast_export_reduces_output_quickly`
- Run tests matching an expression: `uv run pytest -k fast_export`
- Run one file with verbose output: `uv run pytest -vv tests/test_core.py`
- Run replay tests: `uv run pytest tests/test_replay.py`

## When to run what
- For changes in `src/ha_pv_optimization/controller.py`, `src/ha_pv_optimization/models.py`, or `src/ha_pv_optimization/signals.py`, run at least the focused core test file plus lint.
- For changes in `src/ha_pv_optimization/config.py`, run config-related tests plus the full suite.
- For changes in `src/ha_pv_optimization/signals.py`, also run `tests/test_signals.py` and any replay tests affected by the window semantics.
- For changes in `src/ha_pv_optimization/device_models.py`, run `tests/test_device_models.py` and replay if the configured device set changes.
- For changes in `src/ha_pv_optimization/replay.py`, run replay tests plus the full suite.
- For changes in thermal policy or battery-temperature handling, rerun replay with the battery temperature trace when available.
- For behavior changes, add or update tests in `tests/test_core.py`.
- For wrapper/config/docs changes, run lint and the full test suite unless the change is purely documentation.
- For packaging or import-path changes, run `uv build` in addition to lint/tests.
- For changes likely to affect replay outcomes, rerun the replay command against the site traces and append a new row to the root repo's `reference/replay_scorecard_history.csv`.

## Coding style
- Follow existing Ruff formatting; do not hand-format against it.
- Use 4-space indentation and keep code Black/Ruff-compatible.
- Prefer small, targeted edits over broad refactors.
- Preserve ASCII unless a file already requires Unicode.
- Use `from __future__ import annotations` in Python modules, matching the existing codebase.
- Favor clear, direct control flow over clever abstractions.

## Imports
- Group imports as: standard library, third-party, then local package imports.
- Separate import groups with a single blank line.
- Prefer explicit imports over wildcard imports.
- In package modules, follow the existing relative-import style such as `from .models import ...`.
- In tests, import the package API directly and prefer pytest configuration over manual path bootstrapping.

## Types and data modeling
- Add type hints to public functions, methods, and important locals when helpful.
- Prefer builtin generic syntax like `list[str]` and `dict[str, Any]`.
- Use dataclasses for structured controller config, inputs, and results.
- Keep state representation simple and explicit; avoid hidden mutation.
- Use `float | None` and `str | None` rather than `Optional[...]`.
- Prefer frozen dataclasses when values should not change after construction.

## Naming conventions
- Use `snake_case` for functions, methods, variables, and config fields.
- Use `PascalCase` for classes and dataclasses.
- Keep names descriptive and domain-specific: `net_consumption_w`, `allowed_max_output_w`, `seconds_since_last_write`.
- Suffix watt values with `_w`, seconds with `_s`, and percentages with `_pct`.
- Prefix internal helpers with `_` when they are module-private.

## Function design
- Keep pure calculations in helpers or in `PowerControllerCore.step()`.
- Make wrapper helpers responsible for parsing Home Assistant/AppDaemon inputs into plain Python values.
- Prefer returning structured data over ad-hoc tuples or dicts when the shape is stable.
- Keep methods focused; split parsing, validation, and publishing helpers when wrapper methods grow broad.

## Error handling and validation
- Raise `ValueError` for invalid or missing configuration that should block startup.
- Return `None` from parsing helpers when Home Assistant state is unavailable or non-numeric.
- Catch narrow exceptions only; current code catches `TypeError` and `ValueError` when coercing floats.
- Do not swallow configuration problems silently.
- Prefer safe defaults only when they are intentional and documented.
- Preserve the AppDaemon import fallback so tests and local imports work without the runtime installed.

## Controller-specific guidance
- Do not move Home Assistant service calls into the core controller.
- Keep the controller numerically conservative and explain any default change.
- Maintain quantization, clamp behavior, and slew limiting unless the change explicitly redesigns control behavior.
- When translating a shared path target to per-actuator commands, prefer non-overshooting flooring behavior over nearest-step rounding so the controller does not exceed the intended cap.
- Preserve `dry_run` semantics for safe rollout.
- If you add a new control input or config key, thread it through config docs, assumptions, examples, and tests.
- Treat the topology as `PV -DC-> battery -DC-> inverter -AC-> house`, with battery and inverter acting as two gates on the same output path rather than additive outputs.
- When editing Stage 6 thermal behavior, keep the thermal state machine and rail targets aligned with the site-config thermal section and the NOAH charging/discharge-limit entities.
- When editing Stage 7 feed-forward behavior, keep the typed `devices:` section, `device_models.py`, replay runner, and status/debug output aligned so the live controller and replay baseline exercise the same device set.

## Testing guidance
- Prefer deterministic unit tests with explicit numeric expectations.
- Cover new controller branches with focused tests instead of relying on manual reasoning.
- Keep tests fast and isolated; avoid network, filesystem, or AppDaemon runtime dependencies.
- Follow existing pytest naming style: `test_<behavior>()`.
- Use one test per behavior branch when possible.
- Keep replay metrics deterministic and prefer fixture CSV snippets over large trace copies in the package test suite.

## Documentation expectations
- Keep `README.md` focused on the NOAH 2000 plus EZ1-M AppDaemon project, not one private installation.
- Update `docs/ASSUMPTIONS.md` when topology, safety, or actuator assumptions change.
- Update `docs/CONFIGURATION.md` when config keys or defaults change.
- Update `docs/INSTALL.md` when deployment guidance changes.
- Update examples with vendor-flavored placeholder entity names when helpful, but never with private installation ids or secrets.

## Agent workflow guidance
- Read nearby code before editing; follow the established style in the touched file.
- Prefer `apply_patch` for small manual edits.
- Do not revert unrelated user changes in the worktree.
- Do not add dependencies unless necessary for the task.
- Do not create commits unless explicitly asked.
- Mention any commands you ran and any verification you could not run.

## Good change patterns
- Add a config field in `ControllerConfig`, plumb it from the AppDaemon args parser, document it, and test it.
- Add pure helper functions for reusable math or parsing logic.
- Keep debug/status publishing aligned with new result fields when exposing new controller outputs.
- When a stage changes internal architecture, update `README.md`, `docs/`, and this file so the current module split and validation steps stay accurate.

## Avoid
- Installation-specific entity IDs in committed code or docs.
- Pretending the project is fully generic when defaults clearly target the NOAH 2000 plus EZ1-M style setup.
- Hidden behavior changes in default values.
- Large refactors that mix formatting, renaming, and logic changes.
- Moving business logic from the pure core into Home Assistant glue code.
