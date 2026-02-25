# KADAS Altair - User Guide

**Complete installation and usage guide**

---

## 📋 Table of Contents

1. [Installation](#installation)
2. [First Use](#first-use)
3. [Data Sources](#data-sources)
4. [Search & Loading](#search--loading)
5. [Authentication](#authentication)
6. [Troubleshooting](#troubleshooting)

---

## 🔧 Installation

### Option 1: ZIP Package (Recommended)

1. Download `kadas_altair_plugin_full.zip`
2. KADAS Albireo → **Plugins** → **Manage and Install Plugins**
3. **Install from ZIP** tab → Select ZIP file
4. **Activate** plugin from Installed Plugins tab

### Option 2: Manual Copy

**Windows:**
```powershell
Copy-Item -Recurse kadas_altair_plugin "$env:APPDATA\Kadas\Kadas\profiles\default\python\plugins\"
```

**Linux/macOS:**
```bash
cp -r kadas_altair_plugin ~/.local/share/Kadas/Kadas/profiles/default/python/plugins/
```

### Requirements

- KADAS Albireo 2.3+ (based on QGIS 3.x)
- Internet connection
- ~2 MB disk space

---

## 🚀 First Use

### 1. Open Plugin Panel

**Plugins** → **Altair** → **Altair EO Data Panel**

### 2. Select Connector

Choose from dropdown:
- **ICEYE SAR Open Data** (fastest test - 196 items)
- **Maxar Open Data** (55+ disaster events)
- **Umbra SAR Open Data** (high-res radar)
- **Capella SAR Open Data** (~1000 images)
- **Copernicus Dataspace** (Sentinel constellation)

### 3. Authenticate

Click **Authenticate** button:
- **ICEYE, Maxar, Umbra, Capella**: No credentials needed
- **Copernicus**: Requires client_id/client_secret (see [Authentication](#authentication))

### 4. Select Collection

Collections load automatically in dropdown. Select one.

### 5. Define Search Area

**Option A - Draw on Map:**
1. Click **Draw Bbox** button
2. Click and drag rectangle on map
3. Coordinates auto-populate

**Option B - Use Map Extent:**
1. Zoom to desired area
2. Click **Use Map Extent** button

**Option C - Manual Entry:**
1. Enter coordinates: `minX, minY, maxX, maxY`
2. Format: `7.0, 46.0, 8.0, 47.0` (EPSG:4326)

### 6. Set Filters (Optional)

- **Date Range**: Start/End dates
- **Cloud Cover**: 0-100% (optical imagery only)

### 7. Search

Click **Search** button → Results appear in table

### 8. Load Imagery

1. Select row(s) in results table
2. Click **Load Layer** button
3. Imagery appears in KADAS layers panel

---

## 🛰️ Data Sources

### ICEYE SAR Open Data

**Type:** Synthetic Aperture Radar  
**Collections:** 3 (196 total items)  
**Resolution:** 1-3 meters  
**Coverage:** Global  
**Auth:** None required

**Features:**
- All-weather acquisition (works through clouds)
- Day/night imaging
- Pre-filtered by quality

**Use Cases:** Emergency response, maritime surveillance, flood monitoring

### Umbra SAR Open Data

**Type:** Synthetic Aperture Radar  
**Collections:** Recursive STAC (year → month → items)  
**Resolution:** 16-25 cm (world's highest commercial SAR)  
**Coverage:** Global  
**Auth:** None required

**Products:** GEC, SICD, SIDD, CPHD  
**License:** CC BY 4.0

**Use Cases:** Ultra-high resolution monitoring, infrastructure inspection

### Capella SAR Open Data

**Type:** Synthetic Aperture Radar  
**Collections:** ~1000 images (6 organization types)  
**Resolution:** ~1 meter  
**Coverage:** Global  
**Auth:** None required

**Organizations:** product, mode, use-case, capital, datetime, IEEE  
**Products:** GEO, GEC, SLC, SICD, SIDD, CPHD

**Use Cases:** Defense, disaster response, commercial analytics

### Maxar Open Data (Vantor STAC)

**Type:** Optical Imagery  
**Collections:** 55+ disaster events  
**Resolution:** 0.3-0.5 meters (sub-meter)  
**Coverage:** Disaster areas worldwide  
**Auth:** None required

**Satellites:** WorldView, GeoEye, Pléiades  
**License:** CC BY-NC-SA 4.0

**Use Cases:** Disaster assessment, emergency response, damage mapping

### Copernicus Dataspace

**Type:** Multi-sensor (Optical + SAR + Atmospheric)  
**Collections:** Sentinel-1, 2, 3, 5P  
**Resolution:** 10m (S2) to 7km (S5P)  
**Coverage:** Global  
**Auth:** OAuth2 required

**Free registration:** https://dataspace.copernicus.eu/

**Use Cases:** Environmental monitoring, agriculture, urban planning

---

## 🔍 Search & Loading

### Search Parameters

All search filters are **optional** and can be enabled/disabled with checkboxes:

| Parameter | Description | Format | Optional |
|-----------|-------------|--------|----------|
| **Search Area** | Bounding box or polygon | `minX, minY, maxX, maxY` (WGS84) | ✓ Use checkbox |
| **Date Range** | Start and end dates | `YYYY-MM-DD` | ✓ Use checkbox |
| **Cloud Cover** | Max % clouds | `0-100` (optical only) | ✓ Use checkbox |
| **Collection** | Data collection | Dropdown selection | ✓ Select "All" |

**Tips:**
- Uncheck "Use Search Area" to search globally (all available data)
- Uncheck "Use Date Range" to search all time periods
- Uncheck "Use Cloud Cover Filter" to include all cloud conditions
- Without filters, search returns all available data from the connector

### Results Table

Columns vary by connector, typically include:
- **ID**: Unique identifier
- **Date**: Acquisition date/time
- **Platform**: Satellite/sensor
- **Cloud Cover**: % (optical)
- **GSD**: Ground sample distance (resolution)

### Loading Imagery

**COG (Cloud-Optimized GeoTIFF):**
- Loaded via GDAL `/vsicurl/` driver
- No download needed - streams from cloud
- Zoom controls detail level

**Supported Formats:**
- GeoTIFF (.tif)
- COG (Cloud-Optimized GeoTIFF)
- JPEG 2000 (.jp2)

---

## 🔐 Authentication

### Copernicus Dataspace

**Required for:** Sentinel-1, Sentinel-2, Sentinel-3, Sentinel-5P

**Get Credentials:**
1. Register at https://dataspace.copernicus.eu/
2. Create OAuth2 application
3. Copy `client_id` and `client_secret`

**Enter Credentials:**
1. Select "Copernicus Dataspace" connector
2. Click **Settings** (gear icon)
3. Enter `client_id` and `client_secret`
4. Click **Save**
5. Click **Authenticate** in main panel

**Credentials stored securely** in KADAS settings (QGIS-based).

### Other Connectors

**ICEYE, Umbra, Capella, Maxar:** No authentication needed (open data)

---

## 🔧 Troubleshooting

### Plugin Not Appearing

**Check:**
- Plugin is activated: Plugins → Manage and Install Plugins → Installed
- KADAS version ≥ 2.3 (based on QGIS 3.x)
- Plugin copied to correct directory

**Fix:**
```powershell
# Verify installation directory
ls "$env:APPDATA\Kadas\Kadas\profiles\default\python\plugins\kadas_altair_plugin"
```

### Authentication Failed (Copernicus)

**Symptoms:** "Invalid credentials" error

**Solutions:**
2. Verify `client_id` and `client_secret` are correct
3. Check no extra whitespace in credentials
4. Ensure internet connection
5. Check proxy settings: KADAS → Settings → Options → Network
6. View logs: Plugins → Altair → View Logs

### No Search Results

**Check:**
1. **Bbox valid**: minX < maxX, minY < maxY
2. **Date range**: Start before end date
3. **Collection selected**: Dropdown not empty
4. **Area coverage**: Collection covers search area
5. **Internet connection**: Active

### Layer Not Loading

**Check:**
1. **GDAL support**: KADAS has GDAL with COG support (inherited from QGIS)
2. **URL accessible**: Check logs for 404/403 errors
3. **Firewall**: Allow KADAS internet access
4. **Proxy**: Configure if behind corporate proxy

### Slow Performance

**Solutions:**
1. **Reduce bbox size**: Smaller area = fewer results
2. **Limit date range**: Shorter period = fewer results  
3. **Increase cloud threshold**: Filters more optical imagery
4. **Close other apps**: Free memory

### View Logs

**Plugins → Altair → View Logs**

Logs show:
- Authentication attempts
- API requests/responses
- Errors with stack traces
- Network issues

**Log location:**
- Windows: `%APPDATA%\.kadas\altair_plugin.log`
- Linux: `~/.kadas/altair_plugin.log`
- macOS: `~/.kadas/altair_plugin.log`

---

## 📚 Additional Resources

- **[README.md](README.md)**: Overview and features
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: System architecture, connectors, performance, network stack
- **[CONTRIBUTING.md](CONTRIBUTING.md)**: Development guidelines, testing
- **Repository**: https://github.com/mlanini/kadas-altair
- **Issues**: https://github.com/mlanini/kadas-altair/issues

---

**Need Help?** Open an issue on GitHub or email mlanini@proton.me
- **Python**: 3.12+ (included with KADAS Albireo 2)
- **Internet**: Required for catalog and imagery access

**No additional Python packages required!** The plugin uses only KADAS built-in libraries (QGIS-based).

---

## Available Data Sources

The plugin includes 3 production-ready connectors:

| Connector | Collections | Type | Coverage | Status |
|-----------|-------------|------|----------|--------|
| **ICEYE SAR Open Data** | 3 | SAR Imagery | Global | ✅ Ready |
| **Maxar Open Data** | 55 | Optical | Disaster Events | ✅ Ready |
| **swisstopo RapidMapping** | 3+ | Emergency Mapping | Switzerland | ✅ Ready |

### ICEYE SAR Open Data

- **Type**: Synthetic Aperture Radar (SAR)
- **Collections**: 3 (196 total items)
- **Resolution**: Various
- **Coverage**: Global sample areas
- **Use Cases**: All-weather imaging, change detection
- **Features**: Cloud-independent, day/night acquisition

### Maxar Open Data (Vantor STAC)

- **Type**: High-resolution optical imagery
- **Collections**: 55 disaster/emergency events
- **Resolution**: Sub-meter
- **Coverage**: Disaster response areas worldwide
- **Use Cases**: Emergency response, damage assessment
- **Features**: Very high resolution, recent events

### swisstopo RapidMapping

- **Type**: Emergency mapping products
- **Collections**: BLATTEN and other Swiss events
- **Coverage**: Switzerland
- **Use Cases**: Rapid disaster response, emergency planning
- **Features**: Localized, time-critical mapping

---

## Configuration

### AWS STAC Settings

Access: `Plugins` → `Altair` → `Settings` → `AWS STAC` tab

**Configurable Options**:

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| **Catalog URL** | AWS Open Data STAC | Any valid URL | Source of STAC endpoint catalog |
| **Catalog Timeout** | 30 seconds | 5-120s | Timeout for loading catalog |
| **Search Timeout** | 20 seconds | 5-120s | Timeout for search requests |
| **Rate Limit Delay** | 1 second | 0-10s | Delay between pagination requests |

**Restore Defaults**: Click "Ripristina URL Predefinito" button to reset catalog URL.

### Display Settings

Access: `Plugins` → `Altair` → `Settings` → `Visualizzazione` tab

- **Auto-zoom su risultati**: Automatically zoom to search results
- **Risultati massimi**: Maximum number of results to display (10-1000)

### Network Configuration

The plugin **automatically inherits** QGIS network settings:

- **Proxy**: `Settings` → `Options` → `Network` → Configure proxy in QGIS
- **SSL**: Uses QGIS SSL certificate configuration
- **Authentication**: No authentication required for AWS Open Data

**No plugin-specific network configuration needed!**

---

## Using the Plugin

### Main Workflow

```
1. Open Panel → 2. Load Catalog → 3. Select Endpoint → 4. Choose Collection
                                                              ↓
8. Load Imagery ← 7. Select Results ← 6. Review Results ← 5. Search
```

### Step-by-Step Guide

#### 1. Open the Panel

`Plugins` → `Altair` → `Altair EO Data Panel`

#### 2. Load AWS Catalog

Click **"Carica Catalogo"** button

- Downloads catalog from GitHub
- Discovers 50+ STAC endpoints
- Populates endpoint dropdown

#### 3. Select STAC Endpoint

Choose from dropdown (e.g.):
- Sentinel-2 Cloud-Optimized GeoTIFFs
- Landsat Collection 2 Level-2
- Maxar Open Data
- CBERS-4 AWS

#### 4. Collection Auto-Population

**Automatic**: Collections load when endpoint selected

Shows:
- "Tutte le Collections STAC" (search all)
- Individual collections (e.g., "sentinel-2-l2a")

#### 5. Set Search Parameters

**Area** (4 methods):
- Use current map extent
- Draw on map (rectangle/polygon)
- Select from existing layer
- Manual coordinates entry

**Date Range**:
- Start date (Data Inizio)
- End date (Data Fine)

**Cloud Cover**:
- Slider: 0-100%
- Only applies to optical imagery

**Collection** (optional):
- "All" searches all collections
- Select specific collection for focused search

#### 6. Execute Search

Click **"Cerca"** button

Results display:
- **Table**: Date, Satellite, Cloud%, GSD, Collection
- **Map**: Footprints as colored polygons

#### 7. Interactive Selection

**Select from Table**:
- Click row → Highlights on map
- Multiple selection: Ctrl+Click

**Select from Map**:
- Click "Seleziona dalla Mappa" button
- Click footprint on map → Selects in table
- Ctrl+Click to toggle selection

**Bidirectional Sync**: Table ↔ Map selection always synchronized

#### 8. Load Imagery

**Preview**:
- Select results → Click "Anteprima"
- Opens thumbnail or quicklook

**Load COG**:
- Select results → Click "Carica Layer"
- Loads Cloud-Optimized GeoTIFF
- Uses GDAL vsicurl (no download needed)
- Priority: visual → data → rendered_preview → thumbnail

**Zoom to Selection**:
- Click "Zoom su Selezione"
- Map zooms to selected footprints

---

## Troubleshooting

### Common Issues

#### "Failed to fetch AWS catalog"

**Causes**:
- No internet connection
- Firewall blocking GitHub
- Catalog URL changed

**Solutions**:
1. Check internet connection
2. Test URL in browser: https://raw.githubusercontent.com/opengeos/aws-open-data-stac/refs/heads/master/aws_stac_catalogs.json
3. Configure proxy in QGIS if behind corporate firewall
4. Restore default URL: `Settings` → `AWS STAC` → "Ripristina URL Predefinito"

#### "No collections found"

**Causes**:
- Selected endpoint doesn't have `/collections` route
- Endpoint temporarily unavailable
- Network timeout

**Solutions**:
1. Try different endpoint
2. Increase timeout: `Settings` → `AWS STAC` → Catalog Timeout
3. Check endpoint URL in browser

#### "Search returned no results"

**Causes**:
- No imagery in selected area/date range
- Cloud cover filter too strict
- Wrong collection selected

**Solutions**:
1. Expand date range
2. Increase cloud cover threshold
3. Try "Tutte le Collections STAC"
4. Verify area is correct (zoom to see red bbox)

#### "Failed to load COG layer"

**Causes**:
- GDAL vsicurl not available
- Asset URL requires authentication
- Network issues

**Solutions**:
1. Check GDAL version: `Processing` → `Toolbox` → Search "gdal"
2. Try direct URL (without vsicurl)
3. Check asset type (COG, GeoTIFF, etc.)

#### "Proxy authentication required"

**Causes**:
- Corporate proxy needs credentials
- QGIS proxy not configured

**Solutions**:
1. Configure proxy in QGIS: `Settings` → `Options` → `Network`
2. Enter credentials in QGIS proxy settings
3. Restart QGIS after changing proxy

### Logging

**View Logs**: `Plugins` → `Altair` → `📋 Visualizza Log`

**Log Location**:
- Windows: `C:\Users\<username>\.kadas\altair_plugin.log`
- Linux: `~/.kadas/altair_plugin.log`
- macOS: `~/.kadas/altair_plugin.log`

**Log Levels**:
- **INFO**: Normal operations
- **WARNING**: Non-critical issues
- **ERROR**: Failed operations
- **DEBUG**: Detailed diagnostic info

---

## Project Structure

```
kadas-altair/
├── README.md                      # Project overview
├── GUIDE.md                       # This user guide
├── ARCHITECTURE.md                # System architecture & technical reference
├── CONTRIBUTING.md                # Development guidelines
├── LICENSE                        # GPL-2.0 License
├── package_plugin_full.py         # Build script (full)
├── package_plugin_lite.py         # Build script (lite)
└── kadas_altair_plugin/          # Plugin source
    ├── README.md                  # Plugin info
    ├── metadata.txt               # Plugin metadata
    ├── __init__.py                # Plugin entry point
    ├── plugin.py                  # Main plugin class
    ├── logger.py                  # Logging system
    ├── connectors/                # Data source connectors
    │   ├── iceye_stac.py         # ICEYE SAR connector
    │   ├── vantor.py             # Maxar Open Data connector
    │   ├── umbra_stac.py         # Umbra SAR connector
    │   ├── capella_stac.py       # Capella SAR connector
    │   ├── copernicus.py         # Copernicus Dataspace
    │   ├── connector_manager.py  # Connector registry
    │   └── ...                    # Other connectors
    ├── gui/                       # User interface
    │   ├── dock.py               # Main dock widget
    │   ├── settings_dock.py      # Settings dialog
    │   └── ...                    # UI components
    ├── utilities/                 # Helper modules
    │   └── proxy_handler.py
    ├── secrets/                   # Credential management
    │   └── secure_storage.py
    └── test/                      # Test scripts
        ├── test_connectors.py    # Connector tests
        └── ...                    # Other tests
```

---

## Advanced Features

### Custom Catalog URL

Use your own STAC catalog:

1. `Settings` → `AWS STAC`
2. Enter custom URL in "Catalog URL" field
3. Click "Salva Impostazioni"
4. Reload panel

**Requirements**:
- URL must return JSON array of datasets
- Each dataset must have `Explore` links with STAC URLs

### Footprint Layer Styling

Customize footprint appearance:

1. Right-click footprints layer in Layers panel
2. `Properties` → `Symbology`
3. Change:
   - Fill color/opacity
   - Border color/width
   - Label expression

### Batch Processing

Load multiple images at once:

1. Search for imagery
2. Select multiple results (Ctrl+Click)
3. Click "Carica Layer"
4. All selected images load as separate layers

### Export Search Results

Save search results for later:

1. Execute search
2. Right-click footprints layer
3. `Export` → `Save Features As...`
4. Choose format (GeoJSON, Shapefile, etc.)

### Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Toggle Panel | *(not assigned)* |
| Search | Enter (in search form) |
| Select All Results | Ctrl+A (in table) |
| Copy Selection | Ctrl+C (in table) |
| Zoom to Selected | Double-click row |

### API Integration

Access connector programmatically:

```python
from kadas_altair_plugin.connectors.aws_stac import AwsStacConnector

# Create connector
connector = AwsStacConnector()

# Authenticate (load catalog)
connector.authenticate()

# Get endpoints
endpoints = connector.get_stac_endpoints()

# Set endpoint
connector.set_endpoint(endpoints[0]['url'])

# Get collections
collections = connector.get_collections()

# Search
results, next_link = connector.search(
    bbox=[7.0, 46.0, 8.0, 47.0],
    start_date='2024-01-01',
    end_date='2024-01-31',
    max_cloud_cover=20,
    collection='sentinel-2-l2a'
)
```

---

## Supported Datasets

### Optical Imagery

- **Sentinel-2**: L1C (TOA), L2A (BOA)
- **Landsat**: Collection 2 Level-1, Level-2
- **CBERS-4**: MUX, AWFI, PAN5M, PAN10M
- **NAIP**: National Agriculture Imagery Program
- **Maxar Open Data**: Disaster response imagery

### SAR Imagery

- **Sentinel-1**: GRD, SLC
- **ALOS PALSAR**: Global forest/non-forest maps

### Other Datasets

- **USGS 3DEP**: Digital Elevation Models
- **NOAA**: Climate data, sea surface temperature
- **ASTER**: GDEM, L1T

**Total**: 50+ datasets accessible through AWS Open Data STAC catalog

---

## Tips & Best Practices

### Performance

✅ **DO**:
- Use collection filter for faster searches
- Limit search area to region of interest
- Set reasonable date ranges
- Use cloud cover filter for optical imagery

❌ **DON'T**:
- Search entire world at once
- Use very long date ranges (years)
- Load too many layers simultaneously (>10)

### Data Selection

✅ **Best for Different Use Cases**:

| Use Case | Dataset | Collection |
|----------|---------|------------|
| **Multispectral Analysis** | Sentinel-2 | sentinel-2-l2a |
| **Large Area Mapping** | Landsat | landsat-c2-l2 |
| **High-Res Basemaps** | Maxar | maxar-open-data |
| **Disaster Response** | Maxar Open Data | Event-specific |
| **Change Detection** | Sentinel-2 + Landsat | Both |
| **Forest Monitoring** | ALOS PALSAR | palsar-global |

### COG Loading

- **Visual assets**: Best for display/basemaps
- **Data assets**: Best for analysis (full spectral bands)
- **Thumbnails**: Fast preview, low quality

**Tip**: Start with thumbnail/preview, then load data asset if needed.

---

## Getting Help

### Resources

- **[README.md](README.md)**: Overview and features
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: System architecture, connectors, performance, network stack
- **[CONTRIBUTING.md](CONTRIBUTING.md)**: Development guidelines, testing
- **Repository**: https://github.com/mlanini/kadas-altair
- **Issues**: https://github.com/mlanini/kadas-altair/issues
- **In-App Help**: `Plugins` → `Altair` → `Help`

### Support

**Before Reporting Issues**:
1. Check logs: `📋 Visualizza Log`
2. Try with different endpoint
3. Verify internet connection
4. Update to latest version

**Issue Report Should Include**:
- QGIS/KADAS version
- Plugin version
- Error message (copy from logs)
- Steps to reproduce
- Expected vs actual behavior

### Contributing

Found a bug? Have a feature request?

1. Check existing issues
2. Create new issue with details
3. Include logs and screenshots
4. Be specific and constructive

---

## License & Credits

**License**: GNU GPL v2 or later

**Author**: Michael Lanini (michael@intelligeo.ch)

**Built With**:
- QGIS/KADAS API
- AWS Open Data STAC Catalog
- GDAL vsicurl

**Inspired By**:
- kadas-vantor-plugin (footprint interaction patterns)
- opengeos/aws-open-data-stac (catalog source)

**© 2026 Michael Lanini** - Open Source Software
