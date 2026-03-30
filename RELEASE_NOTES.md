# Release Notes - KADAS Altair Plugin v0.4.0

## 🚀 UI, COG Loading & Connector Improvements

v0.4.0 delivers a significant round of UI enhancements, bug fixes and connector reliability improvements focused on four areas: interactive map-based search, COG (Cloud-Optimized GeoTIFF) multi-provider loading, Copernicus authenticated raster access, and Vantor (Maxar Open Data) broad searches.

---

## ✨ Highlights

### 🗺️ Interactive Footprint Selection
- Click any footprint on the map canvas to select it — bidirectional sync with the results table
- Selected items rendered with a semi-transparent **yellow fill** (`rgba(255,220,0,120)`) and golden border via `QgsRuleBasedRenderer`, visually distinct from the blue unselected style
- `FootprintSelectionTool` integrates with KADAS map canvas event handling

### 📐 `QgsExtentWidget` AOI
- Both Archive Search and Tasking docks now use QGIS native `QgsExtentWidget` for the area-of-interest input
- Syncs automatically with the map canvas extent
- Supports manual coordinate editing, draw-on-canvas, and extent from layer

### 🛰️ Multi-Provider COG Loading
- New `_pick_cog_href()` method with 3-level asset fallback:
  1. Priority key list covering Sentinel-2, Landsat, ICEYE, Umbra, Capella naming schemes
  2. MIME type matching (`image/tiff`, `image/geotiff`, `image/jp2`, ...)
  3. File extension fallback (`.tif`, `.jp2`) — skips `.SAFE` product folders
- Copernicus COG urls are now properly opened with **Bearer token injection** via `GDAL_HTTP_HEADERS`, enabling authenticated `/vsicurl/` access to `eodata.dataspace.copernicus.eu`

### 🔍 Vantor Broad Search
- `search()` now iterates all available disaster events (cached first, then up to 10 via network)
- Removed the `if not collection: return []` early-exit that blocked all results when no specific event was selected
- Updated `_extract_assets()` to resolve `href` from both `properties` and feature-level `assets` dict (newer Maxar GeoJSON schema)

### 🖼️ Quicklook Preview Fixes
- **Import fix**: `QNetworkRequest` was missing, causing silent download failures inside a broad `except` block
- **CRS fix**: Quicklook rasters are now explicitly assigned `EPSG:4326` after loading, preventing mis-projection when the map canvas uses a non-WGS84 CRS

---

## 🔧 Architecture Improvements

### Connector Standardization (R1)
- New `ConnectorBase.search_unified()` entrypoint — uniform interface across all connectors
- `ConnectorManager._execute_connector_search()` reduced from ~130 lines of fragile class-name dispatch to 15 lines
- Connectors with non-standard signatures override `search_unified()` rather than requiring dispatcher changes

### Open-Data Auth Gate Fix (R2)
- `ConnectorManager.get_collections()` no longer blocks open-data connectors (Capella, Umbra, ICEYE, Vantor) when unauthenticated
- Only connectors declaring `ConnectorCapability.AUTHENTICATION` are gated

### STAC Item Validation (R3)
- `ConnectorManager._validate_stac_item()` runs before every item enters the result set
- Checks minimum STAC requirements: `type="Feature"`, non-empty `id`, `properties` dict, `assets` dict
- Invalid items logged at WARNING level and silently excluded

---

## 🐛 Bug Fixes

| Area | Issue | Fix |
|------|-------|-----|
| Quicklook | Silent `NameError` on `QNetworkRequest` | Added missing `from qgis.PyQt.QtNetwork import QNetworkRequest` |
| Quicklook | Wrong map position for non-WGS84 canvas | `layer.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))` after load |
| COG (Copernicus) | `KeyError` on asset lookup | `_pick_cog_href()` multi-level fallback |
| COG (Copernicus) | HTTP 401 on `eodata` domain | GDAL Bearer injection in try/finally |
| Vantor search | Zero results when no collection selected | `search()` rewritten to iterate events |
| Tasking dock | Archive result bbox not applied to AOI | `_open_tasking_from_archive()` updated for `extent_widget` |

---

## 📦 Package Details

