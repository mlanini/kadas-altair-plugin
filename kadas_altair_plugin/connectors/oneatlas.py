"""OneAtlas connector stub inspired by airbusgeo/oneatlas-qgis-plugin

This module provides stub implementations and minimal request scaffolding.
Uses QgsNetworkAccessManager for SSL/proxy handling instead of requests.
"""

import json
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlencode
from base64 import b64encode

try:
    from qgis.PyQt.QtCore import QEventLoop, QTimer, QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest
    from qgis.core import QgsNetworkAccessManager
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False

from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.oneatlas')

class OneAtlasConnector(ConnectorBase):
    """Connector that implements OAuth2 client_credentials for OneAtlas.

    Real plugin should retrieve client_id and client_secret from secure
    storage; this method supports a `verify` boolean which if True will
    perform a network token request to the authorization server. If False,
    authentication succeeds locally when credentials include a token.
    """

    TOKEN_URL = 'https://authentication.oneatlas.airbus.com/oauth/token'
    timeout_auth: float = 10.0

    def __init__(self):
        super().__init__()
        self.authenticated = False
        self.token: Optional[str] = None

    def authenticate(self, credentials: dict, verify: bool = True) -> bool:
        """Authenticate using client_id/client_secret or provided token.

        credentials: dict with one of:
          - token: pre-obtained access token
          - client_id and client_secret
        verify: if True perform network request to fetch token
        """
        if 'token' in credentials and credentials['token']:
            self.token = credentials['token']
            self.authenticated = True
            logger.debug('OneAtlas: authenticated with provided token')
            return True

        client_id = credentials.get('client_id')
        client_secret = credentials.get('client_secret')
        if not client_id or not client_secret:
            self.authenticated = False
            logger.warning('OneAtlas: missing client_id or client_secret')
            return False

        if not verify:
            # Accept credentials locally but don't test network
            self.token = f'client:{client_id}'
            self.authenticated = True
            logger.debug('OneAtlas: offline authentication accepted')
            return True

        # Check QGIS availability
        if not QGIS_AVAILABLE:
            logger.error('OneAtlas: QGIS network manager not available')
            self.authenticated = False
            return False

        # Perform OAuth2 client credentials grant using QgsNetworkAccessManager
        try:
            logger.debug('OneAtlas: requesting OAuth2 token via QGIS network manager...')
            
            # Prepare OAuth2 request with HTTP Basic authentication
            # Basic auth: base64(client_id:client_secret)
            credentials_str = f"{client_id}:{client_secret}"
            b64_credentials = b64encode(credentials_str.encode('utf-8')).decode('ascii')
            
            # Prepare form data
            data = urlencode({'grant_type': 'client_credentials'}).encode('utf-8')
            
            # Create network request
            request = QNetworkRequest(QUrl(self.TOKEN_URL))
            request.setHeader(QNetworkRequest.ContentTypeHeader, 'application/x-www-form-urlencoded')
            request.setRawHeader(b'Authorization', f'Basic {b64_credentials}'.encode('utf-8'))
            request.setRawHeader(b'Accept', b'application/json')
            
            # Use QGIS network manager
            nam = QgsNetworkAccessManager.instance()
            reply = nam.post(request, data)
            
            # Event loop with timeout
            loop = QEventLoop()
            reply.finished.connect(loop.quit)
            
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(int(self.timeout_auth * 1000))
            
            loop.exec_()
            
            # Check timeout
            if not reply.isFinished():
                reply.abort()
                logger.error(f'OneAtlas: authentication timeout (>{self.timeout_auth}s)')
                self.authenticated = False
                return False
            
            # Get status code
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            
            # Check network errors
            if reply.error():
                error_code = reply.error()
                error_msg = reply.errorString()
                logger.error(f'OneAtlas: network error ({error_code}): {error_msg} - HTTP {status_code}')
                self.authenticated = False
                reply.deleteLater()
                return False
            
            # Check HTTP status code
            if status_code and status_code >= 400:
                logger.error(f'OneAtlas: HTTP {status_code} error during authentication')
                response_data = reply.readAll().data().decode('utf-8', errors='ignore')
                if response_data:
                    logger.debug(f'OneAtlas: Error response: {response_data[:200]}')
                self.authenticated = False
                reply.deleteLater()
                return False
            
            # Parse successful response
            response_data = reply.readAll().data().decode('utf-8')
            reply.deleteLater()
            
            data = json.loads(response_data)
            access_token = data.get('access_token')
            
            if access_token:
                self.token = access_token
                self.authenticated = True
                logger.info('OneAtlas: successfully authenticated')
                return True
            else:
                logger.error('OneAtlas: no access_token in response')
                self.authenticated = False
                return False
                
        except json.JSONDecodeError as e:
            logger.error(f'OneAtlas: failed to parse token response as JSON: {e}')
            self.authenticated = False
            return False
        except Exception as e:
            logger.error(f'OneAtlas: authentication failed: {e}')
            self.authenticated = False
            return False

    def is_authenticated(self) -> bool:
        """Check if connector is authenticated"""
        return self.authenticated

    def get_collections(self) -> List[Dict[str, Any]]:
        """Get available collections (OneAtlas products)"""
        if not self.authenticated:
            return []
        
        # OneAtlas has different product types
        return [
            {'id': 'spot', 'title': 'SPOT 6/7', 'description': '1.5m resolution optical imagery'},
            {'id': 'pleiades', 'title': 'Pléiades', 'description': '0.5m resolution optical imagery'},
            {'id': 'pleiades-neo', 'title': 'Pléiades Neo', 'description': '0.3m resolution optical imagery'},
        ]

    def search(self, bbox: Optional[List[float]] = None, start_date: Optional[str] = None, 
               end_date: Optional[str] = None, max_cloud_cover: int = 100, 
               collection: Optional[str] = None, limit: int = 10, **kwargs) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Search OneAtlas imagery
        
        Args:
            bbox: Bounding box [minx, miny, maxx, maxy] in EPSG:4326
            start_date: Start date (ISO format)
            end_date: End date (ISO format)
            max_cloud_cover: Maximum cloud coverage percentage
            collection: Collection ID (spot, pleiades, pleiades-neo)
            limit: Maximum number of results
            
        Returns:
            Tuple of (items list, next_token)
        """
        if not self.authenticated:
            return [], None
        
        # In a full implementation, call OneAtlas search API using self.token
        # This is a stub returning sample data
        results = [{
            'id': f'oneatlas-{collection or "default"}-1',
            'type': 'Feature',
            'geometry': {
                'type': 'Polygon',
                'coordinates': [[
                    [bbox[0] if bbox else 0, bbox[1] if bbox else 0],
                    [bbox[2] if bbox else 1, bbox[1] if bbox else 0],
                    [bbox[2] if bbox else 1, bbox[3] if bbox else 1],
                    [bbox[0] if bbox else 0, bbox[3] if bbox else 1],
                    [bbox[0] if bbox else 0, bbox[1] if bbox else 0]
                ]]
            } if bbox else None,
            'bbox': bbox,
            'properties': {
                'datetime': start_date or '2024-01-01T00:00:00Z',
                'platform': collection or 'OneAtlas',
                'constellation': 'oneatlas',
                'eo:cloud_cover': 10,
                'gsd': 0.5,
                'collection': collection or 'pleiades'
            },
            'assets': {
                'thumbnail': {'href': f'https://oneatlas.example.com/thumb/{collection or "default"}.jpg', 'type': 'image/jpeg'},
                'visual': {'href': f'https://oneatlas.example.com/visual/{collection or "default"}.tif', 'type': 'image/tiff'}
            }
        }]
        
        return results, None

    def get_tile_url(self, result: dict, z: int, x: int, y: int) -> str:
        return f'https://oneatlas.example.com/tiles/{result.get("id")}/{z}/{x}/{y}.png'
