# Contributing to KADAS Altair

Thank you for your interest in contributing! This document provides guidelines for development.

## 🚀 Quick Start

### Development Setup

```bash
# Clone repository
git clone https://github.com/mlanini/kadas-altair.git
cd kadas-altair

# Install to QGIS plugins directory
# Windows
Copy-Item -Recurse kadas_altair_plugin "$env:APPDATA\Kadas\KadasXY\profiles\default\python\plugins\"

# Linux/macOS
cp -r kadas_altair_plugin ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/

# Reload plugin in QGIS/KADAS
# Plugin → Plugin Manager → Installed → Reload plugin
```

### Directory Structure

```
kadas_altair_plugin/
├── connectors/          # Data source implementations
│   ├── base.py         # Base connector class
│   ├── copernicus.py   # Copernicus Dataspace (OAuth2 + STAC)
│   ├── iceye_stac.py   # ICEYE SAR Open Data
│   ├── umbra_stac.py   # Umbra SAR Open Data
│   ├── capella_stac.py # Capella SAR Open Data
│   ├── vantor_stac.py  # Maxar/Vantor STAC
│   ├── oneatlas.py     # OneAtlas (stub)
│   └── planet.py       # Planet (stub)
├── gui/                # User interface
│   ├── dock.py         # Main panel
│   ├── settings_dock.py # Settings panel
│   └── footprint_tool.py # Map interaction
├── utilities/          # Helper modules
│   └── proxy_handler.py # Network configuration
├── secrets/            # Credential management
│   └── secure_storage.py
└── logger.py           # Logging system
```

## 🔧 Adding a New Connector

### 1. Create Connector File

Create `kadas_altair_plugin/connectors/mynewsource.py`:

```python
"""MyNewSource connector for satellite imagery"""

import json
from typing import Optional, List, Dict, Tuple

try:
    from qgis.PyQt.QtCore import QEventLoop, QTimer, QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest
    from qgis.core import QgsNetworkAccessManager
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False

from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.mynewsource')


class MyNewSourceConnector(ConnectorBase):
    """Connector for MyNewSource satellite data"""
    
    API_URL = 'https://api.mynewsource.com/v1'
    timeout_auth = 20.0
    timeout_search = 30.0
    
    def __init__(self):
        super().__init__()
        self._authenticated = False
        self._access_token = None
    
    def authenticate(self, credentials: dict, verify: bool = True) -> bool:
        """Authenticate with API
        
        Args:
            credentials: dict with 'api_key' or 'client_id'/'client_secret'
            verify: whether to verify credentials with API
        """
        # Implementation here
        self._authenticated = True
        return True
    
    def get_collections(self) -> List[Dict]:
        """Get available collections
        
        Returns:
            List of collection dicts with 'id', 'title', 'description'
        """
        if not self._authenticated:
            return []
        
        # Use QgsNetworkAccessManager for requests
        # See existing connectors for examples
        return [
            {
                'id': 'collection-1',
                'title': 'My Collection',
                'description': 'Example collection'
            }
        ]
    
    def search(self, **kwargs) -> List[Dict]:
        """Search for imagery
        
        Args:
            bbox: [minx, miny, maxx, maxy] in EPSG:4326
            start_date: ISO format date string
            end_date: ISO format date string
            collection: collection ID
            limit: max results
        
        Returns:
            List of result dicts (GeoJSON-like features)
        """
        if not self._authenticated:
            return []
        
        # Implement search using QgsNetworkAccessManager
        return []
    
    def get_asset_urls(self, result: dict) -> Dict[str, str]:
        """Get asset URLs from search result
        
        Args:
            result: search result dict
        
        Returns:
            Dict mapping asset type to URL (e.g., {'visual': 'https://...'})
        """
        return result.get('assets', {})
```

### 2. Register Connector

Edit `kadas_altair_plugin/connectors/__init__.py`:

```python
from .mynewsource import MyNewSourceConnector

__all__ = [
    'ConnectorBase',
    # ... existing connectors ...
    'MyNewSourceConnector',
]
```

Edit `kadas_altair_plugin/connectors/connector_manager.py`:

```python
class ConnectorType(Enum):
    # ... existing types ...
    MYNEWSOURCE = "mynewsource"
```

### 3. Integrate in UI

Edit `kadas_altair_plugin/gui/dock.py`:

```python
from ..connectors import MyNewSourceConnector
from ..connectors.connector_manager import ConnectorType

# In __init__():
self.connector_manager.register(
    ConnectorType.MYNEWSOURCE,
    MyNewSourceConnector,
    "MyNewSource",
    ConnectorCapability.BBOX_SEARCH | ConnectorCapability.DATE_RANGE
)
```

### 4. Test Connector