| Package | Size | Contents |
|---------|------|----------|
| `kadas_altair_plugin_full_v0.4.0.zip` | ~150 KB | Plugin + bundled dependencies |
| `kadas_altair_plugin_lite_v0.4.0.zip` | ~200 KB | Plugin code only |

---

## 🔗 Resources

- **Copernicus Dataspace**: https://dataspace.copernicus.eu/
- **Maxar Open Data**: https://github.com/opengeos/maxar-open-data
- **Repository**: https://github.com/mlanini/kadas-altair-plugin

---

# Release Notes - KADAS Altair Plugin v0.3.2

## 🔧 Architecture Cleanup - Copernicus STAC Only

This release removes the Copernicus HDA (WEkEO) connector due to API incompatibility issues and focuses on the more reliable Copernicus STAC (Dataspace) connector with OAuth2 authentication.

---

## ✨ Key Changes

### 🗑️ **Removed Copernicus HDA Connector**
- Removed WEkEO HDA integration (API incompatible with Bearer token authentication)
- Removed WMS/WMTS layer browser functionality
- Removed hda library dependency
- Simplified authentication to OAuth2 only

### 🌍 **Copernicus STAC (Dataspace) as Sole Copernicus Connector**
- OAuth2 client credentials authentication
- Secure credential storage with keyring/encryption fallback
- Access to Sentinel constellation datasets
- Standard STAC API implementation

### 🔐 **Simplified Authentication**
Single authentication method for Copernicus:
- **STAC (Dataspace)**: OAuth2 client_id/client_secret
- No username/password fallback needed

---

## 📊 Updated Metrics

### Connector Count
- **Total connectors**: 11 (reduced from 12)
- **Copernicus**: Single STAC connector only
- **Other connectors**: ICEYE, Maxar, Umbra, Capella, and stubs unchanged

### Package Details
- **Lite package**: ~200 KB (plugin code only)
- **Full package**: ~5.78 MB (reduced without hda library)
- **Bundled dependencies**: pystac-client, owslib (for general OGC support)

---

## 🛠️ Technical Details

### Removed Components
- `copernicus_hda.py` connector
- HDA-specific UI elements in settings_dock.py
- HDA search logic in connector_manager.py
- WMS/WMTS refresh functionality in dock.py
- hda>=0.3.0 library dependency

### Updated Components
- **settings_dock.py**: Simplified to single Copernicus STAC section
- **connector_manager.py**: Removed HDA search routing
- **dock.py**: Removed HDA loading and WMS refresh functions
- **Documentation**: All references updated from HDA to STAC-only

---

## 📝 Migration Notes

If you were using Copernicus HDA (WEkEO) in v0.3.1:
1. Switch to **Copernicus STAC (Dataspace)** connector
2. Register for free at https://dataspace.copernicus.eu/
3. Generate OAuth2 client credentials
4. Enter client_id and client_secret in Settings → Copernicus STAC section
5. Access Sentinel constellation datasets via STAC API

---

## 🔗 Resources

- **Copernicus Dataspace**: https://dataspace.copernicus.eu/
- **API Documentation**: https://documentation.dataspace.copernicus.eu/
- **Repository**: https://github.com/mlanini/kadas-altair

---

# Release Notes - KADAS Altair Plugin v0.3.1 (Previous)

## 🌍 WEkEO Integration & WMS/WMTS Layer Browser

This release added the Copernicus HDA (WEkEO) connector providing access to 9000+ datasets and introduced a WMS/WMTS layer browser.

**Note**: This connector was removed in v0.3.2 due to API compatibility issues.

---

## ✨ Highlights

### 🌍 **9000+ Datasets (DEPRECATED)**
Access to WEkEO catalog through HDA connector including:
- Copernicus Marine Service datasets
- Copernicus Climate Change Service (C3S)
- Copernicus Atmosphere Monitoring Service (CAMS)
- EUMETSAT meteorological data

### 🗺️ **WMS/WMTS Layer Browser (REMOVED)**
Instant dataset preview via OGC Web Services:
- Browse available layers per dataset
- Double-click to add to map
- Multi-select support

### 🔐 **Dual Copernicus Authentication (SIMPLIFIED)**
Separate authentication modes:
- **STAC (Dataspace)**: OAuth2 client credentials
- **HDA (WEkEO)**: Username/password (removed in v0.3.2)

---

