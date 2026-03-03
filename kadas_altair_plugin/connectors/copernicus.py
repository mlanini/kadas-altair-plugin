"""Copernicus Dataspace STAC Catalog API Connector

Implements access to Copernicus Dataspace using STAC API 1.1.0:
https://documentation.dataspace.copernicus.eu/APIs/STAC.html

Supports:
- OAuth2 authentication with client credentials
- STAC Catalog API for Sentinel-1, Sentinel-2, Sentinel-3, Sentinel-5P, Sentinel-6
- Advanced search with spatial, temporal, and cloud cover filters
- Integrated with QGIS network manager for proper SSL/proxy handling

IMPORTANT: Asset Access Requirements
--------------------------------------
Copernicus Dataspace has TWO separate authentication systems:

1. OAuth2 Bearer Token (for APIs):
   - Used for STAC catalog search and metadata
   - Used to request temporary S3 credentials
   - Endpoint: https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token

2. S3 Credentials (for data access):
   - Used to access eodata S3 storage assets
   - Must be generated via S3 Keys Manager API
   - Endpoint: https://s3-keys-manager.cloudferro.com/api/user/credentials
   - OAuth2 Bearer token does NOT work for eodata assets (returns HTTP 403)

When loading COG assets via GDAL vsis3:
1. Get temporary S3 credentials using get_s3_credentials()
2. Configure GDAL with AWS credentials:
   gdal.SetConfigOption('AWS_S3_ENDPOINT', 'eodata.dataspace.copernicus.eu')
   gdal.SetConfigOption('AWS_ACCESS_KEY_ID', access_id)
   gdal.SetConfigOption('AWS_SECRET_ACCESS_KEY', secret)
3. Use vsis3:// prefix: vsis3://eodata/bucket/path
4. Delete credentials after use: delete_s3_credentials(access_id)

Official Documentation:
- STAC API: https://documentation.dataspace.copernicus.eu/APIs/STAC.html
- S3 Access: https://documentation.dataspace.copernicus.eu/APIs/S3.html
- OAuth2: https://documentation.dataspace.copernicus.eu/APIs/Token.html

Refactored based on patterns from OpenEO QGIS plugin:
https://github.com/Open-EO/openeo-qgis-plugin
"""

import json
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlencode

try:
    from qgis.PyQt.QtCore import QEventLoop, QTimer, QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest
    from qgis.core import QgsNetworkAccessManager
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False

from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.copernicus')


