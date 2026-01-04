# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.2] - 2026-01-04

### Fixed

- Github action script

## [0.5.0] - 2025-12-09

### Added
- Bidirectional synchronization with checksum-based change detection for external S7 client writes
- Copy-on-read architecture with isolated snap7 buffers for improved performance
- Thread-safe data access using RLock to prevent data corruption
- GUI auto-refresh toggle checkbox (disabled by default for optimal performance)
- Manual refresh button for on-demand GUI updates
- Configurable sync interval for snap7 buffer synchronization

### Changed
- GUI polling disabled by default to eliminate lock contention with external clients
- GUI polling interval increased from 500ms to 2000ms when enabled
- Snap7 sync interval optimized to 50ms (configurable via `set_sync_interval()`)
- Improved external client responsiveness by eliminating timeout issues

### Fixed
- External S7 client write operations now properly reflected in GUI
- Timeout issues caused by GUI polling contention resolved
- Data consistency guaranteed through proper thread locking

## [0.4.0] - 2025-12-09

### Feat
- Scripting engine

## [0.3.0] - 2025-08-23

### Fix
- Installer spec file

## [0.1.0] - 2025-07-31

### Added
- Initial release of PLC DB Simulator.
