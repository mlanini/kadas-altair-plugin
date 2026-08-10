# Release Notes

This file summarizes the main releases of the KADAS Altair plugin. For the full version-by-version history, see [CHANGELOG.md](CHANGELOG.md).

## Current release: v0.5.1

Released 2026-08-09.

### Highlights
- Added support for the swisstopo STAC collection `ch.swisstopo.spezialbefliegungen`.
- Made swisstopo searches collection-aware so a selected collection is queried directly, while unselected searches still span the supported swisstopo collections.
- Fixed Archive Search wiring so the selected swisstopo collection is preserved through the full query path.
- Normalized Smart Tasking archive date ranges to explicit UTC day boundaries so end dates are handled consistently across STAC backends.

### Packaging
- Build command: `KADAS_SKIP_PIP=1 python package_plugin_full.py`
- Output archive: `kadas_altair_plugin_full_v0.5.1.zip`

## Previous releases

### v0.5.0
- Added a mandatory activation disclaimer dialog.
- Improved Smart Tasking CRS handling for geometry layers.
- Tightened Planetary Computer filtering so only valid raster/COG assets are returned.

### v0.4.5
- Added the JAXA Earth STAC connector with public COG-STAC access and no credentials required.
- Added collection browsing and connection checks for the new connector.

### v0.4.4
- Introduced the AOI widget and removed the crash-prone extent-widget workflow from the dock panels.

### v0.4.2
- Introduced Smart Tasking with overpass prediction and 3D orbit visualization.
- Added archive search support for historical scenes and provider-side result inspection.

### v0.4.1
- Improved NASA EarthData authentication support for both token and username/password workflows.

### v0.4.0
- Improved UI behavior, quicklook previews, and COG loading across multiple connectors.
- Added connector architecture improvements for unified search handling and STAC item validation.

## Notes
- The plugin is distributed under the MIT license.
- For installation and usage instructions, see [README.md](README.md) and [GUIDE.md](GUIDE.md).