"""CDSE Sentinel Connector for KADAS Altair

Access Sentinel-1, Sentinel-2, Sentinel-5P via CDSE Sentinel APIs
Uses OAuth2 authentication with client credentials
Supports WMS/WMTS rendering and WCS data download

Based on copernicus/dataspace architecture
https://github.com/copernicus/dataspace
"""

from typing import Optional, Dict, List, Tuple, Any
from datetime import datetime
from urllib.parse import urlencode
import time

try:
    from qgis.core import QgsDataSourceUri
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False

from .base import ConnectorBase
from ..logger import get_logger
from ..utilities.qgis_network import qgis_request_json

logger = get_logger('connectors.cdse_sentinel')

try:
    from requests_oauthlib import OAuth2Session
    from oauthlib.oauth2 import BackendApplicationClient
    OAUTH_AVAILABLE = True
except Exception as exc:
    OAUTH_AVAILABLE = False
    logger.warning(
        "requests-oauthlib not available; "
        f"OAuth2 authentication disabled ({exc})"
    )


class CdseSentinelConnector(ConnectorBase):
    """CDSE Sentinel connector with OAuth2 and OGC service support.
    
    Supports:
    - Sentinel-1 (SAR, Ground Range Detected)
    - Sentinel-2 L1C (MSI, Level-1C Top-of-Atmosphere Reflectance)
    - Sentinel-2 L2A (MSI, Level-2A Surface Reflectance)
    - Sentinel-5P (atmospheric data)
    
    Authentication: OAuth2 client credentials
    Documentation: https://documentation.dataspace.copernicus.eu/
    """

    # Data sources / collections
    DATA_SOURCES = {
        'S1GRD': {
            'id': 'S1GRD',
            'title': 'Sentinel-1 GRD',
            'description': 'SAR Ground Range Detected imagery',
            'cloudless': True,
            'temporal': True
        },
        'S2L1C': {
            'id': 'S2L1C',
            'title': 'Sentinel-2 L1C',
            'description': 'Optical Top-of-Atmosphere Reflectance',
            'cloudless': False,
            'temporal': True
        },
        'S2L2A': {
            'id': 'S2L2A',
            'title': 'Sentinel-2 L2A',
            'description': 'Optical Surface Reflectance',
            'cloudless': False,
            'temporal': True
        },
        'S5P': {
            'id': 'S5P',
            'title': 'Sentinel-5P',
            'description': 'Atmospheric data (O3, NO2, SO2, CO, CH4, HCHO)',
            'cloudless': True,
            'temporal': True
        },
    }

    # Image priorities
    IMAGE_PRIORITIES = ['mostRecent', 'leastRecent', 'leastCC']

    # CDSE Sentinel Catalog collection IDs (CDSE)
    CATALOG_COLLECTIONS = {
        'S1GRD': 'sentinel-1-grd',
        'S2L1C': 'sentinel-2-l1c',
        'S2L2A': 'sentinel-2-l2a',
        'S5P': 'sentinel-5p-l2',
    }

    timeout_auth: float = 30.0
    timeout_search: float = 45.0
    oauth_max_retries: int = 3

    def __init__(self):
        super().__init__()
        self.name = 'CDSE Sentinel'
        self.description = 'Access Sentinel imagery via CDSE Sentinel'

        # OAuth2 settings
        self.base_url = 'https://sh.dataspace.copernicus.eu'
        self.oauth_token_url = (
            'https://identity.dataspace.copernicus.eu/auth/realms/CDSE/'
            'protocol/openid-connect/token'
        )
        self.catalog_search_url = f'{self.base_url}/catalog/v1/search'
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.session: Optional[OAuth2Session] = None
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[float] = None
        self._last_auth_error: Optional[str] = None

    @staticmethod
    def _iso_start(date_value: str) -> str:
        date_value = (date_value or '').strip()
        if not date_value:
            return ''
        if 'T' in date_value:
            return date_value if date_value.endswith('Z') else f'{date_value}Z'
        return f'{date_value}T00:00:00Z'

    @staticmethod
    def _iso_end(date_value: str) -> str:
        date_value = (date_value or '').strip()
        if not date_value:
            return ''
        if 'T' in date_value:
            return date_value if date_value.endswith('Z') else f'{date_value}Z'
        return f'{date_value}T23:59:59Z'

    def _build_datetime_range(self, start_date: str, end_date: str) -> str:
        start = self._iso_start(start_date)
        end = self._iso_end(end_date)

        if start and end:
            return f'{start}/{end}'
        if start and not end:
            return f'{start}/..'
        if end and not start:
            return f'../{end}'

        now_utc = datetime.utcnow().strftime('%Y-%m-%dT23:59:59Z')
        fallback_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        fallback_start = fallback_start.strftime('%Y-%m-%dT00:00:00Z')
        return f'{fallback_start}/{now_utc}'

    def _normalize_collection(
            self,
            collection: Optional[str],
            kwargs: Dict[str, Any]) -> str:
        datasource = str(kwargs.get('datasource', '') or '').strip()
        source = str(collection or datasource or 'S2L2A').strip()
        if source in self.CATALOG_COLLECTIONS:
            return self.CATALOG_COLLECTIONS[source]
        return source.lower()

    def _extract_next_token(self, data: Dict[str, Any]) -> Optional[str]:
        context = data.get('context') or {}
        if isinstance(context, dict) and context.get('next') is not None:
            return str(context.get('next'))

        for link in data.get('links', []) or []:
            if link.get('rel') != 'next':
                continue
            href = str(link.get('href') or '')
            if 'next=' in href:
                return href.split('next=', 1)[1].split('&', 1)[0]
        return None

    def _feature_to_stac_item(
            self,
            feature: Dict[str, Any],
            collection_id: str) -> Dict[str, Any]:
        properties = feature.get('properties') or {}
        bbox = feature.get('bbox')
        geometry = feature.get('geometry')
        assets = feature.get('assets') or {}

        platform = properties.get('platform') or properties.get('constellation') or ''
        cloud_cover = properties.get('eo:cloud_cover')

        return {
            'type': 'Feature',
            'id': str(feature.get('id') or 'unknown'),
            'collection': feature.get('collection') or collection_id,
            'bbox': bbox,
            'geometry': geometry,
            'properties': {
                **properties,
                'platform': platform,
                'eo:cloud_cover': cloud_cover,
                'cloud_cover': cloud_cover,
                'auth_required': True,
                'auth_source': 'cdse_sentinel_oauth2',
            },
            'assets': assets,
            'links': feature.get('links') or [],
            'stac_feature': feature,
            'is_collection': False,
        }

    def get_last_auth_error(self) -> Optional[str]:
        """Return the last authentication error message, if any."""
        return self._last_auth_error

    def get_auth_failure_hint(self) -> str:
        """Return a human-readable hint for the last auth failure."""
        if not OAUTH_AVAILABLE:
            return (
                "OAuth2 dependencies are missing or failed to load. "
                "Install requests-oauthlib and oauthlib, then restart KADAS."
            )
        if not self.client_id or not self.client_secret:
            return "Missing CDSE Sentinel credentials: set client_id and client_secret."
        if self._last_auth_error:
            if 'ConnectTimeout' in self._last_auth_error or 'timed out' in self._last_auth_error.lower():
                return (
                    "Connection timeout while contacting Copernicus identity service. "
                    "Check KADAS/network proxy settings and increase Sentinel request timeout."
                )
            return self._last_auth_error
        return "Authentication failed. Check credentials and network/proxy settings."

    @staticmethod
    def _token_response_compliance_hook(response):
        """Raise HTTP errors for token response before oauthlib parsing."""
        response.raise_for_status()
        return response

    def _fetch_token_via_qgis(self, timeout: int = 30) -> bool:
        """Try to fetch CDSE OAuth2 token via QGIS network stack first."""
        if not self.client_id or not self.client_secret:
            return False

        token_payload = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
        }
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'KADAS-Altair-Plugin/1.0',
        }

        data, err, status = qgis_request_json(
            method='POST',
            url=self.oauth_token_url,
            headers=headers,
            payload=token_payload,
            timeout=max(int(timeout or 0), int(self.timeout_auth), 30),
        )
        if err is not None:
            logger.debug(
                'CDSE QGIS token fetch failed (status=%s): %s',
                status,
                err,
            )
            return False

        token = str((data or {}).get('access_token') or '').strip()
        if not token:
            logger.debug('CDSE QGIS token fetch returned no access_token')
            return False

        self.access_token = token
        try:
            expires_in = int((data or {}).get('expires_in') or 0)
        except Exception:
            expires_in = 0
        if expires_in > 0:
            self.token_expires_at = datetime.now().timestamp() + max(
                60,
                expires_in - 60,
            )
        return True

    def _ensure_oauth_session(self, timeout: int = 30) -> bool:
        """Ensure OAuth2 session is initialized and token is valid."""
        self._last_auth_error = None
        if not OAUTH_AVAILABLE:
            self._last_auth_error = "OAuth2 libraries not available (requests-oauthlib)"
            logger.error(self._last_auth_error)
            return False

        if not self.client_id or not self.client_secret:
            self._last_auth_error = "CDSE Sentinel credentials not configured"
            logger.error(self._last_auth_error)
            return False

        if self.session and self.access_token:
            # Check if token needs refresh
            if (self.token_expires_at and
                    datetime.now().timestamp() < (self.token_expires_at - 60)):
                return True

        # Create new OAuth2 session
        try:
            client = BackendApplicationClient(client_id=self.client_id)
            self.session = OAuth2Session(client=client)
            self.session.trust_env = True

            # Prefer QGIS network stack first so KADAS proxy/auth settings are
            # applied consistently in corporate environments.
            if self._fetch_token_via_qgis(timeout=timeout):
                logger.info('CDSE Sentinel OAuth2 token fetched via QGIS network')
                return True

            # Reuse base connector network settings (proxy + SSL verify).
            # This is critical in corporate networks where direct egress is blocked.
            base_session: Optional[Any] = self.get_session()
            if base_session is not None:
                try:
                    if not getattr(self.session, 'proxies', None) and getattr(base_session, 'proxies', None):
                        self.session.proxies.update(base_session.proxies)
                except Exception:
                    pass

                try:
                    if hasattr(base_session, 'verify'):
                        self.session.verify = base_session.verify
                except Exception:
                    pass

            if getattr(self, '_proxies', None):
                try:
                    self.session.proxies.update(self._proxies)
                except Exception:
                    pass

            if hasattr(self, '_verify_ssl'):
                try:
                    self.session.verify = self._verify_ssl
                except Exception:
                    pass

            # Proxy/TLS handshakes can take significantly longer than regular API calls.
            requested_timeout = int(timeout) if timeout else int(self.timeout_auth)
            auth_connect_timeout = max(requested_timeout, int(self.timeout_auth), 30)
            auth_read_timeout = max(auth_connect_timeout * 2, 90)
            auth_timeout_tuple = (auth_connect_timeout, auth_read_timeout)

            self.session.register_compliance_hook(
                'access_token_response',
                self._token_response_compliance_hook,
            )

            last_exception: Optional[Exception] = None
            for attempt in range(1, self.oauth_max_retries + 1):
                try:
                    proxies_cfg = getattr(self.session, 'proxies', None)
                    if not proxies_cfg:
                        proxies_cfg = None

                    fetch_kwargs: Dict[str, Any] = {
                        'token_url': self.oauth_token_url,
                        'client_id': self.client_id,
                        'client_secret': self.client_secret,
                        'include_client_id': True,
                        'timeout': auth_timeout_tuple,
                        'verify': getattr(self.session, 'verify', True),
                    }
                    # Important: do not pass an empty proxies dict because it
                    # suppresses trust_env proxy discovery in requests.
                    if proxies_cfg:
                        fetch_kwargs['proxies'] = proxies_cfg

                    logger.debug(
                        "Fetching OAuth2 token from %s (attempt %s/%s, timeout=%s, proxies=%s)",
                        self.oauth_token_url,
                        attempt,
                        self.oauth_max_retries,
                        auth_timeout_tuple,
                        'explicit' if proxies_cfg else 'env/default',
                    )
                    token = self.session.fetch_token(**fetch_kwargs)
                    self.access_token = token.get('access_token')
                    self.token_expires_at = token.get('expires_at')
                    logger.info("CDSE Sentinel OAuth2 authentication successful")
                    return True
                except Exception as exc:
                    last_exception = exc
                    logger.warning(
                        "CDSE OAuth2 token fetch attempt %s/%s failed: %s",
                        attempt,
                        self.oauth_max_retries,
                        exc,
                    )
                    if attempt < self.oauth_max_retries:
                        time.sleep(min(2 * attempt, 5))
            
            if last_exception is not None:
                raise last_exception
            raise RuntimeError("OAuth2 token fetch failed without exception")
        except Exception as exc:
            self._last_auth_error = f"OAuth2 token fetch failed: {exc}"
            logger.error(self._last_auth_error)
            self.session = None
            self.access_token = None
            return False

    def authenticate(
            self,
            credentials: Optional[dict] = None,
            verify: bool = True,
            timeout: int = 30) -> bool:
        """Authenticate with CDSE Sentinel credentials.

        Args:
            credentials: Dict with 'client_id' and 'client_secret'
            verify: Verify SSL certificate (default: True)

        Returns:
            True if authentication successful
        """
        if credentials:
            self.client_id = credentials.get('client_id')
            self.client_secret = credentials.get('client_secret')

        return self._ensure_oauth_session(timeout=timeout)

    def _request_catalog_search(
            self,
            payload: Dict[str, Any],
            timeout: int = 30) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int]]:
        """Request the CDSE catalog search endpoint through the best available network stack."""
        headers = {
            'Accept': 'application/geo+json, application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'KADAS-Altair-Plugin/1.0',
        }

        token = str(self.access_token or '').strip()
        if token:
            headers['Authorization'] = f'Bearer {token}'

        request_timeout = max(int(timeout or 0), int(self.timeout_search), 30)

        data, qgis_error, status = qgis_request_json(
            method='POST',
            url=self.catalog_search_url,
            headers=headers,
            payload=payload,
            timeout=request_timeout,
        )
        if qgis_error is None:
            if isinstance(data, dict):
                return data, None, status
            return {'items': data}, None, status

        logger.warning(
            'CDSE Sentinel catalog probe via QGIS network failed: %s',
            qgis_error,
        )

        session = self.get_session()
        if session is None:
            return None, qgis_error, status

        try:
            response = session.post(
                self.catalog_search_url,
                headers=headers,
                json=payload,
                timeout=request_timeout,
            )
            response.raise_for_status()
            if not response.content:
                return {}, None, response.status_code
            response_data = response.json()
            if isinstance(response_data, dict):
                return response_data, None, response.status_code
            return {'items': response_data}, None, response.status_code
        except Exception as exc:
            logger.warning(
                'CDSE Sentinel catalog probe via requests fallback failed: %s',
                exc,
            )
            return None, str(exc), None

    def verify_catalog_access(
            self,
            timeout: int = 30,
            collection: str = 'sentinel-2-l2a') -> Tuple[bool, str, int]:
        """Verify Catalog API access with a minimal POST /catalog/v1/search.

        This follows Copernicus Dataspace CDSE Sentinel Catalog API examples.
        """
        if not self._ensure_oauth_session(timeout=timeout):
            return False, self.get_auth_failure_hint(), 0

        payload = {
            'bbox': [13, 45, 14, 46],
            'datetime': '2019-12-10T00:00:00Z/2019-12-10T23:59:59Z',
            'collections': [collection],
            'limit': 1,
        }

        data, error, status = self._request_catalog_search(payload, timeout=timeout)
        if error is not None:
            message = f'Catalog API check failed: {error}'
            if status is not None:
                message = f'{message} (status={status})'
            self._last_auth_error = message
            logger.error(message)
            return False, message, 0

        if isinstance(data, dict):
            features = data.get('features') or []
        else:
            features = []

        count = len(features)
        logger.info(
            'CDSE Sentinel Catalog API access verified '
            f'({collection}, returned={count})'
        )
        return True, 'Catalog API reachable', count

    def get_collections(self) -> List[Dict[str, Any]]:
        """Return Catalog API collections, with static fallback.

        Mirrors the official "List collections" Catalog API example.
        """
        fallback = []
        for source_id, meta in self.DATA_SOURCES.items():
            fallback.append({
                'id': self.CATALOG_COLLECTIONS.get(source_id, source_id.lower()),
                'title': meta.get('title', source_id),
                'description': meta.get('description', ''),
            })

        if not self._ensure_oauth_session(timeout=int(self.timeout_auth)):
            return fallback

        active_session = self.session
        if active_session is None:
            return fallback

        try:
            url = f'{self.base_url}/catalog/v1/collections'
            response = active_session.get(url, timeout=self.timeout_search)
            response.raise_for_status()
            data = response.json() if response.content else {}
            collections = data.get('collections') or data.get('features') or []
            normalized = []
            for coll in collections:
                normalized.append({
                    'id': str(coll.get('id') or ''),
                    'title': str(coll.get('title') or coll.get('id') or ''),
                    'description': str(coll.get('description') or ''),
                })
            return [c for c in normalized if c.get('id')] or fallback
        except Exception as exc:
            logger.warning(f'CDSE Sentinel collections request failed: {exc}')
            return fallback

    def search_unified(
            self,
            bbox=None,
            start_date=None,
            end_date=None,
            max_cloud_cover=None,
            collection=None,
            text_query=None,
            limit: int = 100,
            timeout: Optional[float] = None,
            **kwargs) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Catalog API search aligned to Copernicus CDSE Sentinel examples.

        Uses POST /catalog/v1/search with request body keys such as:
        bbox, datetime, collections, limit, next, intersects, filter, fields,
        distinct, and sortby.
        """
        timeout_s = float(timeout) if timeout else float(self.timeout_search)
        timeout_s = max(timeout_s, 5.0)

        if not self._ensure_oauth_session(timeout=int(timeout_s)):
            return [], self.get_auth_failure_hint()

        active_session = self.session
        if active_session is None:
            return [], 'OAuth session unavailable after authentication'

        collection_id = self._normalize_collection(collection, kwargs)
        payload: Dict[str, Any] = {
            'collections': [collection_id],
            'limit': max(1, min(int(limit), 1000)),
            'datetime': self._build_datetime_range(
                str(start_date or ''),
                str(end_date or ''),
            ),
        }

        if bbox and len(bbox) >= 4:
            payload['bbox'] = [
                float(bbox[0]),
                float(bbox[1]),
                float(bbox[2]),
                float(bbox[3]),
            ]

        if kwargs.get('intersects'):
            payload['intersects'] = kwargs['intersects']

        if kwargs.get('next') is not None:
            payload['next'] = kwargs['next']

        if kwargs.get('fields') is not None:
            payload['fields'] = kwargs['fields']

        if kwargs.get('distinct') is not None:
            payload['distinct'] = kwargs['distinct']

        if kwargs.get('sortby') is not None:
            payload['sortby'] = kwargs['sortby']

        user_filter = str(kwargs.get('filter') or '').strip()
        cloud_filter = ''
        if max_cloud_cover is not None and collection_id.startswith('sentinel-2'):
            cloud_filter = f"eo:cloud_cover <= {float(max_cloud_cover):.2f}"

        text_filter = ''
        text_query_s = str(text_query or '').strip()
        if text_query_s:
            safe_query = text_query_s.replace("'", "''")
            text_filter = (
                f"id ILIKE '%{safe_query}%' OR s2:product_uri ILIKE '%{safe_query}%'"
            )

        filter_parts = [p for p in [user_filter, cloud_filter, text_filter] if p]
        if filter_parts:
            payload['filter'] = ' AND '.join(f'({part})' for part in filter_parts)

        data, error, _status = self._request_catalog_search(
            payload,
            timeout=int(timeout_s),
        )
        if error is not None:
            logger.error(f'CDSE Sentinel Catalog search failed: {error}')
            return [], error

        if not isinstance(data, dict):
            logger.error('CDSE Sentinel Catalog search returned invalid payload')
            return [], 'Invalid catalog response payload'

        features = data.get('features') or []
        items = [
            self._feature_to_stac_item(feature, collection_id)
            for feature in features
        ]
        next_token = self._extract_next_token(data)
        logger.info(
            'CDSE Sentinel Catalog search: '
            f'collection={collection_id}, items={len(items)}, next={next_token}'
        )
        return items, next_token

    def search(self, query: str = '', **kwargs) -> List[Dict]:
        """Backward-compatible wrapper returning only items.

        The connector manager uses ``search_unified()`` directly, but this
        method is kept for compatibility with older call sites.
        """
        legacy_bbox = query if isinstance(query, (list, tuple)) else None
        bbox = kwargs.get('bbox', legacy_bbox)
        collection = kwargs.get('collection') or kwargs.get('datasource')
        passthrough = {
            key: value
            for key, value in kwargs.items()
            if key not in {
                'bbox',
                'start_date',
                'end_date',
                'max_cloud_cover',
                'cloud_cover',
                'collection',
                'datasource',
                'text_query',
                'limit',
                'timeout',
                'query',
            }
        }
        items, _ = self.search_unified(
            bbox=bbox,
            start_date=kwargs.get('start_date'),
            end_date=kwargs.get('end_date'),
            max_cloud_cover=kwargs.get('max_cloud_cover', kwargs.get('cloud_cover')),
            collection=collection,
            text_query=kwargs.get('text_query') or kwargs.get('query'),
            limit=int(kwargs.get('limit', 100)),
            timeout=kwargs.get('timeout'),
            **passthrough,
        )
        return items

    def download(self, result_id: str, output_path: str, **kwargs) -> bool:
        """Download Sentinel data via WCS.

        Args:
            result_id: Result identifier from search()
            output_path: Local path to save the file
            **kwargs: Additional parameters
                (bbox, instance_id, datasource, etc.)

        Returns:
            True if download successful
        """
        if not self._ensure_oauth_session():
            return False

        instance_id = kwargs.get('instance_id')
        datasource = kwargs.get('datasource', 'S2L2A')
        aoi_bounds = kwargs.get('aoi_bounds')

        if not instance_id or not aoi_bounds:
            logger.error(
                "instance_id and aoi_bounds required for WCS download"
            )
            return False

        try:
            minx, miny, maxx, maxy = aoi_bounds

            # Build WCS GetCoverage request
            wcs_url = (
                f'{self.base_url}/ogc/wcs/{instance_id}'
                f'?service=WCS&version=2.0.1&request=GetCoverage'
                f'&coverageId={datasource}'
                f'&subset=x({minx},{maxx})'
                f'&subset=y({miny},{maxy})'
                f'&format=image/tiff'
            )

            logger.debug(f"WCS download: {wcs_url}")

            # Download file
            response = self.session.get(wcs_url, timeout=60, stream=True)
            response.raise_for_status()

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            logger.info(f"Downloaded to {output_path}")
            return True

        except Exception as exc:
            logger.error(f"WCS download failed: {exc}")
            return False

    def get_wms_uri(
            self,
            instance_id: str,
            layer_id: str,
            aoi_bounds: Tuple,
            date: Optional[str] = None,
            max_cc: int = 100,
            priority: str = 'mostRecent',
            crs: str = 'EPSG:3857') -> str:
        """Build WMS URI for QGIS layer.

        Args:
            instance_id: CDSE Sentinel instance ID
            layer_id: Layer ID (e.g., 'S2L2A')
            aoi_bounds: Bounding box (minx, miny, maxx, maxy)
            date: Acquisition date (ISO format)
            max_cc: Max cloud cover percentage
            priority: Image priority
                (mostRecent, leastRecent, leastCC)
            crs: Target CRS (default: EPSG:3857)

        Returns:
            WMS URI string for QgsRasterLayer
        """
        url = f'{self.base_url}/ogc/wms/{instance_id}'

        params = {
            'service': 'WMS',
            'version': '1.1.1',
            'request': 'GetMap',
            'layers': layer_id,
            'format': 'image/png',
            'transparent': 'true',
            'srs': crs,
        }

        if date:
            params['time'] = date

        ds_info = self.DATA_SOURCES.get(layer_id, {})
        if not ds_info.get('cloudless'):
            params['maxcc'] = str(max_cc)

        if priority:
            params['priority'] = priority

        # Build URI using QGIS QgsDataSourceUri for proper formatting
        if QGIS_AVAILABLE:
            uri = QgsDataSourceUri()
            uri.setParam('url', url)
            uri.setParam('service', 'WMS')
            uri.setParam('layers', layer_id)
            uri.setParam('crs', crs)
            if date:
                uri.setParam('time', date)
            encoded = uri.encodedUri()
            if isinstance(encoded, bytes):
                return encoded.decode('utf-8')
            return encoded
        else:
            # Fallback to string-based URI
            query_str = urlencode(params)
            return f'{url}?{query_str}'

    def get_wmts_uri(
            self,
            instance_id: str,
            layer_id: str,
            tilematrixset: str = 'EPSG:3857',
            date: Optional[str] = None,
            max_cc: int = 100,
            priority: str = 'mostRecent',
            crs: str = 'EPSG:3857') -> str:
        """Build WMTS URI for QGIS layer.

        Args:
            instance_id: CDSE Sentinel instance ID
            layer_id: Layer ID (e.g., 'S2L2A')
            tilematrixset: WMTS tile matrix set name
            date: Acquisition date (ISO format)
            max_cc: Max cloud cover percentage
            priority: Image priority
                (mostRecent, leastRecent, leastCC)
            crs: Target CRS (default: EPSG:3857)

        Returns:
            WMTS URI string for QgsRasterLayer
        """
        url = f'{self.base_url}/ogc/wmts/{instance_id}'

        params = {
            'service': 'WMTS',
            'version': '1.0.0',
            'request': 'GetTile',
            'layer': layer_id,
            'style': 'default',
            'format': 'image/png',
            'tilematrixset': tilematrixset,
            'crs': crs,
        }

        if date:
            params['time'] = date

        ds_info = self.DATA_SOURCES.get(layer_id, {})
        if not ds_info.get('cloudless'):
            params['maxcc'] = str(max_cc)

        if priority:
            params['priority'] = priority

        if QGIS_AVAILABLE:
            uri = QgsDataSourceUri()
            uri.setParam('url', url)
            uri.setParam('service', 'WMTS')
            uri.setParam('layer', layer_id)
            uri.setParam('tilematrixset', tilematrixset)
            uri.setParam('style', 'default')
            uri.setParam('format', 'image/png')
            uri.setParam('crs', crs)
            if date:
                uri.setParam('time', date)
            encoded = uri.encodedUri()
            if isinstance(encoded, bytes):
                return encoded.decode('utf-8')
            return encoded

        query_str = urlencode(params)
        return f'{url}?{query_str}'

    def get_wcs_url(
            self,
            instance_id: str,
            datasource: str,
            aoi_bounds: Tuple,
            date: Optional[str] = None,
            crs: str = 'EPSG:4326') -> str:
        """Build WCS URL for data download.

        Args:
            instance_id: CDSE Sentinel instance ID
            datasource: Data source (S1GRD, S2L2A, etc.)
            aoi_bounds: Bounding box (minx, miny, maxx, maxy)
            date: Acquisition date
            crs: Target CRS

        Returns:
            WCS URL for direct download
        """
        minx, miny, maxx, maxy = aoi_bounds

        url = f'{self.base_url}/ogc/wcs/{instance_id}'

        params = {
            'service': 'WCS',
            'version': '2.0.1',
            'request': 'GetCoverage',
            'coverageId': datasource,
            'subset=x': f'({minx},{maxx})',
            'subset=y': f'({miny},{maxy})',
            'format': 'image/tiff',
        }

        if date:
            params['time'] = date

        query_str = urlencode(params, safe='():,')
        return f'{url}?{query_str}'
