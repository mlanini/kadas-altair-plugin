"""Planet Catalog API connector.

Provides access to Planet catalog search via STAC Catalog API v1 endpoints.

Reference:
- https://docs.planet.com/develop/apis/catalog/reference/
"""

import json
import logging
from typing import Optional, List, Dict, Any, Tuple

from .base import ConnectorBase
from ..logger import get_logger

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
from qgis.PyQt.QtNetwork import QNetworkRequest

logger = get_logger('connectors.planet')


class PlanetConnector(ConnectorBase):
    """Planet Catalog API connector.

    Authentication:
    - OAuth2 Bearer access token (Authorization: Bearer <token>)

    Search endpoint:
    - POST /catalog/v1/search
    """

    DEFAULT_API_BASE = 'https://services.sentinel-hub.com'
    LANDING_PATH = '/catalog/v1'
    COLLECTIONS_PATH = '/catalog/v1/collections'
    SEARCH_PATH = '/catalog/v1/search'

    timeout_auth: float = 10.0
    timeout_search: float = 30.0

    def __init__(self):
        super().__init__()
        self.authenticated = False
        self.access_token: Optional[str] = None
        self._auth_header: Optional[str] = None
        self._api_base_url: str = self.DEFAULT_API_BASE
        self._collections_cache: Optional[List[Dict[str, Any]]] = None

    def _build_url(self, path: str) -> str:
        base = (self._api_base_url or self.DEFAULT_API_BASE).strip().rstrip('/')
        if not path.startswith('/'):
            path = '/' + path
        return f"{base}{path}"

    def _http_get(self, url: str, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """Make authenticated HTTP GET request using QGIS Network Manager."""
        if not self._auth_header:
            logger.error("Planet: not authenticated")
            return None

        try:
            logger.debug(f"Planet: HTTP GET {url}")

            request = QNetworkRequest(QUrl(url))
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            request.setRawHeader(b"Authorization", self._auth_header.encode())
            request.setRawHeader(b"User-Agent", b"KADAS-Altair-Plugin/1.0")
            request.setAttribute(QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.AlwaysNetwork)

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
                logger.error(f"Planet: request timeout after {timeout}s")
                return None

            if reply.error():
                error_code = reply.error()
                error_msg = reply.errorString()
                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                logger.error(f"Planet: network error ({error_code}): {error_msg} - HTTP {status_code}")
                return None

            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if status_code and status_code >= 400:
                logger.error(f"Planet: HTTP {status_code} error")
                return None

            data = reply.readAll().data().decode('utf-8')
            return json.loads(data) if data else {}

        except json.JSONDecodeError as e:
            logger.error(f"Planet: failed to parse JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Planet: HTTP GET failed: {e}")
            return None

    def _http_post(self, url: str, payload: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """Make authenticated HTTP POST request using QGIS Network Manager."""
        if not self._auth_header:
            logger.error("Planet: not authenticated")
            return None

        try:
            logger.debug(f"Planet: HTTP POST {url}")

            request = QNetworkRequest(QUrl(url))
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            request.setRawHeader(b"Authorization", self._auth_header.encode())
            request.setRawHeader(b"User-Agent", b"KADAS-Altair-Plugin/1.0")

            nam = QgsNetworkAccessManager.instance()
            json_data = json.dumps(payload).encode('utf-8')
            reply = nam.post(request, json_data)

            loop = QEventLoop()
            reply.finished.connect(loop.quit)

            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(int(timeout * 1000))

            loop.exec_()

            if not reply.isFinished():
                reply.abort()
                logger.error(f"Planet: request timeout after {timeout}s")
                return None

            if reply.error():
                error_code = reply.error()
                error_msg = reply.errorString()
                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                logger.error(f"Planet: network error ({error_code}): {error_msg} - HTTP {status_code}")
                return None

            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if status_code and status_code >= 400:
                logger.error(f"Planet: HTTP {status_code} error")
                return None

            data = reply.readAll().data().decode('utf-8')
            return json.loads(data) if data else {}

        except json.JSONDecodeError as e:
            logger.error(f"Planet: failed to parse JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Planet: HTTP POST failed: {e}")
            return None

    def authenticate(self, credentials: Optional[dict] = None, verify: bool = True) -> bool:
        """Authenticate using OAuth2 access token.

        Expected credentials:
        - access_token (required)
        - api_base_url (optional, default https://services.sentinel-hub.com)
        """
        if not credentials:
            logger.error('Planet: no credentials provided')
            self.authenticated = False
            return False

        access_token = str(credentials.get('access_token') or '').strip()
        if not access_token:
            logger.error('Planet: missing access_token in credentials')
            self.authenticated = False
            return False

        self.access_token = access_token
        self._auth_header = f"Bearer {self.access_token}"
        self._api_base_url = str(credentials.get('api_base_url') or self.DEFAULT_API_BASE).strip().rstrip('/')
        self._collections_cache = None

        if not verify:
            self.authenticated = True
            logger.debug('Planet: offline authentication accepted')
            return True

        try:
            logger.info('Planet: verifying access token...')
            landing = self._http_get(self._build_url(self.LANDING_PATH), timeout=self.timeout_auth)

            if landing is None:
                logger.error('Planet: token verification failed (request failed)')
                self.authenticated = False
                return False

            if landing.get('type') in ('Catalog', 'Collection') or 'links' in landing:
                self.authenticated = True
                logger.info('Planet: access token verified successfully')
                return True

            logger.error('Planet: unexpected response from Catalog API')
            self.authenticated = False
            return False

        except Exception as e:
            logger.error(f'Planet: authentication failed: {e}')
            self.authenticated = False
            return False

    def is_authenticated(self) -> bool:
        return self.authenticated

    def _discover_collections(self) -> List[Dict[str, Any]]:
        """Discover available collections from Catalog API."""
        if self._collections_cache is not None:
            return self._collections_cache

        response = self._http_get(self._build_url(self.COLLECTIONS_PATH), timeout=self.timeout_search)
        if response is None:
            logger.warning('Planet: failed to fetch collections')
            self._collections_cache = []
            return self._collections_cache

        collections = response.get('collections', [])
        if not isinstance(collections, list):
            logger.warning('Planet: invalid collections response format')
            self._collections_cache = []
            return self._collections_cache

        normalized: List[Dict[str, Any]] = []
        for collection in collections:
            if not isinstance(collection, dict):
                continue

            collection_id = str(collection.get('id', '')).strip()
            if not collection_id:
                continue

            summaries = collection.get('summaries', {}) if isinstance(collection.get('summaries', {}), dict) else {}
            gsd = None
            if isinstance(summaries.get('gsd'), list) and summaries.get('gsd'):
                gsd = summaries.get('gsd')[0]

            normalized.append({
                'id': collection_id,
                'title': collection.get('title') or collection_id,
                'description': collection.get('description') or '',
                'gsd': gsd,
                'asset_count': 0,
            })

        self._collections_cache = normalized
        return normalized

    def get_collections(self) -> List[Dict[str, Any]]:
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return []
        return self._discover_collections()

    def _extract_next_link(self, response: Dict[str, Any]) -> Optional[str]:
        links = response.get('links', [])
        if isinstance(links, list):
            for link in links:
                if not isinstance(link, dict):
                    continue
                if str(link.get('rel', '')).lower() == 'next':
                    href = str(link.get('href', '')).strip()
                    if href:
                        return href
        return None

    def search_unified(
        self,
        bbox=None,
        start_date=None,
        end_date=None,
        max_cloud_cover=None,
        collection=None,
        text_query=None,
        limit: int = 100,
    ) -> tuple:
        """Normalized entrypoint for ConnectorManager."""
        datetime_str: Optional[str] = None
        if start_date and end_date:
            datetime_str = f"{start_date}/{end_date}"
        elif start_date:
            datetime_str = f"{start_date}/.."
        elif end_date:
            datetime_str = f"../{end_date}"

        collections_list = [collection] if collection else None
        results = self.search(
            query=text_query or "",
            bbox=tuple(bbox) if bbox else None,
            datetime=datetime_str,
            collections=collections_list,
            max_cloud_cover=max_cloud_cover,
            limit=limit,
        )
        return results, None

    def search(
        self,
        query: str = "",
        bbox: Optional[Tuple[float, float, float, float]] = None,
        datetime: Optional[str] = None,
        collections: Optional[List[str]] = None,
        max_cloud_cover: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Search Planet Catalog API using POST /catalog/v1/search."""
        if not self.authenticated:
            logger.error('Planet: not authenticated')
            return []

        if query:
            logger.debug('Planet: text query is currently not mapped to Catalog filters and will be ignored')

        available_collections = self._discover_collections()
        available_ids = [str(c.get('id')) for c in available_collections if c.get('id')]

        if collections:
            selected_collections = [c for c in collections if c in available_ids] if available_ids else collections
        else:
            selected_collections = available_ids

        if not selected_collections:
            logger.error('Planet: no collections available/selected for Catalog search')
            return []

        requested_limit = max(1, int(limit))
        page_limit = min(requested_limit, 100)

        payload: Dict[str, Any] = {
            'collections': selected_collections,
            'limit': page_limit,
        }

        if bbox:
            payload['bbox'] = [bbox[0], bbox[1], bbox[2], bbox[3]]

        if datetime:
            payload['datetime'] = datetime

        if max_cloud_cover is not None:
            payload['filter'] = {
                'op': '<=',
                'args': [
                    {'property': 'eo:cloud_cover'},
                    float(max_cloud_cover),
                ],
            }
            payload['filter-lang'] = 'cql2-json'

        logger.info(
            f"Planet: searching catalog (collections={len(selected_collections)}, bbox={bbox}, "
            f"datetime={datetime}, limit={requested_limit})"
        )
        logger.debug(f"Planet: search payload: {json.dumps(payload, indent=2)}")

        search_url = self._build_url(self.SEARCH_PATH)
        results: List[Dict[str, Any]] = []

        try:
            response = self._http_post(search_url, payload, timeout=self.timeout_search)
            if response is None:
                logger.error('Planet: search request failed')
                return []

            visited_next_links = set()
            next_link = self._extract_next_link(response)

            while True:
                features = response.get('features', [])
                if isinstance(features, list):
                    for feature in features:
                        if len(results) >= requested_limit:
                            break
                        if isinstance(feature, dict):
                            results.append(self._feature_to_result(feature))

                if len(results) >= requested_limit:
                    break

                if not next_link or next_link in visited_next_links:
                    break

                visited_next_links.add(next_link)
                response = self._http_get(next_link, timeout=self.timeout_search)
                if response is None:
                    break

                next_link = self._extract_next_link(response)

            logger.info(f"Planet: search returned {len(results)} items")
            return results

        except Exception as e:
            logger.error(f'Planet: search failed: {e}')
            return []

    def _feature_to_result(self, feature: Dict[str, Any]) -> Dict[str, Any]:
        props = feature.get('properties', {})

        collection_id = feature.get('collection') or props.get('collection') or props.get('pl:item_type') or 'unknown'

        result = {
            'id': feature.get('id'),
            'title': f"{collection_id} - {feature.get('id', '')}",
            'bbox': feature.get('bbox'),
            'geometry': feature.get('geometry'),
            'assets': feature.get('assets', {}),
            'properties': props,
            'collection': collection_id,
            'stac_feature': feature,
            'is_collection': False,
        }

        if 'datetime' in props:
            result['datetime'] = props['datetime']
        if 'eo:cloud_cover' in props:
            result['cloud_percent'] = props['eo:cloud_cover']
        if 'gsd' in props:
            result['gsd'] = props['gsd']

        return result

    def get_tile_url(self, result: dict, z: int, x: int, y: int) -> str:
        """Get a tile/asset URL from a result item."""
        assets = result.get('assets', {})

        for key in ('visual', 'preview', 'data'):
            asset = assets.get(key)
            if isinstance(asset, dict) and asset.get('href'):
                return str(asset.get('href'))

        for asset in assets.values():
            if isinstance(asset, dict) and asset.get('href'):
                return str(asset.get('href'))

        return ''