```python
# Test authentication
connector = MyNewSourceConnector()
success = connector.authenticate({'api_key': 'test_key'})
assert success

# Test collections
collections = connector.get_collections()
assert len(collections) > 0

# Test search
results = connector.search(
    bbox=[7.0, 46.0, 8.0, 47.0],
    start_date='2024-01-01',
    end_date='2024-12-31'
)
```

## 📐 Code Standards

### Python Style

- **PEP 8** compliance
- **Type hints** for function signatures
- **Docstrings** for all public methods (Google style)
- **English** for code and comments

### Network Requests

**✅ ALWAYS use QgsNetworkAccessManager:**

```python
from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import QEventLoop, QTimer, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

def make_request(url, timeout=30.0):
    """Make HTTP request using QGIS network manager"""
    request = QNetworkRequest(QUrl(url))
    
    nam = QgsNetworkAccessManager.instance()
    reply = nam.get(request)
    
    loop = QEventLoop()
    reply.finished.connect(loop.quit)
    
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(int(timeout * 1000))
    
    loop.exec_()
    
    if not reply.isFinished():
        reply.abort()
        raise TimeoutError(f"Request timeout: {url}")
    
    if reply.error():
        raise ConnectionError(f"Network error: {reply.errorString()}")
    
    data = reply.readAll().data().decode('utf-8')
    reply.deleteLater()
    
    return data
```

**❌ NEVER use requests library:**

```python
# ❌ WRONG - SSL issues, no proxy support
import requests
response = requests.get(url)
```

### Logging

```python
from ..logger import get_logger

logger = get_logger('module.name')

logger.debug('Detailed diagnostic information')
logger.info('Important state changes')
logger.warning('Recoverable issues')
logger.error('Errors that affect functionality')
```

### Error Handling

```python
def search(self, **kwargs):
    """Search with comprehensive error handling"""
    try:
        # Validate inputs
        bbox = kwargs.get('bbox')
        if not bbox or len(bbox) != 4:
            logger.error('Invalid bbox parameter')
            return []
        
        # Make request
        results = self._make_request(...)
        
        logger.info(f'Found {len(results)} results')
        return results
        
    except ConnectionError as e:
        logger.error(f'Network error: {e}')
        return []
    except json.JSONDecodeError as e:
        logger.error(f'Invalid JSON response: {e}')
        return []
    except Exception as e:
        logger.error(f'Unexpected error: {e}')
        import traceback
        logger.debug(traceback.format_exc())
        return []
```

## 🧪 Testing

### Manual Testing

1. **Install** plugin in QGIS/KADAS
2. **Open** Altair panel
3. **Select** your connector
4. **Test** authentication
5. **Test** collection loading
6. **Test** search with various parameters
7. **Test** layer loading

### Syntax Verification

```powershell
# Compile all Python files
python -m py_compile kadas_altair_plugin/connectors/mynewsource.py
```

### Network Verification

```powershell
# Check all connectors use QgsNetworkAccessManager
python verify_network_migration.py
```

## 📝 Documentation

### Connector Documentation

Create `kadas_altair_plugin/connectors/MYNEWSOURCE_README.md`:

```markdown
# MyNewSource Connector

## Overview

MyNewSource provides [description of data source].

## Authentication

[How to get credentials, if needed]

## Collections

- **Collection 1**: Description
- **Collection 2**: Description

## Search Parameters

- `bbox`: Bounding box [minx, miny, maxx, maxy]
- `start_date`: Start date (ISO format)
- `end_date`: End date (ISO format)
- `collection`: Collection ID

## Example Usage

[Code examples]

## References

- API Documentation: https://...
- Data License: [License info]
```

## 🔄 Pull Request Process

### Before Submitting

1. ✅ **Test** connector thoroughly
2. ✅ **Verify** no `requests` library usage
3. ✅ **Check** syntax with `py_compile`
4. ✅ **Update** metadata if adding collections
5. ✅ **Document** in connector README
6. ✅ **Run** `verify_network_migration.py`

### PR Checklist

- [ ] Code follows PEP 8 style
- [ ] Uses QgsNetworkAccessManager (not requests)
- [ ] Includes comprehensive error handling
- [ ] Has docstrings for all public methods
- [ ] Includes connector README documentation
- [ ] Tested in QGIS/KADAS environment
- [ ] No syntax errors (`py_compile` passes)
- [ ] Updated metadata.txt if needed

### Commit Messages

```
feat(connectors): add MyNewSource connector

- Implements STAC API v1.0.0 support
- Adds OAuth2 authentication
- Supports 10+ collections
- Uses QgsNetworkAccessManager for network requests

Closes #123
```

Format: `type(scope): description`

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `refactor`: Code refactoring
- `test`: Test additions
- `chore`: Maintenance

