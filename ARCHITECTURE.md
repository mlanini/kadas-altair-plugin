# KADAS Altair - Architecture & Technical Reference

**Complete technical documentation for developers and advanced users**

**Note**: This is a **KADAS Albireo 2** plugin (based on QGIS 3.x platform). While it uses QGIS APIs, it's specifically designed for KADAS.

---

## 📋 Table of Contents

1. [System Architecture](#system-architecture)
2. [Connector Framework](#connector-framework)
3. [Performance Optimizations](#performance-optimizations)
4. [Network Stack](#network-stack)
5. [Proxy & VPN Handling](#proxy--vpn-handling)
6. [OpenSSL Configuration](#openssl-configuration)
7. [SAR Connectors](#sar-connectors)

---

# System Architecture

## Overview

KADAS Altair follows a **middleware architecture** that decouples the UI from data source implementations, providing a unified interface for searching and accessing satellite imagery.

```
┌─────────────────────────────────────────────────────────┐
│                KADAS Albireo 2.3+                       │
│              (Built on QGIS 3.x Platform)               │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│              KADAS Altair Plugin (GUI)                  │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────┐   │
│  │  dock.py   │  │ settings   │  │  log_viewer.py   │   │
│  │ (Main UI)  │  │  _dock.py  │  │   (Debugging)    │   │
│  └─────┬──────┘  └────────────┘  └──────────────────┘   │
│  ┌──────────────────────────────────────────────┐       │
│  │ smart_tasking_dock.py (Smart Tasking)        │       │
│  │ SGP4 bearing-convergence overpass prediction │       │
│  │ + 3D orbit/ground track/swath visualisation  │       │
│  └──────────────────────────────────────────────┘       │
└────────┼────────────────────────────────────────────────┘
         │
┌────────▼─────────────────────────────────────────────────┐
│           Connector Manager (Middleware)                 │
│  • Unified search API                                    │
│  • Result standardization (STAC-like)                    │
│  • Authentication management                             │
│  • Parallel collection loading (5x speedup)              │
│  • 5-minute caching (300x speedup on reload)             │
└────────┬─────────────────────────────────────────────────┘
         │
┌────────▼─────────────────────────────────────────────────┐
│                    Connectors (10)                       │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐               │
│  │  Vantor  │  │  ICEYE   │  │   Umbra   │               │
│  │  (CSV)   │  │  (STAC)  │  │   (STAC)  │               │
│  └────┬─────┘  └────┬─────┘  └─────┬─────┘               │
│  ┌────┴─────┐  ┌────┴─────┐  ┌─────┴─────┐               │
│  │ Capella  │  │Copernicus│  │  Planet   │               │
│  │  (STAC)  │  │  (STAC)  │  │   (API)   │               │
│  └──────────┘  └────┬─────┘  └───────────┘               │
│                     │                                    │
│              (OAuth2 Token)                              │
└────────┬─────────────────────────────────────────────────┘
         │
┌────────▼─────────────────────────────────────────────────┐
│              Network Layer (Qt-based + owslib)           │
│  • QgsNetworkAccessManager (proxy-aware)                 │
│  • SSL/TLS via Qt (no Python ssl dependency)             │
│  • VPN-compatible (handles SSL inspection)               │
│  • owslib for WMS/WMTS GetCapabilities parsing           │
└────────┬─────────────────────────────────────────────────┘
         │
┌────────▼─────────────────────────────────────────────────┐
│                  Data Sources                            │
│  • GitHub (CSV, GeoJSON)                                 │
│  • STAC APIs (Umbra, ICEYE, Capella, Copernicus)         │
│  • REST APIs (Copernicus STAC, Planet)                   │
│  • OGC Web Services (WMS/WMTS)                           │
│  • AWS S3 (COG imagery)                                  │
└──────────────────────────────────────────────────────────┘
```

## Project Structure

```
kadas_altair_plugin/
├── __init__.py               # Plugin entry point, OpenSSL config
├── plugin.py                 # Main plugin class, proxy setup
├── logger.py                 # Logging system
├── metadata.txt              # Plugin metadata
│
├── connectors/               # Data source implementations
│   ├── __init__.py
│   ├── base.py              # Abstract base connector
│   ├── connector_manager.py # Middleware (registry + routing)
│   ├── vantor.py            # Vantor Open Data (CSV + GeoJSON)
│   ├── iceye_stac.py        # ICEYE SAR (STAC catalog)
│   ├── umbra_stac.py        # Umbra SAR (recursive STAC)
│   ├── capella_stac.py      # Capella SAR (STAC)
│   ├── copernicus_stac.py   # Copernicus STAC (OAuth2 + REST)
│   ├── jilin_gaofen_stac.py # Jilin-1 Gaofen (commercial, tasking only)
│   ├── oneatlas.py          # OneAtlas (stub)
│   ├── planet.py            # Planet (stub)
│   └── nasa_earthdata.py    # NASA EarthData (stub)
│
├── gui/                      # User interface
│   ├── __init__.py
│   ├── dock.py              # Main panel (search, results, loading)
│   ├── dock_clean.py        # Refactored dock (experimental)
│   ├── smart_tasking_dock.py # Smart Tasking (SGP4 overpass prediction)
│   ├── archive_dock.py      # Archive search dock
│   ├── settings_dock.py     # Settings dialog
│   ├── log_viewer.py        # Log viewer window
│   └── footprint_tool.py    # Map selection tool
│
├── utilities/                # Helper modules
│   ├── __init__.py
│   └── proxy_handler.py     # Proxy configuration
│
├── secrets/                  # Credential management
│   ├── __init__.py
│   ├── secure_storage.py    # Encrypted credential storage
│   └── proxy_config.json.example
│
└── icons/                    # UI icons
    └── *.png
```

---

# Dependencies

## Core Dependencies (Bundled in Full Package)

### pystac-client (>=0.8.5)
- **Purpose**: STAC API client library
- **License**: Apache 2.0
- **Size**: ~1 MB bundled
- **Used by**: ICEYE, Umbra, Capella, Copernicus STAC connectors
- **Features**: Catalog browsing, item search, pagination

### owslib (>=0.31.0)
- **Purpose**: OGC Web Services client library
- **License**: BSD
- **Size**: ~2 MB bundled
- **Used by**: Various connectors for OGC service parsing
- **Features**: GetCapabilities parsing, WMS 1.3.0, WMTS support

### Total Package Size
- **Lite package**: ~200 KB (plugin code only)
- **Full package**: ~5.78 MB (plugin + dependencies)

## QGIS/KADAS Built-in Libraries (Not Bundled)

### qgis.core
- `QgsNetworkAccessManager` - HTTP/HTTPS networking
- `QgsRasterLayer` - Raster layer management
- `QgsCoordinateReferenceSystem` - CRS handling
- `QgsRectangle` - Bounding box geometry
- `QgsProject` - Project management

### qgis.PyQt
- `QtCore` - Qt core functionality
- `QtWidgets` - UI widgets
- `QtNetwork` - Network operations

### Python Standard Library
- `json`, `datetime`, `typing`, `pathlib` - Data handling
- `concurrent.futures` - Parallel execution
- `abc` - Abstract base classes

---

# Connector Framework

## Base Architecture

All connectors inherit from `BaseConnector` (abstract base class):

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class BaseConnector(ABC):
    """Abstract base class for data connectors"""
    
    @abstractmethod
    def authenticate(self, credentials: Optional[Dict] = None) -> bool:
        """Authenticate with the service"""
        pass
    
    @abstractmethod
    def get_collections(self) -> List[Dict[str, Any]]:
        """Get available collections/datasets"""
        pass
    
    @abstractmethod
    def search(self, bbox: List[float], start_date: str, 
               end_date: str, **kwargs) -> List[Dict[str, Any]]:
        """Search for imagery"""
        pass
```

## Connector Manager (Middleware)

**File**: `connectors/connector_manager.py`

The ConnectorManager provides:
- **Unified API** for all connectors
- **Result standardization** (STAC-like format)
- **Authentication state** management
- **Routing logic** based on connector type
- **"All Sources" aggregation** (parallel search across all connectors)

```python
class ConnectorManager:
    def __init__(self):
        self._connectors = {}  # Registry
        self._active_connector = None
        
    def register_connector(self, connector_id, instance, 
                          display_name, capabilities):
        """Register a connector"""
        
    def search(self, bbox, start_date, end_date, **kwargs):
        """Unified search interface"""
        
    def get_all_collections(self, use_cache=True):
        """Aggregate collections from all connectors (cached)"""
        
    def search_all_sources(self, bbox, start_date, end_date, **kwargs):
        """Search across all authenticated connectors"""
```

## Connector Types

### 1. CSV-based (Vantor)

**Data Source**: GitHub raw CSV + GeoJSON  
**Authentication**: None required  
**Collections**: 56 disaster events  

```python
# Load events from CSV
def load_events(self):
    csv_url = "https://raw.githubusercontent.com/.../datasets.csv"
    csv_data = self._fetch_url(csv_url)
    lines = csv_data.strip().split("\n")
    for line in lines[1:]:  # Skip header
        parts = line.split(",")
        event_name = parts[0]
        tile_count = int(parts[1])
```

### 2. STAC Catalog (ICEYE, Umbra, Capella)

**Data Source**: STAC JSON catalogs  
**Authentication**: None (open data)  
**Collections**: 3-1000+ items  

```python
# Navigate STAC hierarchy
def _fetch_catalog_if_needed(self):
    if not self._catalog:
        self._catalog = self._http_get(self.base_url)
    return self._catalog is not None

def get_collections(self):
    # Navigate child links
    for link in self._catalog['links']:
        if link['rel'] == 'child':
            collection_data = self._http_get(link['href'])
```

### 3. REST API + OAuth2 (Copernicus)

**Data Source**: Copernicus Dataspace API  
**Authentication**: OAuth2 (client credentials flow)  
**Collections**: Sentinel 1/2/3/5P (12 collections)  

```python
def authenticate(self, credentials):
    # OAuth2 token request
    response = requests.post(
        'https://identity.dataspace.copernicus.eu/auth/realms/.../token',
        data={
            'grant_type': 'client_credentials',
            'client_id': credentials['client_id'],
            'client_secret': credentials['client_secret']
        }
    )
    self._access_token = response.json()['access_token']
```

---

# Authentication Architecture

## Dual Secure Storage

KADAS Altair v0.3.1+ uses **two separate secure storage services**:

### Copernicus STAC (OAuth2)
- **Service Name**: `'copernicus'`
- **Credentials**: `client_id`, `client_secret`
- **Storage**: QGIS settings + keyring/encryption
- **Usage**: Token-based API access

## Credential Fallback Chain

### Copernicus STAC
1. **UI credentials** (Settings → Copernicus STAC section)
2. **Secure storage** (keyring → cryptography → base64)

## Secure Storage Implementation

**File**: `secrets/secure_storage.py`

```python
class SecureStorageService:
    """3-level credential storage"""
    
    def store_credentials(self, service_name, username, password):
        """Store credentials with fallback chain"""
        try:
            # Level 1: System keyring (Windows Credential Manager, macOS Keychain)
            keyring.set_password(service_name, username, password)
        except:
            try:
                # Level 2: Encrypted file (cryptography library)
                self._store_encrypted(service_name, username, password)
            except:
                # Level 3: Base64 obfuscated (QGIS settings)
                self._store_obfuscated(service_name, username, password)
    
    def get_credentials(self, service_name):
        """Retrieve credentials with same fallback"""
        # Try keyring → encrypted → obfuscated
```

---

# Performance Optimizations

## Collection Loading

### Problem
Sequential collection loading from 9 connectors took **~30 seconds**, making "All Sources" mode unusable.

### Solution: Parallel Loading + Caching

**File**: `connectors/connector_manager.py`

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

def get_all_collections(self, use_cache: bool = True) -> List[Dict[str, Any]]:
    """Get collections from ALL registered connectors (OPTIMIZED)
    
    PERFORMANCE OPTIMIZATIONS:
    - Parallel loading with ThreadPoolExecutor (5 workers)
    - In-memory caching with 5-minute TTL
    - Timeout protection (10s per connector)
    - Graceful error handling
    """
    # Check cache first (5-minute TTL)
    cache_key = '_all_collections_cache'
    cache_ttl = 300  # 5 minutes
    
    if use_cache and hasattr(self, cache_key):
        timestamp = getattr(self, '_all_collections_cache_timestamp', 0)
        if time.time() - timestamp < cache_ttl:
            return getattr(self, cache_key)
    
    # Parallel execution
    all_collections = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_connector = {
            executor.submit(self._fetch_connector_collections, 
                          conn_id, conn_info): conn_id
            for conn_id, conn_info in self._connectors.items()
        }
        
        for future in as_completed(future_to_connector, timeout=100):
            conn_id, collections, error = future.result(timeout=10)
            if collections:
                all_collections.extend(collections)
    
    # Cache results
    setattr(self, cache_key, all_collections)
    setattr(self, '_all_collections_cache_timestamp', time.time())
    
    return all_collections
```

### Performance Benchmarks

| Connector | Individual Time | Sequential Total | Parallel Total |
|-----------|----------------|------------------|----------------|
| Vantor | 2.3s | - | - |
| ICEYE | 4.1s | - | - |
| Copernicus | 0.1s | - | - |
| NASA EarthData | 1.8s | - | - |
| Planet | 0.05s | - | - |
| **Total (5 connectors)** | - | **~30s** | **~6s** |
| **Total (cached)** | - | **~30s** | **<0.1s** |

**Speedup**: 
- First load: **5x faster** (30s → 6s)
- Cached load: **300x faster** (30s → 0.1s)

### Cache Management

**Auto-invalidation**:
- When user authenticates/de-authenticates
- Triggered in `dock.py` after `authenticate_connector()` calls

**Manual invalidation**:
```python
connector_manager.clear_collections_cache()
```

---

# Network Stack

## Qt-based Networking (Primary)

All modern connectors use `QgsNetworkAccessManager`:

```python
from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.PyQt.QtCore import QUrl

def _fetch_url(self, url: str) -> str:
    """Fetch URL content using Qt networking"""
    nam = QgsNetworkAccessManager.instance()
    request = QNetworkRequest(QUrl(url))
    
    # Synchronous request
    reply = nam.blockingGet(request)
    
    if reply.error():
        raise Exception(f"Network error: {reply.errorString()}")
    
    return bytes(reply.content()).decode('utf-8')
```

**Benefits**:
- ✅ **Automatic proxy detection** from KADAS settings
- ✅ **SSL/TLS via Qt** (no Python `ssl` module)
- ✅ **VPN-compatible** (handles SSL inspection)
- ✅ **Cross-platform** (Windows, Linux, macOS)
- ✅ **Certificate management** via Qt

## Legacy Connectors (Fallback)

Some connectors use `requests` library:
- Environment variables propagated from KADAS proxy settings
- Set at plugin startup in `plugin.py`

---

# UI Components

## Main Dock (Search Results)

**File**: `gui/dock.py`

### Results Display

```python
# Search results display
self.results_table_view = QTableWidget()
```

## Settings Dock (Connector Configuration)

**File**: `gui/settings_dock.py`

### Copernicus STAC Configuration

```python
# Copernicus STAC (Dataspace)
stac_group = QGroupBox("Copernicus STAC (Dataspace)")
self.copernicus_client_id_input = QLineEdit()
self.copernicus_client_secret_input = QLineEdit()
self.test_copernicus_stac_btn = QPushButton("Test Connection")
```

**Features:**
- **Test STAC Connection**: Tests OAuth2 with Copernicus Dataspace
- **Restore Defaults**: Reset to default configuration

---

# Proxy & VPN Handling

## Architecture

### 1. Qt Network Layer (Primary)

**File**: All modern connectors (`vantor.py`, `iceye_stac.py`, etc.)

```python
# Proxy automatically detected from KADAS settings (QGIS-based)
nam = QgsNetworkAccessManager.instance()
request = QNetworkRequest(QUrl(url))
reply = nam.get(request)
```

**Configuration in KADAS**:
- Settings → Options → Network → Proxy
- Plugin reads these settings automatically (inherited from QGIS platform)

### 2. Environment Variables (Fallback)

**File**: `plugin.py → _apply_proxy_settings()`

```python
def _apply_proxy_settings(self):
    """Propagate QGIS proxy settings to environment variables"""
    settings = QSettings()
    
    proxy_enabled = settings.value('/proxy/proxyEnabled', False, type=bool)
    if not proxy_enabled:
        return
    
    proxy_host = settings.value('/proxy/proxyHost', '', type=str)
    proxy_port = settings.value('/proxy/proxyPort', '', type=str)
    proxy_user = settings.value('/proxy/proxyUser', '', type=str)
    proxy_password = settings.value('/proxy/proxyPassword', '', type=str)
    
    # Build proxy URL
    if proxy_user and proxy_password:
        proxy_url = f"http://{proxy_user}:{proxy_password}@{proxy_host}:{proxy_port}"
    else:
        proxy_url = f"http://{proxy_host}:{proxy_port}"
    
    # Set environment variables
    os.environ['HTTP_PROXY'] = proxy_url
    os.environ['HTTPS_PROXY'] = proxy_url
```

### 3. VPN Detection

**File**: `plugin.py → _detect_vpn()`

```python
def _detect_vpn(self):
    """Detect VPN connection by checking for private network IPs"""
    try:
        import socket
        hostname = socket.gethostname()
        ip_address = socket.gethostbyname(hostname)
        
        # Check if IP is in private ranges
        if (ip_address.startswith('10.') or 
            ip_address.startswith('172.') or 
            ip_address.startswith('192.168.')):
            logger.info(f"VPN detected (private IP: {ip_address})")
            return True
    except:
        pass
    return False
```

## VPN with SSL Inspection

### Problem
Corporate VPNs use **SSL inspection** (man-in-the-middle):
- Intercepts HTTPS traffic
- Re-encrypts with corporate certificate
- Causes SSL verification failures in Python

### Solution
**Use Qt networking** → SSL handled by Qt, which:
- Respects system certificate store
- Works with corporate certificates
- No Python `ssl` module needed

---

# OpenSSL Configuration

## Problem

OpenSSL 3.0+ moved legacy cryptographic algorithms to a separate "legacy provider" that must be explicitly enabled. Without it, some proxy/VPN environments fail with:

```
OpenSSL 3.0's legacy provider failed to load
```

## Solution: Automatic Configuration

**File**: `__init__.py` (plugin entry point)

```python
import os

def classFactory(iface):
    # Set OpenSSL configuration
    plugin_dir = os.path.dirname(__file__)
    openssl_conf = os.path.join(plugin_dir, 'openssl.cnf')
    
    if os.path.exists(openssl_conf):
        os.environ['OPENSSL_CONF'] = openssl_conf
        logger.info(f"OpenSSL config set: {openssl_conf}")
    
    from .plugin import KadasAltairPlugin
    return KadasAltairPlugin(iface)
```

**File**: `openssl.cnf` (in plugin root)

```ini
openssl_conf = openssl_init

[openssl_init]
providers = provider_sect

[provider_sect]
default = default_sect
legacy = legacy_sect

[default_sect]
activate = 1

[legacy_sect]
activate = 1
```

This enables both default and legacy OpenSSL providers automatically when the plugin loads.

---

# SAR Connectors

## ICEYE SAR Open Data

**Catalog**: Static STAC catalog  
**Collections**: 3 organizational views (196 items total)  
**Structure**: `Root → Child Collections → Items`

```python
# Navigate hierarchy
def search(self, bbox, start_date, end_date, collections, limit):
    # 1. Fetch root catalog
    root_links = self._catalog.get('links', [])
    child_links = [l for l in root_links if l['rel'] == 'child']
    
    # 2. Fetch each child collection
    for coll_link in child_links:
        coll_data = self._http_get(coll_link['href'])
        
        # 3. Get item links
        item_links = [l for l in coll_data['links'] if l['rel'] == 'item']
        
        # 4. Fetch individual items
        for item_link in item_links:
            item_data = self._http_get(item_link['href'])
            
            # 5. Apply filters (bbox, dates)
            if self._item_matches_filters(item_data, bbox, start_date, end_date):
                items.append(item_data)
```

**Bbox Filtering**:
```python
def _item_matches_filters(self, item, bbox, start_date, end_date):
    """Check if item bbox overlaps search bbox"""
    item_bbox = item.get('bbox')  # [west, south, east, north]
    
    # Check for NO overlap (then exclude)
    no_overlap = (
        item_bbox[2] < bbox[0] or  # item east < filter west
        item_bbox[0] > bbox[2] or  # item west > filter east
        item_bbox[3] < bbox[1] or  # item north < filter south
        item_bbox[1] > bbox[3]     # item south > filter north
    )
    
    if no_overlap:
        logger.info(f"❌ EXCLUDING {item['id']}: bbox does not overlap")
        return False
    else:
        logger.info(f"✅ INCLUDING {item['id']}: bbox overlaps")
        return True
```

## Umbra SAR Open Data

**Catalog**: Recursive STAC (Year → Month → Day → Items)  
**Collections**: Dynamically generated by traversing hierarchy  
**Products**: GEC, SICD, SIDD, CPHD (GeoTIFF + NITF)

```python
# Recursive navigation
def get_collections(self):
    """Navigate year → month hierarchy"""
    for year_link in root_catalog['links']:
        year_data = self._http_get(year_link['href'])
        
        for month_link in year_data['links']:
            month_data = self._http_get(month_link['href'])
            
            # Count items in month
            item_count = len([l for l in month_data['links'] if l['rel'] == 'item'])
            
            collections.append({
                'id': f"{year}-{month}",
                'title': f"Umbra {year}-{month}",
                'asset_count': item_count
            })
```

## Capella SAR Open Data

**Catalog**: Multiple organization types  
**Collections**: ~1000 images organized by product/mode/use-case  
**Products**: GEO, GEC, SLC, SICD, SIDD, CPHD

**Organization Types**:
- `product`: By product type (GEO, GEC, SLC, etc.)
- `mode`: By imaging mode (spotlight, stripmap)
- `use-case`: By application (defense, disaster, commercial)
- `capital`: By geographic region
- `datetime`: By acquisition date
- `IEEE`: IEEE GRSS Data Fusion Contest

---

## Data Flow: Search Operation

```
User Input (dock.py)
    │
    ├─ Bbox: [west, south, east, north] (EPSG:4326)
    ├─ Date Range: start_date, end_date
    ├─ Collection: collection_id
    └─ Filters: cloud_cover, etc.
    │
    ▼
ConnectorManager.search()
    │
    ├─ Route to active connector
    ├─ Execute connector-specific search
    └─ Standardize results (STAC-like format)
    │
    ▼
Connector.search() (e.g., ICEYE)
    │
    ├─ Fetch catalog
    ├─ Navigate hierarchy
    ├─ Fetch items
    ├─ Apply bbox filter
    ├─ Apply date filter
    └─ Return matching items
    │
    ▼
SearchTask (QgsTask)
    │
    ├─ Run in background thread
    ├─ Keep UI responsive
    └─ Signal completion
    │
    ▼
dock.py → _populate_results_table()
    │
    ├─ Display results in table
    ├─ Show footprints on map
    └─ Enable "Load Layer" button
```

---

## Testing & Debugging

### Log Viewer

**Access**: Plugins → Altair → Settings → Open Log Viewer

**Log Levels**:
- `INFO`: Normal operations
- `WARNING`: Non-critical issues
- `ERROR`: Failed operations
- `DEBUG`: Detailed diagnostic info

**Log Location**:
- Windows: `%APPDATA%\.kadas\altair_plugin.log`
- Linux: `~/.kadas/altair_plugin.log`

### Network Debugging

**Enable detailed QGIS network logs**:
```python
QgsNetworkAccessManager.instance().setProperty('logLevel', 'debug')
```

**Check proxy settings**:
```python
from PyQt5.QtCore import QSettings
settings = QSettings()
proxy_enabled = settings.value('/proxy/proxyEnabled', False, type=bool)
proxy_host = settings.value('/proxy/proxyHost', '', type=str)
print(f"Proxy: {proxy_enabled}, Host: {proxy_host}")
```

---

## Best Practices

### For Connector Development

1. ✅ **Inherit from BaseConnector**
2. ✅ **Use QgsNetworkAccessManager** for all HTTP requests
3. ✅ **Implement all abstract methods** (authenticate, get_collections, search)
4. ✅ **Return STAC-like results** (id, bbox, properties, assets)
5. ✅ **Add detailed logging** (INFO for operations, DEBUG for details)
6. ✅ **Handle errors gracefully** (return empty list, don't crash)
7. ✅ **Register in ConnectorManager** (`plugin.py`)

### For Network Operations

1. ✅ **Use Qt networking** (not `requests` library)
2. ✅ **Set timeouts** (default: 30s for catalog, 20s for search)
3. ✅ **Handle rate limits** (add delays between requests if needed)
4. ✅ **Cache responses** where appropriate
5. ✅ **Log network errors** with full context

### For Performance

1. ✅ **Use parallel loading** for independent operations
2. ✅ **Cache expensive operations** (5-minute TTL for collections)
3. ✅ **Limit result counts** (default: 100, max: 10000)
4. ✅ **Stream large files** (use GDAL vsicurl for COGs)
5. ✅ **Paginate results** when possible

---

## References

- **STAC Specification**: https://stacspec.org/
- **KADAS Albireo**: https://www.kadas-albireo.ch/
- **QGIS API** (underlying platform): https://qgis.org/pyqgis/
- **Qt Network**: https://doc.qt.io/qt-5/qtnetwork-index.html
- **GDAL vsicurl**: https://gdal.org/user/virtual_file_systems.html#vsicurl-http-https-ftp-files-random-access

---

**Version**: 0.2.0  
**Platform**: KADAS Albireo 2.3+ (QGIS 3.x-based)  
**Last Updated**: 2026-02-25
