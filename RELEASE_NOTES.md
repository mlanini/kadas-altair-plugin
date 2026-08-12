# Release Notes

This file summarizes the main releases of the KADAS Altair plugin. For the full version-by-version history, see [CHANGELOG.md](CHANGELOG.md).

## Current release: v0.5.2

Released 2026-08-12

### Highlights
- Fixed Search and Predict swath geometry for antimeridian-heavy scenes by using MultiPolygon swaths, validating the geometry, and keeping longitude wrapping consistent.
- Restored Landsat-class fallback access by using fractional orbital progress with a stable per-satellite seed, and added Landsat 8 to the satellite catalogue.
- Added a visible hourglass busy indicator in **Search and Predict** while archive search and overpass prediction are running.
- Improved user feedback during mixed **Search + Predict** mode: the indicator stays visible until all active background tasks are complete.
- Reduces ambiguity during multi-second provider requests and overpass computations.
- Makes it explicit that Altair is working and the UI is responsive.

### Packaging
- Build command: `KADAS_SKIP_PIP=1 python package_plugin_full.py`
- Output archive: `kadas_altair_plugin_full_v0.5.2.zip`

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