class CopernicusConnector(ConnectorBase):
    """Copernicus Dataspace STAC Catalog connector with OAuth2 support.
    
    Authentication: OAuth2 client credentials flow
    API Documentation: https://documentation.dataspace.copernicus.eu/
    
    Based on OpenEO QGIS plugin authentication patterns for better
    reliability and QGIS integration.
    """

    # Copernicus Dataspace endpoints
    AUTH_URL = 'https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token'
    STAC_API_URL = 'https://stac.dataspace.copernicus.eu/v1'
    S3_KEYS_MANAGER_URL = 'https://s3-keys-manager.cloudferro.com/api/user/credentials'
    S3_ENDPOINT = 'eodata.dataspace.copernicus.eu'
    
    # Available collections
    # Based on Copernicus Dataspace STAC catalog (STAC 1.1.0)
    # https://documentation.dataspace.copernicus.eu/APIs/STAC.html
    COLLECTIONS = {
        'sentinel-1-grd': {
            'id': 'sentinel-1-grd',  # Correct STAC collection ID
            'title': 'Sentinel-1 GRD',
            'description': 'SAR Ground Range Detected imagery',
            'resolution': '10m',
            'platform': 'SENTINEL-1'
        },
        'sentinel-2-l2a': {
            'id': 'sentinel-2-l2a',  # Correct STAC collection ID
            'title': 'Sentinel-2 L2A',
            'description': 'Optical multispectral imagery (Surface Reflectance)',
            'resolution': '10m',
            'platform': 'SENTINEL-2'
        },
        'sentinel-2-l1c': {
            'id': 'sentinel-2-l1c',  # Correct STAC collection ID
            'title': 'Sentinel-2 L1C',
            'description': 'Optical multispectral imagery (Top of Atmosphere)',
            'resolution': '10m',
            'platform': 'SENTINEL-2'
        },
        'sentinel-3-olci': {
            'id': 'sentinel-3-olci',  # Correct STAC collection ID
            'title': 'Sentinel-3 OLCI',
            'description': 'Ocean and Land Color Instrument',
            'resolution': '300m',
            'platform': 'SENTINEL-3'
        },
        'sentinel-3-slstr': {
            'id': 'sentinel-3-slstr',  # Correct STAC collection ID
            'title': 'Sentinel-3 SLSTR',
            'description': 'Sea and Land Surface Temperature Radiometer',
            'resolution': '500m',
            'platform': 'SENTINEL-3'
        },
        'sentinel-5p-l2': {
            'id': 'sentinel-5p-l2',  # Correct STAC collection ID
            'title': 'Sentinel-5P L2',
            'description': 'Atmospheric monitoring',
            'resolution': '7km',
            'platform': 'SENTINEL-5P'
        }
    }
    
    # Timeout settings (more conservative than before)
    timeout_auth = 20.0
    timeout_search = 45.0
    timeout_default = 30.0

    def __init__(self):
        """Initialize Copernicus connector.
        
        Uses QGIS network manager for proper SSL/TLS and proxy handling,
        similar to OpenEO plugin approach.
        """
        super().__init__()
        self._authenticated = False
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._client_id: Optional[str] = None
        self._client_secret: Optional[str] = None
        self._session = None
        
        logger.debug('CopernicusConnector initialized')

    def _http_request(self, url: str, method: str = 'GET', headers: Optional[Dict[str, str]] = None,
                      data: Optional[bytes] = None, timeout: float = 30.0) -> Optional[Dict]:
        """Make HTTP request using QGIS network manager.
        
        Args:
            url: URL to request
            method: HTTP method ('GET', 'POST', or 'DELETE')
            headers: Optional request headers
            data: Optional request body (for POST)
            timeout: Request timeout in seconds
            
        Returns:
            Parsed JSON response or None on error (or for 204 No Content)
        """
        if not QGIS_AVAILABLE:
            logger.error('Copernicus: QGIS network manager not available')
            return None

        try:
            # Create network request
            request = QNetworkRequest(QUrl(url))
            
            # Set headers
            if headers:
                for key, value in headers.items():
                    if key.lower() == 'content-type':
                        request.setHeader(QNetworkRequest.ContentTypeHeader, value)
                    else:
                        request.setRawHeader(key.encode('utf-8'), value.encode('utf-8'))
            
            # Use QGIS network manager
            nam = QgsNetworkAccessManager.instance()
            
            # Send request based on method
            if method == 'POST':
                reply = nam.post(request, data if data else b'')
            elif method == 'DELETE':
                reply = nam.deleteResource(request)
            else:  # GET
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
                logger.error(f"Copernicus: Request timeout after {timeout}s: {url}")
                return None
            
            # Get status code
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            
            # Check network errors
            if reply.error():
                error_code = reply.error()
                error_msg = reply.errorString()
                logger.error(f"Copernicus: Network error ({error_code}): {error_msg} - HTTP {status_code}")
                
                # Try to read error response
                response_data = reply.readAll().data().decode('utf-8', errors='ignore')
                if response_data:
                    logger.debug(f"Copernicus: Error response: {response_data[:500]}")
                
                reply.deleteLater()
                return None
            
            # Check HTTP status code
            if status_code and status_code >= 400:
                logger.error(f"Copernicus: HTTP {status_code} error for {url}")
                response_data = reply.readAll().data().decode('utf-8', errors='ignore')
                if response_data:
                    logger.debug(f"Copernicus: Error response: {response_data[:500]}")
                reply.deleteLater()
                return None
            
            # Handle 204 No Content (DELETE success)
            if status_code == 204:
                logger.debug(f"Copernicus: 204 No Content - request successful")
                reply.deleteLater()
                return None
            
            # Read and parse JSON response
            response_data = reply.readAll().data().decode('utf-8')
            logger.debug(f"Copernicus: Received {len(response_data)} bytes from {url}")
            
            reply.deleteLater()
            
            # Return None for empty responses
            if not response_data or response_data.strip() == '':
                return None
            
            return json.loads(response_data)
            
        except json.JSONDecodeError as e:
            logger.error(f"Copernicus: Failed to parse JSON from {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Copernicus: HTTP request failed for {url}: {e}")
            import traceback
            logger.debug(f"Copernicus: Traceback: {traceback.format_exc()}")
            return None


    @property
    def is_authenticated(self) -> bool:
        """Check if connector is authenticated with valid token.
        
        Returns:
            bool: True if authenticated and token is still valid
        """
        if not self._authenticated or not self._access_token:
            return False
        
        # Check token expiration
        if self._token_expires_at and datetime.now() >= self._token_expires_at:
            logger.debug('Copernicus: access token expired')
            return False
        
        return True

    def test_credentials(self, client_id: str, client_secret: str) -> Tuple[bool, str]:
        """Test Copernicus credentials without storing them.
        
        Useful for validating credentials in UI before saving.
        
        Args:
            client_id: OAuth2 client ID
            client_secret: OAuth2 client secret
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        # Temporarily store credentials
        old_id = self._client_id
        old_secret = self._client_secret
        old_authenticated = self._authenticated
        
        try:
            self._client_id = client_id
            self._client_secret = client_secret
            
            logger.info('Copernicus: Testing credentials...')
            success = self._obtain_access_token()
            
            if success:
                # Get token info
                expires_in = int((self._token_expires_at - datetime.now()).total_seconds()) if self._token_expires_at else 0
                message = f"✓ Credentials valid! Token expires in {expires_in} seconds."
                logger.info(f'Copernicus: {message}')
                return True, message
            else:
                message = "✗ Invalid credentials or authentication failed. Check logs for details."
                logger.error(f'Copernicus: {message}')
                return False, message
                
        except Exception as e:
            message = f"✗ Error testing credentials: {e}"
            logger.error(f'Copernicus: {message}')
            return False, message
        finally:
            # Restore original credentials
            self._client_id = old_id
            self._client_secret = old_secret
            self._authenticated = old_authenticated

    def authenticate(self, credentials: Dict[str, str], verify: bool = True) -> bool:
        """Authenticate using OAuth2 client credentials flow.
        
        Follows OpenEO plugin pattern for credential management.
        
        Args:
            credentials: Dict with 'client_id' and 'client_secret'
            verify: Whether to verify credentials immediately by requesting token
            
        Returns:
            bool: True if authentication successful or credentials stored
        """
        # Extract and clean credentials
        self._client_id = credentials.get('client_id', '').strip()
        self._client_secret = credentials.get('client_secret', '').strip()

        if not self._client_id or not self._client_secret:
            logger.warning('Copernicus: missing client_id or client_secret in credentials')
            self._authenticated = False
            return False

        logger.debug(f'Copernicus: credentials provided (client_id length: {len(self._client_id)})')
        logger.debug(f'Copernicus: client_id starts with: {self._client_id[:10]}...')

        if not verify:
            # Offline mode - just store credentials
            self._authenticated = True
            logger.debug('Copernicus: credentials stored (offline mode, not verified)')
            return True

        # Verify credentials by requesting access token
        logger.info('Copernicus: Verifying credentials with authentication server...')
        return self._obtain_access_token()

    def _obtain_access_token(self) -> bool:
        """Obtain OAuth2 access token using client credentials grant.
        
        Uses QgsNetworkAccessManager for SSL/proxy handling instead of requests library.
        
        Returns:
            bool: True if token obtained successfully
        """
        if not self._client_id or not self._client_secret:
            logger.error('Copernicus: cannot obtain token without credentials')
            return False

        if not QGIS_AVAILABLE:
            logger.error('Copernicus: QGIS network manager not available')
            return False

        try:
            logger.debug('Copernicus: requesting OAuth2 access token via QGIS network manager...')
            logger.debug(f'Copernicus: auth URL: {self.AUTH_URL}')
            logger.debug(f'Copernicus: client_id: {self._client_id[:10]}...{self._client_id[-4:]}')
            
            # Prepare token request according to Copernicus Dataspace documentation
            # https://documentation.dataspace.copernicus.eu/APIs/Token.html
            data = {
                'grant_type': 'client_credentials',
                'client_id': self._client_id,
                'client_secret': self._client_secret
            }
            
            # URL-encode the form data
            encoded_data = urlencode(data).encode('utf-8')
            
            # Create network request
            request = QNetworkRequest(QUrl(self.AUTH_URL))
            request.setHeader(QNetworkRequest.ContentTypeHeader, 'application/x-www-form-urlencoded')
            request.setRawHeader(b'Accept', b'application/json')
            
            # Log request details (without secret)
            logger.debug(f'Copernicus: POST {self.AUTH_URL}')
            logger.debug(f'Copernicus: grant_type=client_credentials')
            
            # Use QGIS network manager (respects proxy and SSL settings)
            nam = QgsNetworkAccessManager.instance()
            reply = nam.post(request, encoded_data)
            
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
                logger.error(f'Copernicus: ✗ Token request timeout (>{self.timeout_auth}s)')
                logger.error('Copernicus: The authentication server may be slow or unreachable')
                self._authenticated = False
                return False
            
            # Get response status code
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            
            # Check network errors
            if reply.error():
                error_code = reply.error()
                error_msg = reply.errorString()
                
                logger.error(f'Copernicus: ✗ Network error ({error_code}): {error_msg}')
                logger.debug(f'Copernicus: HTTP status: {status_code}')
                
                # Try to read response body for more details
                response_data = reply.readAll().data().decode('utf-8', errors='ignore')
                if response_data:
                    try:
                        error_data = json.loads(response_data)
                        error_desc = error_data.get('error_description', error_data.get('error', ''))
                        if error_desc:
                            logger.error(f'Copernicus: {error_desc}')
                    except json.JSONDecodeError:
                        logger.debug(f'Copernicus: Response body: {response_data[:200]}')
                
                # Provide specific guidance based on status code
                if status_code == 401:
                    logger.error('Copernicus: 401 Unauthorized - Invalid client credentials')
                    logger.error('Copernicus: Please verify your client_id and client_secret')
                    logger.error('Copernicus: Get credentials at: https://dataspace.copernicus.eu/')
                elif status_code == 400:
                    logger.error('Copernicus: 400 Bad Request - Malformed request')
                    logger.error('Copernicus: Check that credentials do not contain special characters')
                
                self._authenticated = False
                return False
            
            # Check HTTP status code
            if status_code and status_code >= 400:
                logger.error(f'Copernicus: ✗ HTTP {status_code} error')
                
                # Read response body
                response_data = reply.readAll().data().decode('utf-8', errors='ignore')
                try:
                    error_data = json.loads(response_data)
                    error_desc = error_data.get('error_description', error_data.get('error', 'Unknown error'))
                    logger.error(f'Copernicus: {error_desc}')
                except json.JSONDecodeError:
                    logger.debug(f'Copernicus: Response: {response_data[:200]}')
                
                self._authenticated = False
                return False
            
            # Read and parse successful response
            response_data = reply.readAll().data().decode('utf-8')
            logger.debug(f'Copernicus: received {len(response_data)} bytes')
            
            token_data = json.loads(response_data)
            logger.debug(f'Copernicus: token response keys: {list(token_data.keys())}')
            
            self._access_token = token_data.get('access_token')
            expires_in = token_data.get('expires_in', 3600)  # Default 1 hour
            
            if not self._access_token:
                logger.error('Copernicus: ✗ No access_token in response')
                logger.error(f'Copernicus: response data: {token_data}')
                self._authenticated = False
                return False
            
            # Set expiration time with 5 minute buffer to avoid edge cases
            self._token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)
            
            self._authenticated = True
            logger.info(f'Copernicus: ✓ OAuth2 token obtained successfully (expires in {expires_in}s)')
            logger.debug(f'Copernicus: token: {self._access_token[:20]}...{self._access_token[-10:]}')
            
            # Clean up
            reply.deleteLater()
            
            return True
                
        except json.JSONDecodeError as e:
            logger.error(f'Copernicus: ✗ Failed to parse token response as JSON: {e}')
            logger.error(f'Copernicus: Response was not valid JSON')
            self._authenticated = False
            return False
        except Exception as e:
            logger.error(f'Copernicus: ✗ Unexpected error during token request: {e}')
            import traceback
            logger.debug(f'Copernicus: Traceback: {traceback.format_exc()}')
            self._authenticated = False
            return False

    def _ensure_valid_token(self) -> bool:
        """Ensure we have a valid access token, refreshing if necessary.
        
        Similar to OpenEO plugin's token management approach.
        
        Returns:
            bool: True if valid token available
        """
        if not self._authenticated:
            logger.debug('Copernicus: not authenticated, cannot ensure token')
            return False
        
        # Check if token is expired or about to expire
        if not self._access_token or (self._token_expires_at and datetime.now() >= self._token_expires_at):
            logger.debug('Copernicus: token expired or missing, obtaining new token...')
            return self._obtain_access_token()
        
        return True

    def search(self, query: str, **kwargs) -> List[Dict]:
        """Search Copernicus STAC catalog for imagery.
        
        Implements base class search interface with Copernicus-specific parameters.
        
        Args:
            query: Free-text search query (currently not used by STAC API)
            **kwargs: Additional search parameters:
                - bbox: Bounding box [min_lon, min_lat, max_lon, max_lat] in EPSG:4326
                - start_date: Start date in 'YYYY-MM-DD' format
                - end_date: End date in 'YYYY-MM-DD' format
                - max_cloud_cover: Maximum cloud coverage percentage (0-100)
                - collection: Collection ID (e.g., 'sentinel-2-l2a')
                - limit: Maximum number of results (default: 100)
            
        Returns:
            List of result dictionaries with metadata
        """
        if not self._ensure_valid_token():
            logger.warning('Copernicus: not authenticated or token invalid, cannot search')
            return []

        # Extract search parameters from kwargs
        bbox = kwargs.get('bbox')
        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        max_cloud_cover = kwargs.get('max_cloud_cover', 100)
        collection = kwargs.get('collection', 'sentinel-2-l2a')
        limit = kwargs.get('limit', 100)
        
        # Validate bbox (required)
        if not bbox:
            logger.error('Copernicus: bbox is required')
            return []
        
        # Use default date range if not provided (last 30 days)
        if not start_date or not end_date:
            from datetime import datetime, timedelta
            end = datetime.now()
            start = end - timedelta(days=30)
            
            if not start_date:
                start_date = start.strftime('%Y-%m-%d')
                logger.info(f'Copernicus: Using default start_date: {start_date}')
            
            if not end_date:
                end_date = end.strftime('%Y-%m-%d')
                logger.info(f'Copernicus: Using default end_date: {end_date}')
        
        try:
            logger.info(f'Copernicus: searching {collection} with bbox={bbox}, dates={start_date} to {end_date}, cloud<={max_cloud_cover}%')
            logger.debug(f'Copernicus: Request limit={limit}')
            
            # Build STAC search request
            search_url = f'{self.STAC_API_URL}/search'
            
            # Prepare request body according to STAC API spec
            request_body = {
                'bbox': bbox,
                'datetime': f'{start_date}T00:00:00Z/{end_date}T23:59:59Z',
                'collections': [collection],
                'limit': min(limit, 1000)  # Cap at 1000 per STAC spec
            }
            
            # Add cloud cover filter for optical sensors
            if collection.startswith('sentinel-2') and max_cloud_cover < 100:
                request_body['query'] = {
                    'eo:cloud_cover': {
                        'lte': max_cloud_cover
                    }
                }
            
            # Prepare headers with OAuth2 bearer token
            headers = {
                'Authorization': f'Bearer {self._access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            # Convert request body to JSON bytes
            request_data = json.dumps(request_body).encode('utf-8')
            
            # Make POST request using QGIS network manager
            data = self._http_request(
                search_url,
                method='POST',
                headers=headers,
                data=request_data,
                timeout=self.timeout_search
            )
            
            if not data:
                logger.error('Copernicus: search request failed')
                return []
            
            # Parse STAC response
            features = data.get('features', [])
            
            logger.info(f'Copernicus: found {len(features)} results for {collection}')
            
            # Transform STAC features to internal format
            results = []
            for feature in features:
                result = self._transform_stac_feature(feature, collection)
                if result:
                    results.append(result)
            
            return results
                
        except Exception as e:
            logger.error(f'Copernicus: unexpected error during search: {e}')
            import traceback
            logger.debug(traceback.format_exc())
            return []

    def _transform_stac_feature(self, feature: Dict, collection: str) -> Optional[Dict]:
        """Transform STAC feature to internal result format.
        
        Extracts relevant metadata from STAC feature and normalizes to
        plugin's internal format.
        
        Args:
            feature: STAC feature from catalog API
            collection: Collection name for context
            
        Returns:
            Dict with standardized result fields or None if transformation fails
        """
        try:
            properties = feature.get('properties', {})
            geometry = feature.get('geometry', {})
            bbox_list = feature.get('bbox', [])
            
            # Extract datetime
            datetime_str = properties.get('datetime', '')
            date = datetime_str.split('T')[0] if datetime_str else 'Unknown'
            
            # Extract cloud cover (optical sensors only)
            cloud_cover = properties.get('eo:cloud_cover')
            if cloud_cover is None:
                cloud_cover = properties.get('cloudCover', 0)
            
            # Determine satellite platform
            platform = properties.get('platform', '')
            constellation = properties.get('constellation', '')
            
            if not platform and constellation:
                platform = constellation
            
            if not platform:
                # Infer from collection
                collection_upper = collection.upper()
                if 'SENTINEL-2' in collection_upper:
                    platform = 'Sentinel-2'
                elif 'SENTINEL-1' in collection_upper:
                    platform = 'Sentinel-1'
                elif 'SENTINEL-3' in collection_upper:
                    platform = 'Sentinel-3'
                elif 'SENTINEL-5' in collection_upper:
                    platform = 'Sentinel-5P'
                else:
                    platform = 'Unknown'
            
            # Get resolution from collection metadata
            coll_meta = self.COLLECTIONS.get(collection, {})
            resolution = coll_meta.get('resolution', 'Unknown')
            
            # Get assets and convert S3 URLs to HTTPS
            assets = feature.get('assets', {})
            converted_assets = self._convert_s3_urls_to_https(assets)
            
            # Build standardized result
            result = {
                'collection': f'Copernicus {platform}',
                'id': feature.get('id', 'unknown'),
                'date': date,
                'satellite': platform.upper() if platform != 'Unknown' else 'SENTINEL',
                'cloud_cover': round(cloud_cover, 1) if cloud_cover is not None else None,
                'resolution': resolution,
                'bbox': bbox_list,
                'geometry': geometry,
                'properties': properties,
                'assets': converted_assets,
                'stac_feature': feature,  # Preserve original for advanced use
                'source': 'Copernicus Dataspace'
            }
            
            return result
            
        except Exception as e:
            logger.warning(f'Copernicus: failed to transform STAC feature: {e}')
            logger.debug(f'Problematic feature: {feature}')
            return None
    
    def _convert_s3_urls_to_https(self, assets: Dict) -> Dict:
        """Convert S3 URLs to HTTPS URLs for Copernicus assets.
        
        Copernicus Dataspace STAC catalog returns S3 URLs like:
        s3://eodata/Sentinel-2/MSI/L2A/2026/02/07/...
        
        These must be converted to HTTPS URLs:
        https://eodata.dataspace.copernicus.eu/Sentinel-2/MSI/L2A/2026/02/07/...
        
        Args:
            assets: Dictionary of assets from STAC feature
            
        Returns:
            Dictionary with converted asset URLs
        """
        if not assets:
            return assets
        
        converted = {}
        
        for asset_name, asset_data in assets.items():
            if not isinstance(asset_data, dict):
                converted[asset_name] = asset_data
                continue
            
            # Copy asset data
            asset_copy = asset_data.copy()
            
            # Convert S3 URL to HTTPS
            href = asset_copy.get('href', '')
            if href.startswith('s3://eodata/'):
                # Remove s3://eodata/ prefix and replace with HTTPS URL
                path = href.replace('s3://eodata/', '')
                https_url = f'https://eodata.dataspace.copernicus.eu/{path}'
                asset_copy['href'] = https_url
                
                logger.debug(f'Copernicus: Converted S3 to HTTPS: {asset_name}')
                logger.debug(f'  Original: {href[:80]}...')
                logger.debug(f'  Converted: {https_url[:80]}...')
            
            converted[asset_name] = asset_copy
        
        return converted

    def get_collections(self) -> List[Dict[str, str]]:
        """Get list of available collections.
        
        Returns static list of known Copernicus collections.
        
        Returns:
            List of collection metadata dicts
        """
        collections = []
        for coll_id, coll_meta in self.COLLECTIONS.items():
            collections.append({
                'id': coll_id,
                'title': coll_meta.get('title', coll_id),
                'description': coll_meta.get('description', ''),
                'resolution': coll_meta.get('resolution', 'Unknown')
            })
        return collections

    def get_preview_url(self, result: Dict) -> Optional[str]:
        """Get preview/thumbnail URL for a result.
        
        Args:
            result: Search result dictionary
            
        Returns:
            URL string or None
        """
        try:
            assets = result.get('assets', {})
            
            # Try to find thumbnail or preview asset
            for asset_key in ['thumbnail', 'preview', 'visual']:
                if asset_key in assets:
                    asset = assets[asset_key]
                    if isinstance(asset, dict):
                        return asset.get('href')
            
            return None
            
        except Exception as e:
            logger.warning(f'Copernicus: failed to get preview URL: {e}')
            return None

    def get_download_url(self, result: Dict, asset_type: str = 'data') -> Optional[str]:
        """Get download URL for specific asset type.
        
        For Copernicus Dataspace, this returns the OData API download URL
        which requires OAuth2 authentication.
        
        Args:
            result: Search result dictionary
            asset_type: Asset type to download (e.g., 'data', 'metadata')
            
        Returns:
            URL string or None
        """
        try:
            # For Copernicus, we need to use the OData API for downloads
            # The STAC assets contain links but they require special handling
            item_id = result.get('id')
            if not item_id:
                logger.warning('Copernicus: no item ID found in result')
                return None
            
            # Copernicus OData download URL pattern
            # https://documentation.dataspace.copernicus.eu/APIs/OData.html
            odata_url = f"https://zipper.dataspace.copernicus.eu/odata/v1/Products({item_id})/$value"
            
            logger.debug(f'Copernicus: OData download URL: {odata_url}')
            return odata_url
            
        except Exception as e:
            logger.warning(f'Copernicus: failed to get download URL: {e}')
            return None
    
    def get_asset_download_url(self, result: Dict, asset_name: str) -> Optional[str]:
        """Get download URL for a specific asset within a product.
        
        For Copernicus individual assets (like TCI.jp2, B04.jp2), we need to
        extract them from the product archive or use direct asset links with auth.
        
        Args:
            result: Search result dictionary
            asset_name: Name of the asset (e.g., 'visual', 'B04', 'TCI')
            
        Returns:
            Tuple of (URL string or None, requires_auth: bool)
        """
        try:
            assets = result.get('assets', {})
            
            if asset_name not in assets:
                logger.warning(f'Copernicus: asset "{asset_name}" not found')
                return None
            
            asset = assets[asset_name]
            if not isinstance(asset, dict):
                return None
            
            asset_href = asset.get('href')
            if not asset_href:
                return None
            
            # Copernicus assets require OAuth2 authentication
            # The href is typically an S3 URL that requires signed access
            logger.debug(f'Copernicus: asset URL requires OAuth2: {asset_href[:100]}...')
            
            return asset_href
            
        except Exception as e:
            logger.warning(f'Copernicus: failed to get asset download URL: {e}')
            return None
    
    def get_s3_credentials(self) -> Optional[Dict[str, str]]:
        """Get temporary S3 credentials using OAuth2 token.
        
        Copernicus Dataspace requires S3 credentials to access eodata assets.
        These are different from OAuth2 tokens and must be generated via S3 Keys Manager API.
        
        API Documentation: https://documentation.dataspace.copernicus.eu/APIs/S3.html
        
        Returns:
            Dict with 'access_id' and 'secret' keys, or None if failed
        """
        if not self._ensure_valid_token():
            logger.error('Copernicus: Cannot get S3 credentials - no valid OAuth2 token')
            return None
        
        try:
            logger.info('Copernicus: Requesting temporary S3 credentials from S3 Keys Manager...')
            
            headers = {
                'Authorization': f'Bearer {self._access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            # Make POST request to generate temporary S3 credentials
            response = self._http_request(
                self.S3_KEYS_MANAGER_URL,
                method='POST',
                headers=headers,
                timeout=self.timeout_default
            )
            
            if not response:
                logger.error('Copernicus: Failed to get S3 credentials - no response')
                return None
            
            # Extract credentials
            access_id = response.get('access_id')
            secret = response.get('secret')
            
            if not access_id or not secret:
                logger.error('Copernicus: S3 credentials response missing access_id or secret')
                logger.debug(f'Response keys: {list(response.keys())}')
                return None
            
            logger.info(f'Copernicus: ✅ Got temporary S3 credentials (access_id: {access_id[:20]}...)')
            
            return {
                'access_id': access_id,
                'secret': secret
            }
            
        except Exception as e:
            logger.error(f'Copernicus: Failed to get S3 credentials: {e}')
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    def delete_s3_credentials(self, access_id: str) -> bool:
        """Delete temporary S3 credentials.
        
        Official endpoint from documentation:
        https://documentation.dataspace.copernicus.eu/APIs/S3.html
        
        Args:
            access_id: The access_id to delete
            
        Returns:
            bool: True if successfully deleted
        """
        if not self._ensure_valid_token():
            logger.warning('Copernicus: Cannot delete S3 credentials - no valid OAuth2 token')
            return False
        
        try:
            # Official DELETE endpoint format from documentation
            delete_url = f'{self.S3_KEYS_MANAGER_URL}/access_id/{access_id}'
            
            headers = {
                'Authorization': f'Bearer {self._access_token}',
                'Accept': 'application/json'
            }
            
            # Make DELETE request
            # Returns 204 No Content on success (handled as None by _http_request)
            self._http_request(
                delete_url,
                method='DELETE',
                headers=headers,
                timeout=self.timeout_default
            )
            
            logger.info(f'Copernicus: ✅ Deleted temporary S3 credentials (access_id: {access_id[:20]}...)')
            return True
            
        except Exception as e:
            logger.warning(f'Copernicus: Failed to delete S3 credentials: {e}')
            return False
        """Get a signed URL for accessing a Copernicus asset.
        
        Copernicus Dataspace uses S3 URLs that require OAuth2 authentication.
        This method returns the URL with proper authentication headers configured.
        
        Args:
            asset_href: The asset href from STAC catalog
            
        Returns:
            Signed/authenticated URL or None if authentication fails
        """
        try:
            # Ensure we have a valid token
            if not self._ensure_valid_token():
                logger.error('Copernicus: Cannot get signed URL - authentication failed')
                return None
            
            # For Copernicus S3 URLs, we need to include the Bearer token
            # GDAL vsicurl will use GDAL_HTTP_HEADERS environment variable
            # So we just return the original URL - the caller must configure GDAL
            
            logger.debug(f'Copernicus: Asset requires Bearer token authentication')
            logger.debug(f'Copernicus: Original URL: {asset_href[:100]}...')
            
            # Return original URL - authentication is handled via GDAL_HTTP_HEADERS
            return asset_href
            
        except Exception as e:
            logger.error(f'Copernicus: Failed to get signed asset URL: {e}')
            return None