# s1ard
[![Documentation Status][1]][2] [![PyPI version][4]][5]

**A prototype processor for Sentinel-1 Analysis Ready Data (ARD) backscatter products.**

Please refer to the [documentation][3] for more details about installation and
usage instructions, general processor information and the API reference.

Further information about the S1-NRB product can also be found
[here][6].

## Fork Notes

- Docker build supports `UPDATE_SNAP` to enable or skip SNAP module updates at build time.
  Example: `docker build --build-arg UPDATE_SNAP=false -t s1ard-snap:no-update .`
- When `UPDATE_SNAP=true`, the update step targets only the Microwave Toolbox module (`eu.esa.microwavetbx.microwavetbx.kit`) as configured in the container definition/build files.
- Added an Apptainer definition file for HPC/container workflows: [apptainer/s1ard-snap.def](apptainer/s1ard-snap.def).
- Known behavior: after updating SNAP Microwave Toolbox from `13.0.0` to `13.0.3`, SNAP may produce empty SAR outputs.
- Known behavior: SNAP border-noise removal can fail during metadata parsing in `RemoveGRDBorderNoiseOp`. This issue is addressed by reordering SNAP pre-processing to run `ThermalNoiseRemoval` before `Remove-GRD-Border-Noise`.
  Reference: [RemoveGRDBorderNoiseOp.java (line 223)](https://github.com/senbox-org/microwave-toolbox/blob/3877ef0b9f1deaebf029f1ea7eac6c8094cb94ab/sar-op-calibration/src/main/java/eu/esa/sar/calibration/gpf/RemoveGRDBorderNoiseOp.java#L223)
- Recommended custom-grid execution strategy:
  - Run `mode=sar` once over the full AOI/custom-grid union (scene-level SAR processing).
  - Run `mode=nrb` with per-tile parallelization (e.g., SLURM arrays with `--aoi_tiles`).
  - Avoid splitting SAR stage by adjacent tiles, because SAR outputs are scene/EPSG keyed and can be reused across overlapping tile-driven runs.
- If a job is interrupted, `reset_locks_on_start=True` can remove stale pyroSAR/SNAP lock sidecars at the start of each scene. Keep it disabled when multiple jobs may write the same scene-level SAR targets concurrently.

## Fork Changelog

### New Features
- Added custom tiling grid support via `custom_tile_grid` and `custom_tile_id_field`, including support for non-MGRS tile IDs in `aoi_tiles`.
  Files: [s1ard/config.py](s1ard/config.py), [s1ard/resources/config.ini](s1ard/resources/config.ini), [s1ard/processor.py](s1ard/processor.py), [s1ard/custom_grid.py](s1ard/custom_grid.py)
- Implemented direct SAR geocoding in custom grid CRS (single target CRS + per-scene clipped extent) when `custom_tile_grid` is provided.
  Files: [s1ard/processor.py](s1ard/processor.py), [s1ard/processors/snap.py](s1ard/processors/snap.py), [s1ard/snap.py](s1ard/snap.py)
- Added explicit custom DEM mode via `dem_type=custom_dem` with scene-wise DEM preparation (crop/reproject/resample to SNAP-ready EPSG:4326), following the logic of `cesard.dem.prepare`.
  Config validation ignores `custom_dem_*` parameters when `dem_type != custom_dem`. Custom geoid conversion is controlled by `custom_dem_apply_geoid`; when enabled, the geoid model is read from `custom_dem_geoid_isg` (URL or local file path) via GDAL ISG support (when disabled, geoid input is ignored). The value is expected to end with `.isg` (warning if not).
  Files: [s1ard/config.py](s1ard/config.py), [s1ard/resources/config.ini](s1ard/resources/config.ini), [s1ard/processor.py](s1ard/processor.py), [s1ard/custom_dem.py](s1ard/custom_dem.py), [s1ard/ard.py](s1ard/ard.py)
- Added `geoid_block_size` to process custom DEM geoid correction in chunks and avoid high memory use on large DEMs.
  Files: [s1ard/config.py](s1ard/config.py), [s1ard/resources/config.ini](s1ard/resources/config.ini), [s1ard/custom_dem.py](s1ard/custom_dem.py)
- Added polarization selection (`polarizations`) configurable from the configuration file and propagated through SAR + ARD processing.
  Files: [s1ard/config.py](s1ard/config.py), [s1ard/resources/config.ini](s1ard/resources/config.ini), [s1ard/processor.py](s1ard/processor.py), [s1ard/snap.py](s1ard/snap.py), [s1ard/ard.py](s1ard/ard.py)
- Added ARD product metadata/STAC handling for custom tile IDs, including temporary pseudo-MGRS mapping for STAC writer compatibility while preserving original custom tile ID.
  Files: [s1ard/ard.py](s1ard/ard.py), [s1ard/metadata/extract.py](s1ard/metadata/extract.py), [s1ard/metadata/stac.py](s1ard/metadata/stac.py), [s1ard/metadata/mapping.py](s1ard/metadata/mapping.py)
- Added end-of-group ARD completion log with created/skipped product counters and elapsed time.
  File: [s1ard/processor.py](s1ard/processor.py)

### Compatibility Fixes
- Added pyroSAR COG_SAFE compatibility patching for `_COG.SAFE(.zip)` scene naming and `-cog.xml` annotations.
  Files: [s1ard/pyrosar_compat.py](s1ard/pyrosar_compat.py), [s1ard/processor.py](s1ard/processor.py)
  Reference: [pyroSAR issue #291 (implementation suggestion)](https://github.com/johntruckenbrodt/pyroSAR/issues/291#issuecomment-2903834217)
- Updated ARD/STAC product name pattern to allow custom tile ID tokens (not only 5-char MGRS IDs).
  Files: [s1ard/metadata/mapping.py](s1ard/metadata/mapping.py), [s1ard/metadata/stac.py](s1ard/metadata/stac.py)
- Updated SNAP preprocessing node order to `Apply-Orbit-File -> ThermalNoiseRemoval -> Remove-GRD-Border-Noise -> Calibration`, resolving border-noise compatibility issues with COG_SAFE scenes.
  File: [s1ard/snap.py](s1ard/snap.py)

### Bug Corrections
- Added safe DB insertion wrapper to handle `UNIQUE constraint failed: data.product, data.outname_base` collisions by chunk retry + duplicate skip, instead of hard fail.
  Files: [s1ard/archive_utils.py](s1ard/archive_utils.py), [s1ard/processor.py](s1ard/processor.py)
- Made SAR "already processed" checks robust by validating expected EPSG outputs, not only output folder presence.
  Files: [s1ard/sar_state.py](s1ard/sar_state.py), [s1ard/processor.py](s1ard/processor.py)
- Fixed DEM annotation (`em`) behavior for custom/non-MGRS tiles by using `gdalwarp` for custom DEM and skipping unsupported MGRS-only extraction path with explicit warning.
  File: [s1ard/ard.py](s1ard/ard.py)
- Made SNAP cleanup robust against concurrent file removal by ignoring missing temp paths during deletion.
  File: [s1ard/snap.py](s1ard/snap.py)
- Added optional startup cleanup of stale pyroSAR/SNAP lock sidecars (`reset_locks_on_start`) for interrupted-job recovery.
  File: [s1ard/snap.py](s1ard/snap.py)
- Added atomic custom geoid downloads, unreadable-cache refresh, and clearer GDAL ISG diagnostics for `custom_dem_geoid_isg`.
  File: [s1ard/custom_dem.py](s1ard/custom_dem.py)

### Container / Build Updates
- Standardized SNAP installation path to `/opt/esa-snap` and aligned installer varfile accordingly.
  Files: [Dockerfile](Dockerfile), [docker/esa-snap.varfile](docker/esa-snap.varfile)
- Added headless/font dependencies for SNAP runtime stability in container builds.
  File: [Dockerfile](Dockerfile)
- Switched SNAP update step to controlled module update flow with timeout and explicit exit-code handling (including expected `143` termination).
  File: [Dockerfile](Dockerfile)
- Forced Ubuntu APT mirrors to HTTPS in container builds (`Dockerfile` + Apptainer definitions) before `apt update`.
  Files: [Dockerfile](Dockerfile), [apptainer/s1ard-snap.def](apptainer/s1ard-snap.def), [apptainer/s1ard-base.def](apptainer/s1ard-base.def)

### Tests
- Added/updated config tests for:
  - default `polarizations=None`
  - custom DEM mode (`dem_type=custom_dem`)
  - `custom_dem_apply_geoid` gating behavior
  - geoid input from `custom_dem_geoid_isg` (URL or local path)
  - non-MGRS `aoi_tiles` acceptance with custom grids
  File: [tests/test_config.py](tests/test_config.py)

[1]: https://readthedocs.org/projects/s1ard/badge/?version=latest
[2]: https://s1ard.readthedocs.io/en/latest/?badge=latest
[3]: https://s1ard.readthedocs.io/en/latest/
[4]: https://badge.fury.io/py/s1ard.svg
[5]: https://badge.fury.io/py/s1ard
[6]: https://sentiwiki.copernicus.eu/web/s1-products#S1Products-Sentinel-1ARDNormalisedRadarBackscatter(NRB)ProductS1-Products-Sentinel-1-ARD-Normalised-Radar-Backscatter
