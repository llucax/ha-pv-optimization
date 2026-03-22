# Assumptions and Current Limitations

`ha-pv-optimization` is deliberately generic within a narrow control model.

It is not a universal EMS.

## Control model assumptions

- one live actuator at a time
- a numeric, non-negative power limit
- one main household-consumption signal in watts
- optionally one net import/export correction signal in watts
- optionally battery SoC and reserve-floor inputs in percent
- coarse control cadence measured in tens of seconds

## Topology assumptions

The controller works best when the chosen actuator has a predictable effect on the same electrical boundary measured by your Home Assistant sensors.

Good fit:

- behind-the-meter self-consumption control
- a single inverter output limit
- a single battery output limit
- topologies where increasing the configured limit increases house-serving power

Possible with caveats:

- aggregate devices that hide internal dispatch details
- installations with imperfect measurement coverage
- systems without battery reserve inputs, if native device protections already exist

Poor fit:

- multi-actuator coordination
- signed charge/discharge setpoints
- mode-only control surfaces
- per-phase balancing
- fast export-limiting requirements or sub-second feedback loops

## Battery and actuator capability assumptions

If you enable battery protection inputs, the controller assumes:

- SoC is reported in percent
- the reserve floor is reported in percent
- output should stop or derate near that floor

If your device exposes different semantics, configure the app carefully or leave those inputs unset.

## Current transparency note

This project was developed and used first on:

- a Growatt NOAH 2000 battery
- an APsystems EZ1-M inverter

That matters because several default tuning choices reflect a conservative, coarse-control style that worked on that real installation.

The project is public and genericized, but it remains intentionally opinionated rather than pretending to support every inverter, battery, or topology equally well.
