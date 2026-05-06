# Changelog

All notable changes to KADAS Altair Plugin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.3] - 2026-05-06

### Added
- **Jilin-1 Gaofen STAC connector** (`jilin_gaofen_stac.py`) — connector file for CGSTL's Jilin-1 high-resolution optical constellation (commercial, 0.72 m GSD):
  - Bearer-token authentication via QSettings (`altair/jilin_access_token`) or credentials dict
  - STAC POST `/search` with bbox + date + cloud cover + collection filters; GET fallback for collections without POST search
  - Available in Archive and Smart Tasking docks
- **Jilin-1 entry in satellite catalogue** (Smart Tasking dock): NORAD 52836, 0.72 m GSD, off-nadir model, max 30°, 1-day revisit

### Removed
- **Jilin-1 Gaofen removed from Open Data dock** — Jilin-1 is a commercial service (Chang Guang Satellite Technology, CGSTL); requires a private endpoint and bearer token per tenant. The connector file is retained for Archive/Smart Tasking use but is no longer registered in the Open Data panel.

### Fixed
- **KADAS AOI crash** — removed `QgsExtentWidget.setMapCanvas()` call in `smart_tasking_dock.py` and `tasking_dock.py`.
  KADAS uses `KadasMapCanvas` which is incompatible with `QgsMapToolExtent` (the draw-on-canvas tool installed by `setMapCanvas()`), causing a hard segfault when the user clicked the draw button. The widget retains full manual-coordinate and "use current extent" functionality.

### Changed
- **Satellite catalogue** expanded from 21 to 22 entries
- **Open Data connector count**: 6 production-ready connectors (unchanged from 0.4.2)
- **metadata.txt**: version bumped to 0.4.3

## [0.4.2] - 2026-04-01

### Added
- **Smart Tasking dock** — satellite overpass prediction and 3D orbit visualisation:
  - **Bearing-convergence engine**: iterative bisection detects when a satellite’s sensor footprint crosses the target AOI (replaces elevation-based scanning)
  - **Sensor models**: `pushbroom` (swath-only) and `off_nadir` (swath + max scan angle) with per-satellite parameters in a 21-entry catalogue
  - **SGP4 orbital propagation** via `sgp4` library with analytical sun-synchronous fallback
  - **5-layer 3D visualisation** (QGIS native `qgis._3d` renderers):
    - Orbit track — LineStringZ at orbital altitude (white)
    - Ground track — LineString on surface (cyan)
    - Swath corridor — Polygon ribbon (cyan, semi-transparent)
    - Satellite position — PointZ at altitude (red sphere)
    - Nadir axis — LineStringZ surface→satellite (red tube)
  - **Archive search** tab with multi-connector parallel search (reuses connector framework)
  - Antimeridian and pole-guard clamping for all generated geometries
  - `blockSignals` guards to prevent spurious `itemSelectionChanged` during table repopulation

### Changed
- **Satellite catalogue** enriched with `sensor_model` and `max_off_nadir_deg` fields for all 21 entries
- **metadata.txt**: Updated version to 0.4.2, description updated with Smart Tasking capabilities