## 🆕 Features (Historical - v0.3.1)

### Copernicus HDA (WEkEO) Connector (REMOVED)
- **9000+ datasets** from WEkEO HDA API
- **Username/password authentication** with 3-level fallback
- **Dynamic query parameter mapping**
- **Full download support**
- **Bbox and temporal filters**

### WMS/WMTS Layer Browser (REMOVED)
- **Dedicated tab** - "WMS/WMTS Layers"
- **owslib integration** - GetCapabilities parsing
- **Protocol support** - WMS 1.3.0 and WMTS
- **Layer metadata display**
- **Quick actions**:
  - Double-click layer to add to map
  - Multi-select + "Add to Map" button
  - Refresh layers button for selected dataset

### Enhanced Settings UI
- **Split Copernicus configuration**:
  - **Copernicus STAC (Dataspace)** section - OAuth2 credentials
  - **Copernicus HDA (WEkEO)** section - Username/password
- **Individual test buttons** - Test each connection independently
- **Separate timeouts** - 15s for STAC, 45s for HDA
- **Restore defaults** - Per-service default restoration
- **Clear documentation** - Info labels with registration links

---

## 🔧 Technical Details

### New Dependencies
- **hda >= 0.3.0** (Apache 2.0 license)
  - Python client for WEkEO Harmonized Data Access API
  - Dataset query and download functionality
  - Size: ~500KB bundled
- **owslib >= 0.31.0** (BSD license)
  - OGC Web Services parsing library
  - WMS/WMTS GetCapabilities support
  - Size: ~2MB bundled

### Package Information
- **Size**: 5.78 MB (was ~3 MB)
- **Files**: 630 total (597 library files)
- **Growth**: +2.78 MB for 9000+ datasets access

### API Changes
- **Renamed**: `CopernicusConnector` → `CopernicusStacConnector`
- **New class**: `CopernicusHdaConnector` (680 lines)
- **Extended**: ConnectorManager routing for HDA signatures
- **New UI**: QTabWidget + QTreeWidget for layer browser

### Architecture Enhancements
- **Dual secure storage services**:
  - `'copernicus'` - STAC OAuth2 tokens
  - `'copernicus_hda'` - HDA username/password
- **Dynamic query building** - Dataset-specific parameter mapping
- **owslib integration** - Automatic service discovery
- **Conditional UI** - WMS refresh enabled only for HDA connector

---

## 📋 Upgrade Guide

### For Users

#### New Credentials Setup
1. **Copernicus STAC** (existing) - Continue using OAuth2:
   - Settings → Copernicus STAC (Dataspace)
   - Enter client_id and client_secret
   - Test connection

2. **Copernicus HDA** (new) - Register and configure:
   - Visit https://wekeo.eu and register
   - Settings → Copernicus HDA (WEkEO)
   - Enter username and password
   - Test connection

#### Using WMS/WMTS Browser
1. Select "Copernicus HDA (WEkEO)" as data source
2. Choose a dataset from Collections dropdown
3. Click "WMS/WMTS Layers" tab
4. Click "Refresh Layers"
5. Double-click layer or select + "Add to Map"

### For Developers

#### Import Changes
```python
# Old import (still works but deprecated)
from ..connectors.copernicus import CopernicusConnector

# New imports
from ..connectors.copernicus_stac import CopernicusStacConnector
from ..connectors.copernicus_hda import CopernicusHdaConnector
```

#### Secure Storage Keys
```python
# STAC OAuth2 credentials
stac_creds = secure_storage.get_credentials('copernicus')

# HDA username/password
hda_creds = secure_storage.get_credentials('copernicus_hda')
```

---

## 🧪 Testing Recommendations

### Copernicus HDA Authentication Test
1. Configure WEkEO credentials in Settings → Copernicus HDA
2. Click "Test Connection" button
3. **Expected**: 
   - ✅ Authentication successful
   - Sample datasets displayed
   - Connection time shown

### WMS/WMTS Layer Browser Test
1. Select "Copernicus HDA (WEkEO)" as data source
2. Select a dataset (e.g., "EO:EUM:DAT:METOP:AVHR")
3. Switch to "WMS/WMTS Layers" tab
4. Click "Refresh Layers"
5. **Expected**:
   - Layers populate in tree view
   - Layer names, titles, and types displayed
   - Double-click adds layer to map successfully

