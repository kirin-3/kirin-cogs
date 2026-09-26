# Changelog

## [1.0.12] - 2026-02-27 onward (kirin-cogs)

The cog was imported into this repo at 1.0.12; the upstream entries for 1.0.2–1.0.11 were not carried over. Changes
made here since the import:

### Added

- Contest number persists across restarts, and dashboards are rebound on load.
- `cotmreward` pays through Unicornia with one idempotency key per contest and winner, saves each contest's places
  before paying, and reruns pay only those saved places. An optional contest number argument.
- Red data-deletion requests remove the user from saved results.

### Changed

- `[p]cotm` posts in the channel the command was used in.
- Standings hide invalid votes by default, and each author is ranked once by their best entry.
- Payout text uses the server's custom currency emoji.

### Removed

- Duplicate `contestcount` command.
- Unused `CONTEST_CHANNEL_IDS` and the server IDs only it used.

## [1.0.1] - 2025-1-27

### Added

- "cotm" command alias

### Changed

- Moved logger level into const
- Added docstrings to all methods

### Fixed

- Channel & role mentions in description texts.
- Custom server emoji in description texts.

## [1.0.0] - 2025-1-27

### Added

- Created initial project setup.
- Implemented basic functionality for posting Cutie of the Month Contest information.
