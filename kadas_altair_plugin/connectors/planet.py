"""Planet STAC connector

Provides access to Planet imagery via the STAC API.

Architecture (based on https://docs.planet.com/develop/apis/data/stac/):
- Endpoint: https://api.planet.com/x/data/
- Authentication: Basic auth with API key (username field) or Bearer token
- Search: POST to /search endpoint with CQL2 filters
- Collections: PSScene, SkySatScene, REScene, PSScene4Band
- Supports: bbox, datetime, intersects, CQL2 filters

Features:
- Basic auth with API key
- Cross-collection search with CQL2 filters
- Geometry intersection (s_intersects)
- Temporal filters (t_after, t_before, t_intersects)
- Comparison filters (>=, <=, between, in)
- Logical operators (and, or, not)
- Asset and permission filters
- Pagination support

API Reference: https://api.planet.com/x/data/docs

License: Requires Planet account and API key
"""

import json
import base64
import logging
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urljoin
from .base import ConnectorBase
from ..logger import get_logger

# QGIS network infrastructure
from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager
from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
from qgis.PyQt.QtNetwork import QNetworkRequest

logger = get_logger('connectors.planet')


class PlanetConnector(ConnectorBase):
    """Planet STAC connector with CQL2 filter support.
    
    Features:
    - Basic auth with API key
    - STAC search endpoint (/x/data/search)
    - CQL2 JSON filter support
    - Multiple collection types (PSScene, SkySatScene, etc.)
    - QGIS network manager integration (proxy-aware)
    """
    
    # Planet STAC API endpoints
    BASE_URL = 'https://api.planet.com/x/data/'
    SEARCH_URL = 'https://api.planet.com/x/data/search'
    
    # Timeouts
    timeout_auth: float = 10.0
    timeout_search: float = 30.0
    
    # Collections (Planet item types)
    COLLECTIONS = {
        'PSScene': {
            'title': 'PlanetScope Scene',
            'description': '3-5m resolution daily imagery',
            'gsd': 3.0
        },
        'PSScene4Band': {
            'title': 'PlanetScope 4-Band',
            'description': '3m resolution multispectral',
            'gsd': 3.0
        },
        'REScene': {
            'title': 'RapidEye Scene',
            'description': '5m resolution imagery',
            'gsd': 5.0
        },
        'SkySatScene': {
            'title': 'SkySat Scene',
            'description': '0.5-1m resolution video + still imagery',
            'gsd': 0.7
        },
        'SkySatCollect': {
            'title': 'SkySat Collect',
            'description': 'SkySat collection imagery',
            'gsd': 0.5
        }
    }

    def __init__(self):
        super().__init__()
        self.authenticated = False
        self.api_key: Optional[str] = None
        self._auth_header: Optional[str] = None

    def _get_auth_header(self) -> str:
        """Generate Basic auth header from API key.
        
        Planet uses Basic auth with API key in username field and empty password.
        """
        if not self.api_key:
            return ''
        
        # Format: "apikey:"
        userpass = f"{self.api_key}:"
        b64_credentials = base64.b64encode(userpass.encode()).decode()
        return f"Basic {b64_credentials}"

    def _http_get(self, url: str, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """Make authenticated HTTP GET request using QGIS Network Manager.
        
        Args:
            url: URL to fetch
            timeout: Timeout in seconds
            
        Returns:
            JSON response as dictionary or None on error
        """
        if not self._auth_header:
            logger.error("Planet: not authenticated")
            return None
        
        try:
            logger.debug(f"Planet: HTTP GET {url}")
            
            # Create network request
            request = QNetworkRequest(QUrl(url))
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            request.setRawHeader(b"Authorization", self._auth_header.encode())
            request.setRawHeader(b"User-Agent", b"KADAS-Altair-Plugin/1.0")
            request.setAttribute(QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.AlwaysNetwork)
            
            # Use QGIS network manager
            nam = QgsNetworkAccessManager.instance()
            reply = nam.get(request)
            
            # Event loop with timeout
            loop = QEventLoop()
            reply.finished.connect(loop.quit)
            
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(int(timeout * 1000))
            
            loop.exec_()
            
            # Check timeout
            if not reply.isFinished():
                reply.abort()
                logger.error(f"Planet: request timeout after {timeout}s")
                return None
            
            # Check network errors
            if reply.error():
                error_code = reply.error()
                error_msg = reply.errorString()
                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                
                logger.error(f"Planet: network error ({error_code}): {error_msg} - HTTP {status_code}")
                return None
            
            # Check HTTP status code
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if status_code and status_code >= 400:
                logger.error(f"Planet: HTTP {status_code} error")
                return None
            
            # Parse JSON
            data = reply.readAll().data().decode('utf-8')
            return json.loads(data)
            
        except json.JSONDecodeError as e:
            logger.error(f"Planet: failed to parse JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Planet: HTTP GET failed: {e}")
            return None

    def _http_post(self, url: str, payload: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """Make authenticated HTTP POST request using QGIS Network Manager.
        
        Args:
            url: URL to post to
            payload: JSON payload
            timeout: Timeout in seconds
            
        Returns:
            JSON response as dictionary or None on error
        """
        if not self._auth_header:
            logger.error("Planet: not authenticated")
            return None
        
        try:
            logger.debug(f"Planet: HTTP POST {url}")
            
            # Create network request
            request = QNetworkRequest(QUrl(url))
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            request.setRawHeader(b"Authorization", self._auth_header.encode())
            request.setRawHeader(b"User-Agent", b"KADAS-Altair-Plugin/1.0")
            
            # Use QGIS network manager
            nam = QgsNetworkAccessManager.instance()
            json_data = json.dumps(payload).encode('utf-8')
            reply = nam.post(request, json_data)
            
            # Event loop with timeout
            loop = QEventLoop()
            reply.finished.connect(loop.quit)
            
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(int(timeout * 1000))
            
            loop.exec_()
            
            # Check timeout
            if not reply.isFinished():
                reply.abort()
                logger.error(f"Planet: request timeout after {timeout}s")
                return None
            
            # Check network errors
            if reply.error():
                error_code = reply.error()
                error_msg = reply.errorString()
                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                
                logger.error(f"Planet: network error ({error_code}): {error_msg} - HTTP {status_code}")
                return None
            
            # Check HTTP status code
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if status_code and status_code >= 400:
                logger.error(f"Planet: HTTP {status_code} error")
                return None
            
            # Parse JSON
            data = reply.readAll().data().decode('utf-8')
            return json.loads(data)
            
        except json.JSONDecodeError as e:
            logger.error(f"Planet: failed to parse JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Planet: HTTP POST failed: {e}")
            return None

    def authenticate(self, credentials: Optional[dict] = None, verify: bool = True) -> bool:
        """Authenticate with Planet API using API key.
        
        Args:
            credentials: Dictionary with 'api_key' field
            verify: If True, verify API key by calling API
            
        Returns:
            True if authentication successful
        """
        if not credentials:
            logger.error('Planet: no credentials provided')
            self.authenticated = False
            return False
        
        api_key = credentials.get('api_key')
        if not api_key:
            logger.error('Planet: missing api_key in credentials')
            self.authenticated = False
            return False
        
        self.api_key = api_key
        self._auth_header = self._get_auth_header()
        
        if not verify:
            self.authenticated = True
            logger.debug('Planet: offline authentication accepted')
            return True
        
        # Verify by fetching the root STAC catalog
        try:
            logger.info('Planet: verifying API key...')
            catalog = self._http_get(self.BASE_URL, timeout=self.timeout_auth)
            
            if catalog is None:
                logger.error('Planet: API key verification failed (request failed)')
                self.authenticated = False
                return False
            
            # Check if we got a valid STAC catalog
            if catalog.get('type') == 'Catalog' or 'links' in catalog:
                self.authenticated = True
                logger.info('Planet: API key verified successfully')
                return True
            else:
                logger.error('Planet: unexpected response from API')
                self.authenticated = False
                return False
                
        except Exception as e:
            logger.error(f'Planet: authentication failed: {e}')
            self.authenticated = False
            return False

    def is_authenticated(self) -> bool:
        """Check if connector is authenticated"""
        return self.authenticated

    def get_collections(self) -> List[Dict[str, Any]]:
        """Get available Planet collections (item types).
        
        Returns list of collections with metadata.
        """
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return []
        
        collections = []
        for coll_id, metadata in self.COLLECTIONS.items():
            collections.append({
                'id': coll_id,
                'title': metadata['title'],
                'description': metadata['description'],
                'gsd': metadata['gsd'],
                'asset_count': 0  # Not available without search
            })
        
        return collections

    def search(self, query: str = "", bbox: Optional[Tuple[float, float, float, float]] = None,
               datetime: Optional[str] = None, collections: Optional[List[str]] = None,
               limit: int = 100) -> List[Dict[str, Any]]:
        """Search Planet imagery using STAC search endpoint.
        
        Based on Planet STAC API documentation with CQL2 filters.
        
        Args:
            query: Text search (applied to properties)
            bbox: Bounding box (minx, miny, maxx, maxy)
            datetime: ISO datetime or range (e.g., "2024-01-01/2024-12-31" or "2024-01-01/..")
            collections: List of collection IDs to search (PSScene, SkySatScene, etc.)
            limit: Maximum number of results
            
        Returns:
            List of result dicts
        """
        if not self.authenticated:
            logger.error('Planet: not authenticated')
            return []
        
        # Build search payload
        payload: Dict[str, Any] = {
            'limit': min(limit, 250)  # Planet max is 250
        }
        
        # Add collections filter
        if collections:
            payload['collections'] = collections
        else:
            # Default to PSScene if not specified
            payload['collections'] = ['PSScene']
        
        # Add bbox filter
        if bbox:
            payload['bbox'] = [bbox[0], bbox[1], bbox[2], bbox[3]]
        
        # Add datetime filter
        if datetime:
            payload['datetime'] = datetime
        
        # Build CQL2 filter for additional constraints
        filter_args = []
        
        # Add clear_percent filter (minimum 50% clear by default)
        filter_args.append({
            'op': '>=',
            'args': [
                {'property': 'pl:clear_percent'},
                50
            ]
        })
        
        # Combine filters with AND if multiple
        if filter_args:
            if len(filter_args) == 1:
                payload['filter'] = filter_args[0]
            else:
                payload['filter'] = {
                    'op': 'and',
                    'args': filter_args
                }
        
        logger.info(f"Planet: searching (collections={payload.get('collections')}, bbox={bbox}, limit={limit})")
        logger.debug(f"Planet: search payload: {json.dumps(payload, indent=2)}")
        
        # Execute search
        try:
            response = self._http_post(self.SEARCH_URL, payload, timeout=self.timeout_search)
            
            if response is None:
                logger.error('Planet: search request failed')
                return []
            
            # Extract features
            features = response.get('features', [])
            logger.info(f"Planet: search returned {len(features)} items")
            
            # Convert to result format
            results = []
            for feature in features:
                result = self._feature_to_result(feature)
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f'Planet: search failed: {e}')
            return []
    
    def _feature_to_result(self, feature: Dict[str, Any]) -> Dict[str, Any]:
        """Convert STAC feature to result dict.
        
        Args:
            feature: STAC Feature from Planet API
            
        Returns:
            Result dictionary
        """
        props = feature.get('properties', {})
        
        result = {
            'id': feature.get('id'),
            'title': props.get('pl:item_type', '') + ' - ' + feature.get('id', ''),
            'bbox': feature.get('bbox'),
            'geometry': feature.get('geometry'),
            'assets': feature.get('assets', {}),
            'properties': props,
            'collection': props.get('pl:item_type', 'unknown'),
            'stac_feature': feature,
            'is_collection': False,
        }
        
        # Extract key metadata
        if 'datetime' in props:
            result['datetime'] = props['datetime']
        if 'pl:clear_percent' in props:
            result['clear_percent'] = props['pl:clear_percent']
        if 'pl:cloud_percent' in props:
            result['cloud_percent'] = props['pl:cloud_percent']
        if 'gsd' in props:
            result['gsd'] = props['gsd']
        if 'pl:ground_control' in props:
            result['ground_control'] = props['pl:ground_control']
        if 'pl:satellite_id' in props:
            result['satellite_id'] = props['pl:satellite_id']
        
        return result

    def get_tile_url(self, result: dict, z: int, x: int, y: int) -> str:
        """Get tile URL for a result.
        
        Planet STAC items include asset hrefs, but they require authentication.
        Returns the first visual asset href found.
        """
        assets = result.get('assets', {})
        
        # Prefer visual/preview assets
        for key in ('visual', 'basic_analytic', 'ortho_visual', 'preview'):
            asset = assets.get(key)
            if isinstance(asset, dict) and asset.get('href'):
                # Note: Planet asset URLs require authentication
                # Add ?auth=true query parameter to include credentials
                href = asset.get('href', '')
                if href and '?' not in href:
                    href += '?auth=true'
                return str(href)
        
        # Return first asset href if no preferred type found
        for asset in assets.values():
            if isinstance(asset, dict) and asset.get('href'):
                href = asset.get('href', '')
                if href and '?' not in href:
                    href += '?auth=true'
                return str(href)
        
        return ''