### HDA Search Test
1. Select Copernicus HDA connector
2. Choose a dataset
3. Define search area and date range
4. Click "Search"
5. **Expected**:
   - Results appear in table
   - Metadata shown correctly
   - Download functional

---

## 📊 Statistics

### Connector Count
- **Before**: 5 connectors
- **After**: 6 connectors (+1 Copernicus HDA)

### Dataset Access
- **Before**: 300+ collections
- **After**: 9000+ datasets (30x increase)

### Code Changes
- **Lines added**: ~1500+
- **New files**: 1 (copernicus_hda.py)
- **Modified files**: 8
- **New methods**: 10+

### Package Metrics
- **Size growth**: +93% (3 MB → 5.78 MB)
- **New dependencies**: 2 (hda, owslib)
- **Bundle efficiency**: ~0.3 KB per dataset

---

## 🐛 Known Issues

### WMS/WMTS Limitations
- Not all WEkEO datasets provide WMS/WMTS services
- Some services may have temporary availability issues
- Performance depends on service response time

### HDA Query Limitations
- Each dataset has unique query parameters
- Generic search uses common parameters only
- Advanced queries may require dataset-specific knowledge

---

## 🔗 Useful Links

- **WEkEO Registration**: https://wekeo.eu
- **HDA Documentation**: https://wekeo.readthedocs.io/
- **Copernicus Dataspace**: https://dataspace.copernicus.eu
- **Plugin Repository**: https://github.com/mlanini/kadas-altair
- **Issue Tracker**: https://github.com/mlanini/kadas-altair/issues

---

# Previous Releases

## v0.3.0 - Copernicus Authentication Fix

---

## 🐛 Critical Bug Fixes

### Copernicus HTTP 403 & Timeout Issues
- **Fixed HTTP 403 error** when loading Copernicus COGs via GDAL vsicurl
  - Root cause: Bearer token not included in GDAL HTTP requests
  - Solution: Configure `GDAL_HTTP_HEADERS` with OAuth2 Bearer token
- **Fixed download timeout** when downloading Copernicus assets
  - Root cause: urllib requests missing Authorization header
  - Solution: Custom urllib.request.Request with Bearer token
- **Improved error messages** with clear diagnostics and user guidance
  - Specific error handling for authentication failures
  - Step-by-step troubleshooting suggestions

### Technical Details
```python
# Preview: GDAL now sends Bearer token
gdal.SetConfigOption('GDAL_HTTP_HEADERS', f'Authorization: Bearer {token}')

# Download: urllib sends Bearer token
req = urllib.request.Request(url)
req.add_header('Authorization', f'Bearer {token}')
```

---

## ✨ New Features

### Enhanced Copernicus Settings
- **Username/Password fields** added to Copernicus settings tab
  - Required for S3 Keys Manager password grant authentication
  - Securely stored using secure_storage API (keyring/encrypted)
  - Masked password input for security
- **Improved credential management**
  - Both OAuth2 (client_id/client_secret) and user credentials supported
  - Credentials automatically retrieved from secure storage
  - No plaintext secrets in logs or QSettings

### Package Versioning
- **Version-tagged ZIP files** for easier deployment tracking
  - `kadas_altair_plugin_full_v0.3.0.zip` (with dependencies)
  - `kadas_altair_plugin_lite_v0.3.0.zip` (minimal)
  - Version automatically read from metadata.txt during packaging

---

## 🔧 Technical Improvements

### Authentication Flow
1. User enters OAuth2 credentials in Settings → Copernicus
2. Plugin obtains Bearer token via client_credentials grant
3. Token stored in connector instance (`copernicus_connector.access_token`)
4. Preview/Download operations retrieve token from connector
5. Token sent in Authorization header for authenticated asset access

### Security Enhancements
- Secure credential storage via `secure_storage.py`
  - System keyring (if available)
  - Encrypted storage with machine-specific key (fallback)
  - Base64 obfuscation (last resort)
- No secrets logged or stored in plaintext
- Automatic credential cleanup on plugin uninstall

---

## 📦 Package Changes

### File Naming
- **Before**: `kadas_altair_plugin_full.zip`
- **After**: `kadas_altair_plugin_full_v0.3.0.zip`
- Version included for better release management