## 🐛 Bug Reports

When reporting bugs, include:

1. **QGIS/KADAS version**
2. **Plugin version**
3. **Connector** being used
4. **Steps to reproduce**
5. **Expected behavior**
6. **Actual behavior**
7. **Log output** (from log viewer)

## 💡 Feature Requests

When requesting features:

1. **Use case** - What are you trying to achieve?
2. **Current limitation** - What prevents you now?
3. **Proposed solution** - How should it work?
4. **Alternatives** - What workarounds exist?

## 📚 Resources

- **QGIS API**: https://qgis.org/pyqgis/
- **STAC Spec**: https://stacspec.org/
- **Qt Network**: https://doc.qt.io/qt-5/qtnetwork-index.html
- **Vantor Plugin**: https://github.com/mlanini/kadas-vantor-plugin (reference implementation)

## � Testing

### Test Scripts

The `test/` directory contains standalone test scripts for debugging connectors independently of QGIS.

#### Available Tests

**1. Copernicus Authentication (`test_copernicus_auth.py`)**
```bash
python test/test_copernicus_auth.py <client_id> <client_secret>
```
- Tests OAuth2 token generation
- Validates Copernicus credentials
- Diagnoses authentication issues

**2. Umbra Structure Exploration (`test_umbra_structure.py`)**
```bash
python test/test_umbra_structure.py
```
- Explores Umbra STAC catalog hierarchy
- Verifies year → month → day navigation
- Inspects item metadata and assets

**3. Vantor Search (`test_vantor_search.py`)**
```bash
python test/test_vantor_search.py
```
- Tests Maxar Open Data STAC search
- Validates event collection navigation
- Verifies subcollection hierarchy

**4. Network Connectivity (`test_network_connectivity.py`)**
```bash
python test/test_network_connectivity.py
```
- Tests proxy and VPN compatibility
- Verifies QgsNetworkAccessManager integration
- Tests all plugin data sources
- Validates GeoJSON parsing

Expected output:
```
================================================================================
  Test 1: Basic Connectivity (No Proxy) - ✅ PASS
  Test 2: Connectivity with KADAS Proxy - ✅ PASS
  Test 3: Multiple Endpoints - ✅ PASS
  Test 4: GeoJSON Parsing - ✅ PASS

✅ Network connectivity is working!
```

**5. Network Migration Verification (`verify_network_migration.py`)**
```bash
python verify_network_migration.py
```
- Scans all connector files for `requests` library usage
- Validates migration to QgsNetworkAccessManager
- Checks SSL/proxy compatibility

### Running Tests

**From KADAS Python Console:**
```python
import subprocess
subprocess.run([
    "C:/Program Files/QGIS 3.40.7/apps/Python312/python.exe",
    "c:/path/to/kadas-altair-plugin/test/test_network_connectivity.py"
])
```

**From Terminal (Windows):**
```powershell
cd C:\tmp\kadas-plugins\kadas-altair-plugin\test
& "C:\Program Files\QGIS 3.40.7\apps\Python312\python.exe" test_network_connectivity.py
```

**From Terminal (Linux/macOS):**
```bash
cd /path/to/kadas-altair-plugin/test
python3 test_network_connectivity.py
```

### Test Requirements

All test scripts require:
- Python 3.8+
- `requests` library (for HTTP requests)

Install dependencies:
```bash
pip install requests
```

### Test Troubleshooting

**SSL Errors:**
```bash
# Windows: Install certificates
pip install --upgrade certifi

# Linux: Update CA certificates
sudo update-ca-certificates
```

**Proxy Issues:**
```bash
# Set proxy environment variables
set HTTP_PROXY=http://proxy.company.com:8080
set HTTPS_PROXY=http://proxy.company.com:8080
```

**Timeout Errors:**
```python
# Increase timeout in scripts
response = requests.post(url, data=data, timeout=60)  # 60 seconds
```

### Adding New Tests

When adding connectors, create corresponding test scripts:

**Test Template:**
```python
"""Test <ConnectorName> functionality"""
import requests
import json

def test_connector():
    """Test connector logic"""
    url = "https://api.example.com/catalog.json"
    
    response = requests.get(url, timeout=10)
    data = response.json()
    
    print(f"Catalog ID: {data.get('id')}")
    print(f"Items: {len(data.get('links', []))}")

if __name__ == '__main__':
    test_connector()
```

Save as `test/<connector_name>.py` and document in this section.

---

## �🤝 Getting Help

- **GitHub Issues**: https://github.com/mlanini/kadas-altair/issues
- **Email**: mlanini(at)proton(dot)me

## 📄 License

By contributing, you agree that your contributions will be licensed under GPL-2.0.

---

**Thank you for contributing to KADAS Altair!** 🎉