### Documentation
- Added inspiring projects to Credits: [eo-predictor](https://github.com/developmentseed/eo-predictor), [sat-predict](https://sat-predict.davidhsu.cc/)
- Updated ARCHITECTURE.md with Smart Tasking dock in architecture diagram and project structure
- Updated README.md with Smart Tasking feature and version badge

## [0.4.1] - 2026-03-31

### Changed
- **NASA EarthData connector** now supports both authentication modes documented by Earthdata Login/earthaccess:
  - `username` + `password`
  - `access_token` / `EARTHDATA_TOKEN` (Bearer)
- Added credentials loading precedence in connector: explicit input → secure storage → environment (`EARTHDATA_TOKEN`, `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD`) → `.netrc` via earthaccess.
- Added reusable authenticated session/header helpers in NASA connector for downstream streaming/download use.
- Improved NASA granule asset mapping:
  - Adds explicit `visual` raster asset when TIFF/COG links are present
  - Prefers raster links in `get_download_url()`.

### Fixed
- **Secure storage** now returns credentials for service `nasa_earthdata` (username/password/access_token), enabling proper reload from settings.
- **Settings dock** NASA tab now supports token input and token-aware test flow (token OR user/pass).
- **Main dock initialization** now reads NASA token from secure storage/settings and passes it to connector registration.

### Documentation
- Updated NASA guidance text in Settings and GUIDE with explicit token workflow.

## [0.4.0] - 2026-03-29

### Changed
- **UI compactness**: Open Data, Archive, Tasking and Settings docks are now wrapped in a scrollable container, top-aligned, and use tighter spacing/margins to better fit KADAS window height.
- **`QgsExtentWidget` AOI** in both Archive Search and Tasking docks — bidirectional sync with map canvas; replaces manual coordinate spin boxes
- **Archive Search dock** (`archive_dock.py`):
  - `FootprintSelectionTool` — click a footprint on the map canvas to select it; selection reflected bidirectionally in the results table
  - `QgsRuleBasedRenderer` for footprint layer: selected items highlighted with semi-transparent yellow fill (`rgba(255,220,0,120)`) and `#ffcc00` border
  - Quicklook preview panel: `QNetworkRequest` import fix (was missing, causing silent download failures)
  - Quicklook CRS fix: `layer.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))` applied after loading worldfile-backed quicklook raster to ensure correct reprojection to map CRS
  - `_pick_cog_href(assets)` — 3-level COG asset auto-detection: (1) priority key list `['visual','TCI','TCI_10m','B_TCI','B04_10m','B04','B03_10m','B03','data','analytic','cog','image']`, (2) media-type matching, (3) file extension fallback; skips `.SAFE` product folders
  - `_gdal_set_bearer(token)` / `_gdal_clear_bearer()` — inject/clear `GDAL_HTTP_HEADERS` for authenticated `/vsicurl/` access to Copernicus `eodata.dataspace.copernicus.eu`
  - `_get_bearer_for_item(item)` — resolves `_access_token` from the connector instance bound to a result item
- **Tasking dock** (`tasking_dock.py`):
  - `addStretch(1)` between every top-level group for even vertical distribution
  - AOI now uses `QgsExtentWidget` instead of separate spin boxes
  - `_get_aoi_bbox_wgs84()` helper returns the WGS84 bounding box from the widget; used in email body generation
- `plugin.py` — `_open_tasking_from_archive()` updated to set `extent_widget` (via `setCurrentExtent` / `setOriginalExtent`) instead of the removed `bbox_min_lon/lat` spin boxes
- **Connector Architecture (R1)**: Introduced `search_unified()` standardized entrypoint in `ConnectorBase`
  - All connectors share a single normalized call signature: `(bbox, start_date, end_date, max_cloud_cover, collection, text_query, limit)`
  - Connectors with non-standard `search()` signatures (IceyeStacConnector, UmbraSTACConnector, CapellaSTACConnector, CopernicusStacConnector, PlanetConnector) override `search_unified()` to translate parameters
  - `ConnectorManager._execute_connector_search()` simplified from ~130 lines of fragile class-name dispatch to 15 lines calling `instance.search_unified()`
- **Open-Data Auth Fix (R2)**: `ConnectorManager.get_collections()` no longer gates open-data connectors (Capella, Umbra, ICEYE, Vantor) behind an authentication check
- **STAC Item Validation (R3)**: Added `ConnectorManager._validate_stac_item()` — lightweight pre-result validation ensuring `type=="Feature"`, non-empty `id`, `properties` dict, `assets` dict
- **Vantor connector** (`vantor.py`):
  - `search()` rewritten — iterates events from cache first, then up to `MAX_EVENTS_TO_FETCH=10` via network; removed `if not collection: return []` early-exit
  - `_extract_assets(props, feature=None)` — optional `feature` param resolves from top-level `assets` dict when `href` not found in `properties` (newer Maxar GeoJSON schema)
- **metadata.txt**: Updated version to 0.4.0, updated description and tags

### Fixed
- COG loading for Copernicus STAC: Bearer token now injected via `GDAL_HTTP_HEADERS` before `/vsicurl/` open; cleared in `finally` block
- Vantor multi-event broad search: returns results even when no specific collection is selected
- Quicklook download failure: `QNetworkRequest` was silently causing `NameError` inside a broad `except Exception` block
- Quicklook displayed at wrong map position for non-WGS84 map CRS

## [0.3.2] - 2026-03-27

### Removed
- **Copernicus HDA (WEkEO) Connector** - Removed due to API incompatibility
  - Bearer token authentication not supported by hda library
  - WMS/WMTS layer browser functionality removed
  - HDA username/password authentication removed
  - hda>=0.3.0 library dependency removed

### Changed
- **Connector Count**: Reduced from 12 to 11 (single Copernicus STAC only)
- **Settings UI**: Simplified to single Copernicus STAC section
- **Package Size**: Reduced without hda library
- **Documentation**: Updated all HDA references to STAC-only

## [0.3.1] - 2026-03-03

### Added
- **Copernicus HDA (WEkEO) Connector** - Access to 9000+ WEkEO datasets via Harmonized Data Access API
  - Username/password authentication with 3-level fallback (explicit → secure_storage → ~/.hdarc)
  - Dynamic query parameter mapping for dataset-specific searches
  - Full download functionality via HDA client
  - Support for bbox and temporal range filters
- **WMS/WMTS Layer Browser** - Instant data visualization without downloading
  - New "WMS/WMTS Layers" tab in Results section
  - owslib integration for parsing GetCapabilities
  - Support for both WMS and WMTS protocols
  - Multi-select layer addition to map
  - Double-click quick-add functionality
- **Dual Copernicus Authentication** - Separate authentication for different Copernicus services
  - OAuth2 client credentials for STAC (Dataspace)
  - Username/password for HDA (WEkEO)
  - Independent secure storage services ('copernicus' and 'copernicus_hda')
  - Separate timeout configurations (15s STAC, 45s HDA)
- **Enhanced Settings UI**
  - Split Copernicus configuration into STAC and HDA sections
  - Individual "Test Connection" buttons for each service
  - Dedicated "Restore Defaults" buttons
  - Clear visual separation and service-specific documentation

### Changed
- **Connector Architecture**: Renamed `CopernicusConnector` to `CopernicusStacConnector` for clarity
- **ConnectorManager**: Extended to support HDA connector signature and routing
- **Package Size**: Increased to 5.78 MB (was ~3 MB) to bundle new dependencies
- **Dataset Count**: Expanded from 300+ to 9000+ accessible datasets
- **Connector Count**: Increased from 5 to 6 production-ready connectors
- **metadata.txt**: Updated descriptions to reflect new capabilities

### Dependencies
- Added `hda>=0.3.0` - Python client for WEkEO Harmonized Data Access API (Apache 2.0 license)
- Added `owslib>=0.31.0` - OGC Web Services parsing library for WMS/WMTS (BSD license)

### Fixed
- Improved error handling in HDA authentication with user-friendly messages
- Better credential fallback mechanism with ~/.hdarc file support
- Enhanced logging for WMS/WMTS capabilities parsing

### Technical Details
- New `CopernicusHdaConnector` class (680 lines)
- New UI components: QTabWidget, QTreeWidget for layer browser
- owslib integration for GetCapabilities parsing (WMS 1.3.0, WMTS)
- Dynamic query building based on dataset queryable parameters
- Standardized layer information format (name, title, type, url, bbox, crs)

## [0.2.0] - 2026-02-25

### Added
- **Performance Optimization**: Parallel collection loading with ThreadPoolExecutor (5 concurrent workers)
- **Caching System**: 5-minute TTL cache for collections with automatic invalidation on authentication
- **Enhanced ICEYE Logging**: Detailed bbox filtering diagnostics with INFO-level logging
- **Documentation Consolidation**: Streamlined to 4 essential documents (README, GUIDE, ARCHITECTURE, CONTRIBUTING)
- **KADAS Branding**: Consistent KADAS Albireo 2.3+ references throughout all documentation

### Changed
- Collection loading speed improved **5x** (30s → 6s) with parallel execution
- Cached collection loading improved **300x** (30s → 0.1s) with TTL cache
- Cache automatically invalidates after authentication flow
- ICEYE connector now logs "✅ INCLUDING" or "❌ EXCLUDING" with bbox coordinates
- Updated installation paths to KADAS-specific locations (Kadas/Kadas/profiles/default/)
- Documentation structure: Consolidated TECHNICAL.md and PERFORMANCE_IMPROVEMENTS.md into ARCHITECTURE.md

### Fixed
- ICEYE bbox filtering now properly validated and logged
- Collection cache properly cleared after connector authentication

### Documentation
- **ARCHITECTURE.md**: New comprehensive technical reference (consolidates previous technical docs)
- **README.md**: Updated with KADAS branding and 4-document structure
- **GUIDE.md**: Updated with KADAS-specific paths, settings, and requirements
- **CONTRIBUTING.md**: Enhanced with testing guidelines

### Technical Details
- Python 3.12+ support
- KADAS Albireo 2.3+ compatibility (based on QGIS 3.x platform)
- Connector Framework with 9 connectors (5 production-ready)
- Qt-based networking via QgsNetworkAccessManager
- Bundled pystac-client dependency (1.59 MB package)

## [0.1.0] - Initial Release

### Added
- Multi-source satellite imagery browser for KADAS Albireo 2
- 5 production-ready connectors:
  - **ICEYE SAR Open Data**: 3 collections, 196 SAR imagery items, global coverage
  - **Umbra SAR Open Data**: High-resolution SAR up to 16cm, recursive STAC catalog
  - **Capella SAR Open Data**: ~1000 SAR images, X-band radar, multiple product formats
  - **Maxar Open Data (Vantor STAC)**: 55+ disaster event collections, sub-meter optical
  - **Copernicus Dataspace**: Sentinel-1/2/3/5P via OAuth2 and STAC API
- 3 additional experimental connectors: Planet, NASA EarthData, OneAtlas
- Interactive map-based footprint selection with bidirectional table sync
- Cloud-Optimized GeoTIFF (COG) loading via GDAL vsicurl
- Advanced search filters: bbox, date range, cloud cover
- OAuth2 client credentials flow support
- Comprehensive logging system with log viewer
- QgsNetworkAccessManager for SSL/proxy handling
- Native QGIS network integration
- 300+ collections across all connectors

### Features
- Unified connector interface via ConnectorManager middleware
- Advanced search with multiple filter types
- Footprint visualization on map canvas
- Load imagery directly from URL (COG support)
- Settings dialog for connector configuration
- Log viewer with filtering capabilities
- Secure credential storage
- Proxy and VPN support via Qt networking stack

---

## Version History Legend

- **Added**: New features
- **Changed**: Changes in existing functionality
- **Deprecated**: Soon-to-be removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Vulnerability fixes
- **Documentation**: Documentation updates
- **Technical Details**: Internal/technical changes

---

## Links

- [GitHub Repository](https://github.com/mlanini/kadas-altair)
- [Issue Tracker](https://github.com/mlanini/kadas-altair/issues)
- [Installation Guide](GUIDE.md)
- [Architecture Documentation](ARCHITECTURE.md)
- [Contributing Guidelines](CONTRIBUTING.md)
