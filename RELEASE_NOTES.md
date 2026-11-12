# Release Notes

This file summarizes the main releases of the KADAS Altair plugin. For the full version-by-version history, see [CHANGELOG.md](CHANGELOG.md).

## Current release: v0.6.1

Released 2026-11-12

### Highlights
- Added a configurable **Custom STAC** connector with collection discovery, authentication options, and a connection test.
- Added a dedicated **Tasking Results** panel and Send Order prefill from a selected archive or overpass result.
- Improved Quicklook/COG asset selection and connector-specific asset authentication.
- Updated swisstopo to STAC API v1 with swissEO S2-SR v200 as the default collection; saved v100 selections are migrated.
- Fixed swisstopo timestamp handling, added paginated results ordered by acquisition date, and preferred the 10 m true-colour COG.
- Fixed Planetary Computer searches spanning incompatible collection backends.
- Limited Vantor searches to their deadline and avoided repeated TLE requests after proxy failure, while retaining cached orbital data.
- Fixed Settings panel creation when configuring optical sun elevation.
- Corrected nadir swath geometry and MODIS polar swath gaps.
- Removed OneAtlas from archive search because its search implementation is unavailable; OAuth testing remains in Settings.

### Packaging
- Build command: `python package_plugin_full.py` (requires access to the configured Python package index)
- Expected output archive: `kadas_altair_plugin_full_v0.6.1.zip`
- The full v0.6.1 archive has been built and verified; its checksum is recorded in [SHA256SUMS.md](SHA256SUMS.md).

## Previous unpublished release: v0.6.0

Released 2026-11-11

### Highlights
- Added SGP4-based overpass prediction for the center point of an AOI's bounding rectangle, with a 48-hour default window and optional date-range prediction.
- Added persistent TLE caching and offline prediction, with a configurable maximum epoch offset (72 hours by default) and explicit unavailable/partial/no-pass diagnostics instead of synthetic times.
- Added a configurable optical daylight threshold (10 degrees by default) and separate geometric-candidate reporting for SAR sensors with incomplete acquisition constraints.
- Refreshed the main dock visual design with a shared theme across Open Data Search, Archive Search, Settings, and Tasking panels.
- Improved button hierarchy, panel contrast, tables, and status badges for a cleaner KADAS-native workflow.
- Removed direct PyQt5 imports from the active UI path to improve Qt6 compatibility for KADAS 2.3 and beyond.
- Fixed Search and Predict swath geometry for antimeridian-heavy scenes by using MultiPolygon swaths, validating the geometry, and keeping longitude wrapping consistent.
- Restored Landsat-class fallback access by using fractional orbital progress with a stable per-satellite seed, and added Landsat 8 to the satellite catalogue.
- Added a visible hourglass busy indicator in **Search and Predict** while archive search and overpass prediction are running.
- Improved user feedback during mixed **Search + Predict** mode: the indicator stays visible until all active background tasks are complete.
- Reduces ambiguity during multi-second provider requests and overpass computations.
- Makes it explicit that Altair is working and the UI is responsive.

## Previous releases

### v0.5.0
- Added a mandatory activation disclaimer dialog.
- Improved Search and Predict CRS handling for geometry layers.
- Tightened Planetary Computer filtering so only valid raster/COG assets are returned.

### v0.4.5
- Added the JAXA Earth STAC connector with public COG-STAC access and no credentials required.
- Added collection browsing and connection checks for the new connector.

### v0.4.4
- Introduced the AOI widget and removed the crash-prone extent-widget workflow from the dock panels.

### v0.4.2
- Introduced Search and Predict with overpass prediction and 3D orbit visualization.
- Added archive search support for historical scenes and provider-side result inspection.

### v0.4.1
- Improved NASA EarthData authentication support for both token and username/password workflows.

### v0.4.0
- Improved UI behavior, quicklook previews, and COG loading across multiple connectors.
- Added connector architecture improvements for unified search handling and STAC item validation.

## Notes
- The plugin is distributed under the MIT license.
- For installation and usage instructions, see [README.md](README.md) and [GUIDE.md](GUIDE.md).