### Checksums
- **SHA256**: `2BE0260A2CB1B9EAA504A89EC7C414A72D78F83C543B8B06CAC938CEBAC911E3`
- **Size**: 1.60 MB (1,675,153 bytes)
- **Build**: 2026-02-28 10:03:43

---

## 🧪 Testing Recommendations

### Copernicus Preview Test
1. Configure OAuth2 credentials in Settings → Copernicus
2. Search for Sentinel-2 L2A imagery
3. Select a result and click "Preview"
4. **Expected**: COG loads successfully without HTTP 403
5. **Log check**: Look for "🔐 Copernicus: Using OAuth2 Bearer token authentication"

### Copernicus Download Test
1. Authenticated as above
2. Select one or more results
3. Click "Download"
4. **Expected**: Files download without timeout/403
5. **Log check**: Look for "Copernicus: Using authenticated HTTPS download"

---

## 📝 Known Limitations

### Token Expiration
- OAuth2 tokens expire after a set period (typically 1 hour)
- Users must re-authenticate if token expires during session
- Future: Automatic token refresh implementation

### Windows SSL Workaround
- `GDAL_HTTP_UNSAFESSL=YES` still required for SChannel compatibility
- Bypasses certificate revocation check on Windows
- Long-term: Update to GDAL with better SSL backend or use curl

### S3 Keys Manager
- Username/password fields added but S3 temporary credentials not yet implemented
- Currently using direct HTTPS access with Bearer token
- Future: Implement S3 Keys Manager password grant for vsis3:// access

---

## 🔄 Upgrade Notes

### From v0.2.0
1. **Backup existing settings** (optional, credentials stored securely)
2. **Uninstall v0.2.0** via Plugins → Manage and Install Plugins
3. **Install v0.3.0** from ZIP: `kadas_altair_plugin_full_v0.3.0.zip`
4. **Reconfigure Copernicus credentials** in Settings → Copernicus
5. **Test preview/download** to verify authentication works

### Settings Migration
- OAuth2 credentials (client_id/client_secret) preserved via secure_storage
- New username/password fields optional (for future S3 Keys Manager support)
- No manual migration required

---

## 📚 Documentation Updates

### New Documents
- **COPERNICUS_AUTH_FIX.md** - Detailed authentication fix documentation
  - Root cause analysis of HTTP 403 error
  - Technical solution explanation
  - Test cases and verification steps

### Updated Documents
- **SHA256SUMS.md** - Updated with v0.3.0 checksums
- **GUIDE.md** - Copernicus authentication section enhanced
- **ARCHITECTURE.md** - Secure storage API documented

---

## 🙏 Acknowledgments

Thanks to all users who reported the Copernicus HTTP 403 issue and provided logs for debugging!

---

## 📥 Download

- **GitHub Release**: [v0.3.0](https://github.com/mlanini/kadas-altair/releases/tag/v0.3.0)
- **Full Package**: `kadas_altair_plugin_full_v0.3.0.zip` (1.60 MB)
- **Lite Package**: `kadas_altair_plugin_lite_v0.3.0.zip` (minimal)

---

**Previous Releases**: See sections below for v0.2.0 and earlier

---

# Release Notes - KADAS Altair Plugin v0.2.0

## 🚀 Performance & Documentation Update

This release focuses on **significant performance improvements** and **comprehensive documentation consolidation** for the KADAS Altair Plugin.

---

## ⚡ Performance Improvements

### Parallel Collection Loading
- **5x faster** collection loading (30s → 6s) using ThreadPoolExecutor with 5 concurrent workers
- Collections from multiple connectors now load simultaneously instead of sequentially
- Dramatically improves user experience when browsing "All Sources"

### Intelligent Caching
- **300x faster** cached responses (30s → 0.1s) with 5-minute TTL cache
- Automatic cache invalidation after authentication flows
- Reduces redundant API calls while keeping data fresh

### Results
| Scenario | Before | After | Improvement |
|----------|--------|-------|-------------|
| Initial Load (5 connectors) | ~30s | ~6s | **5x faster** ⚡ |
| Cached Load | ~30s | ~0.1s | **300x faster** 🚀 |

---

## 🐛 Bug Fixes

### ICEYE Bbox Filtering
- Enhanced logging for bbox filter validation
- Added detailed diagnostics: "✅ INCLUDING" or "❌ EXCLUDING" with coordinate details
- Explicit variable naming (item_west, filter_west) for better debugging
- INFO-level logging helps troubleshoot filtering issues

---

## 📚 Documentation Overhaul

### Consolidation
Reduced from 7+ fragmented files to **4 essential documents**:

1. **README.md** - Project overview and quick start
2. **GUIDE.md** - Complete user manual (22KB)
3. **ARCHITECTURE.md** - Technical reference (25KB) - **NEW**
4. **CONTRIBUTING.md** - Development guidelines (15KB)

### ARCHITECTURE.md (New)
Consolidated technical documentation including:
- System Architecture diagrams
- Connector Framework deep-dive
- Performance Optimizations (parallel loading + caching)
- Network Stack (Qt networking, SSL, proxy handling)
- OpenSSL Configuration
- SAR Connectors diagnostics
- References and resources

### Updated Content
- **KADAS Branding**: All references now correctly specify "KADAS Albireo 2.3+" (not generic QGIS)
- **Installation Paths**: KADAS-specific locations (Kadas/Kadas/profiles/default/)
- **Log Paths**: ~/.kadas/ (not QGIS paths)
- **Network Settings**: KADAS → Settings (QGIS-based platform)
- **Python Version**: 3.12+ included with KADAS Albireo 2

---

## 🔧 Technical Details

### Requirements
- **KADAS Albireo 2.3+** (based on QGIS 3.x platform)
- **Python 3.12+** (included with KADAS)
- Qt-based networking via QgsNetworkAccessManager
- Bundled dependencies (pystac-client)

### Connectors (5 Production-Ready)
1. **ICEYE SAR Open Data** - 3 collections, 196 items, global coverage
2. **Umbra SAR Open Data** - 16cm resolution, recursive STAC catalog
3. **Capella SAR Open Data** - ~1000 images, X-band radar
4. **Maxar Open Data (Vantor STAC)** - 55+ disaster collections, sub-meter optical
5. **Copernicus Dataspace** - Sentinel-1/2/3/5P via OAuth2

### Architecture
- ConnectorManager middleware with parallel execution
- ThreadPoolExecutor (5 workers) for concurrent API calls
- 5-minute TTL cache with auto-invalidation
- Qt-based SSL/proxy handling (no requests library)

---

## 📦 Installation

### Option 1: KADAS Plugin Manager (Recommended)
1. Open KADAS Albireo 2.3+
2. Navigate to **Settings → Manage Plugins**
3. Search for "KADAS Altair"
4. Click **Install Plugin**

### Option 2: Manual Installation
1. Download `kadas_altair_plugin_full.zip` (1.59 MB) from [GitHub Releases](https://github.com/mlanini/kadas-altair/releases)
2. Extract to: `Kadas/Kadas/profiles/default/python/plugins/`
3. Restart KADAS
4. Enable via **Settings → Manage Plugins**

---

## 📖 Documentation

- **[README.md](README.md)** - Project overview
- **[GUIDE.md](GUIDE.md)** - Complete user manual
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Technical reference
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Development guidelines
- **[CHANGELOG.md](CHANGELOG.md)** - Version history

---

## 🐞 Known Issues

- ICEYE bbox filtering requires manual verification via logs (INFO level)
- Cache TTL is fixed at 5 minutes (not configurable via UI)
- Parallel loading limited to 5 concurrent workers (configurable in code)

---

## 🙏 Acknowledgments

- **KADAS Albireo 2** team for the excellent geospatial platform
- All satellite data providers: ICEYE, Umbra, Capella, Maxar, Copernicus
- Contributors and testers from the KADAS community

---

## 📝 License

GPL-2.0 License - See [LICENSE](LICENSE) file for details

---

## 🔗 Links

- **GitHub Repository**: https://github.com/mlanini/kadas-altair
- **Issue Tracker**: https://github.com/mlanini/kadas-altair/issues
- **Author**: Michael Lanini (mlanini@proton.me)

---

**Full Changelog**: [v0.1.0...v0.2.0](https://github.com/mlanini/kadas-altair/compare/v0.1.0...v0.2.0)
