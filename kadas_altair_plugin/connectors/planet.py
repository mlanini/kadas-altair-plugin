"""Planet API connector.

Provides access to Planet imagery, basemap, and order services using the same
API key model as the official QGIS Planet plugin.
"""

import json
from base64 import b64encode
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from requests.auth import HTTPBasicAuth

from .base import ConnectorBase
from ..logger import get_logger
from ..utilities.qgis_network import qgis_request_json

logger = get_logger('connectors.planet')


class PlanetConnector(ConnectorBase):
    """Planet API connector.

    Authentication:
    - Planet API key, sent as HTTP Basic auth with an empty password.

    Search endpoint:
    - POST /data/v1/quick-search

    Basemap and order endpoints are exposed as helper methods to mirror the
    capabilities used by the official QGIS Planet plugin.
    """

    DEFAULT_API_BASE = 'https://api.planet.com'
    OPEN_STAC_CATALOG_URL = 'https://www.planet.com/data/stac/catalog.json'

    ITEM_TYPES_PATH = '/data/v1/item-types/'
    QUICK_SEARCH_PATH = '/data/v1/quick-search'
    MOSAICS_PATH = '/basemaps/v1/mosaics'
    SERIES_PATH = '/basemaps/v1/series'
    COMPUTE_ORDERS_PATH = '/compute/ops/orders/v2'
    TASKING_ORDERS_PATH = '/tasking/v2/orders/'
    TASKING_PRICING_PATH = '/tasking/v2/pricing/'
    TASKING_CAPTURES_PATH = '/tasking/v2/captures/'
    TASKING_URL = 'https://api.planet.com/tasking/v2/orders/'

    timeout_auth: float = 10.0
    timeout_search: float = 60.0

    def __init__(self):
        super().__init__()
        self.authenticated = False
        self.api_key: Optional[str] = None
        self.access_token: Optional[str] = None
        self._auth: Optional[HTTPBasicAuth] = None
        self._api_base_url: str = self.DEFAULT_API_BASE
        self._tasking_base_url: str = self.DEFAULT_API_BASE
        self._tasking_orders_path: str = self.TASKING_ORDERS_PATH
        self._tasking_pricing_path: str = self.TASKING_PRICING_PATH
        self._tasking_captures_path: str = self.TASKING_CAPTURES_PATH
        self._tasking_portal_url: str = self.TASKING_URL
        self._collections_cache: Optional[List[Dict[str, Any]]] = None
        self._open_stac_catalog_url: str = self.OPEN_STAC_CATALOG_URL
        self._open_stac_search_url: Optional[str] = None
        self._open_collections_cache: Optional[List[Dict[str, Any]]] = None

    def _build_url(self, path: str) -> str:
        base = (
            self._api_base_url or self.DEFAULT_API_BASE
        ).strip().rstrip('/')
        if not path.startswith('/'):
            path = '/' + path
        return f"{base}{path}"

    def _get_session(self) -> requests.Session:
        session = self.get_session()
        if session is None:
            session = requests.Session()
        return session

    def _build_tasking_url(self, path: str) -> str:
        base = (self._tasking_base_url or self.DEFAULT_API_BASE).strip().rstrip('/')
        clean_path = str(path or '').strip()
        if not clean_path:
            clean_path = self.TASKING_ORDERS_PATH
        if not clean_path.startswith('/'):
            clean_path = '/' + clean_path
        return f"{base}{clean_path}"

    def _request_json(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        if not self._auth:
            logger.error('Planet: not authenticated')
            return None

        session = self._get_session()
        auth_header = b64encode(
            f"{self.api_key or ''}:".encode('utf-8')
        ).decode('ascii')
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'KADAS-Altair-Plugin/1.0',
            'Authorization': f'Basic {auth_header}',
        }

        method_upper = str(method or 'GET').strip().upper()
        if method_upper in ('GET', 'POST'):
            data, qgis_error, status = qgis_request_json(
                method=method_upper,
                url=url,
                headers=headers,
                payload=payload,
                params=params,
                timeout=timeout,
            )
            if qgis_error is None:
                return data

            logger.warning(
                'Planet: QGIS network request failed for %s %s '
                '(status=%s), falling back to requests: %s',
                method_upper,
                url,
                status,
                qgis_error,
            )

        request_kwargs: Dict[str, Any] = {
            'auth': self._auth,
            'headers': headers,
            'timeout': timeout,
        }

        if params:
            request_kwargs['params'] = params
        if payload is not None:
            request_kwargs['json'] = payload

        try:
            logger.debug('Planet: %s %s', method, url)
            response = session.request(method, url, **request_kwargs)
            if response.status_code >= 400:
                logger.error(
                    'Planet: HTTP %s error for %s %s',
                    response.status_code,
                    method,
                    url,
                )
                return None

            if not response.text:
                return {}

            return response.json()
        except ValueError as exc:
            logger.error('Planet: failed to parse JSON from %s: %s', url, exc)
            return None
        except requests.RequestException as exc:
            logger.error('Planet: request failed for %s: %s', url, exc)
            return None

    def _request_open_stac_json(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        """Request JSON from Planet open STAC endpoints (no auth required)."""
        session = self._get_session()
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'KADAS-Altair-Plugin/1.0',
        }

        method_upper = str(method or 'GET').strip().upper()
        if method_upper in ('GET', 'POST'):
            data, qgis_error, status = qgis_request_json(
                method=method_upper,
                url=url,
                headers=headers,
                payload=payload,
                params=params,
                timeout=timeout,
            )
            if qgis_error is None:
                return data

            logger.warning(
                'Planet open STAC: QGIS network request failed for %s %s '
                '(status=%s), falling back to requests: %s',
                method_upper,
                url,
                status,
                qgis_error,
            )

        request_kwargs: Dict[str, Any] = {
            'headers': headers,
            'timeout': timeout,
        }
        if params:
            request_kwargs['params'] = params
        if payload is not None:
            request_kwargs['json'] = payload

        try:
            response = session.request(method, url, **request_kwargs)
            if response.status_code >= 400:
                logger.error(
                    'Planet open STAC: HTTP %s error for %s %s',
                    response.status_code,
                    method,
                    url,
                )
                return None

            if not response.text:
                return {}

            return response.json()
        except ValueError as exc:
            logger.error(
                'Planet open STAC: failed to parse JSON from %s: %s',
                url,
                exc,
            )
            return None
        except requests.RequestException as exc:
            logger.error(
                'Planet open STAC: request failed for %s: %s',
                url,
                exc,
            )
            return None

    def _build_geometry_filter(
        self,
        bbox: Tuple[float, float, float, float],
    ) -> Dict[str, Any]:
        min_lon, min_lat, max_lon, max_lat = bbox
        geometry = {
            'type': 'Polygon',
            'coordinates': [[
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]],
        }
        return {
            'type': 'GeometryFilter',
            'field_name': 'geometry',
            'config': geometry,
        }

    def _build_date_filter(
        self,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if not start_date and not end_date:
            return None

        config: Dict[str, Any] = {}
        if start_date:
            config['gte'] = start_date
        if end_date:
            config['lte'] = end_date

        return {
            'type': 'DateRangeFilter',
            'field_name': 'acquired',
            'config': config,
        }

    def _build_cloud_filter(
        self,
        max_cloud_cover: Optional[float],
    ) -> Optional[Dict[str, Any]]:
        if max_cloud_cover is None:
            return None

        return {
            'type': 'RangeFilter',
            'field_name': 'cloud_cover',
            'config': {'lte': float(max_cloud_cover)},
        }

    def authenticate(
        self,
        credentials: Optional[dict] = None,
        verify: bool = True,
    ) -> bool:
        """Authenticate with a Planet API key.

        Expected credentials:
        - api_key or access_token (required)
        - api_base_url (optional, default https://api.planet.com)
        """
        if not credentials:
            logger.error('Planet: no credentials provided')
            self.authenticated = False
            return False

        api_key = str(
            credentials.get('api_key')
            or credentials.get('access_token')
            or ''
        ).strip()
        if not api_key:
            logger.error('Planet: missing api_key in credentials')
            self.authenticated = False
            return False

        self.api_key = api_key
        self.access_token = api_key
        self._auth = HTTPBasicAuth(self.api_key, '')
        self._api_base_url = str(
            credentials.get('api_base_url') or self.DEFAULT_API_BASE
        ).strip().rstrip('/')
        self._tasking_base_url = str(
            credentials.get('tasking_base_url')
            or credentials.get('api_base_url')
            or self.DEFAULT_API_BASE
        ).strip().rstrip('/')
        self._tasking_orders_path = str(
            credentials.get('tasking_orders_path') or self.TASKING_ORDERS_PATH
        ).strip() or self.TASKING_ORDERS_PATH
        self._tasking_pricing_path = str(
            credentials.get('tasking_pricing_path') or self.TASKING_PRICING_PATH
        ).strip() or self.TASKING_PRICING_PATH
        self._tasking_captures_path = str(
            credentials.get('tasking_captures_path') or self.TASKING_CAPTURES_PATH
        ).strip() or self.TASKING_CAPTURES_PATH
        self._tasking_portal_url = str(
            credentials.get('tasking_url') or self.TASKING_URL
        ).strip() or self.TASKING_URL
        self._open_stac_catalog_url = str(
            credentials.get('open_stac_catalog_url')
            or self.OPEN_STAC_CATALOG_URL
        ).strip() or self.OPEN_STAC_CATALOG_URL
        self._collections_cache = None
        self._open_collections_cache = None
        self._open_stac_search_url = None

        if not verify:
            self.authenticated = True
            logger.debug('Planet: offline authentication accepted')
            return True

        try:
            logger.info('Planet: verifying API key...')
            response = self._request_json(
                'GET',
                self._build_url(self.ITEM_TYPES_PATH),
                timeout=self.timeout_auth,
            )

            if response is None:
                logger.error(
                    'Planet: token verification failed (request failed)'
                )
                self.authenticated = False
                return False

            item_types = (
                response.get('item_types', [])
                if isinstance(response, dict)
                else []
            )
            if item_types or response:
                self.authenticated = True
                logger.info('Planet: API key verified successfully')
                return True

            logger.error('Planet: unexpected response from Planet API')
            self.authenticated = False
            return False

        except Exception as e:
            logger.error(f'Planet: authentication failed: {e}')
            self.authenticated = False
            return False

    def is_authenticated(self) -> bool:
        return self.authenticated

    def _discover_collections(self) -> List[Dict[str, Any]]:
        """Discover available Planet item types."""
        if self._collections_cache is not None:
            return self._collections_cache

        response = self._request_json(
            'GET',
            self._build_url(self.ITEM_TYPES_PATH),
            timeout=self.timeout_search,
        )
        if response is None:
            logger.warning('Planet: failed to fetch item types')
            self._collections_cache = []
            return self._collections_cache

        item_types = (
            response.get('item_types', [])
            if isinstance(response, dict)
            else []
        )
        if not isinstance(item_types, list):
            logger.warning('Planet: invalid item types response format')
            self._collections_cache = []
            return self._collections_cache

        normalized: List[Dict[str, Any]] = []
        for item_type in item_types:
            if not isinstance(item_type, dict):
                continue

            item_type_id = str(item_type.get('id', '')).strip()
            if not item_type_id:
                continue

            display_name = str(
                item_type.get('display_name')
                or item_type.get('name')
                or item_type_id
            )
            description = str(item_type.get('description') or '')
            gsd = item_type.get('gsd')
            asset_types = item_type.get('asset_types', [])
            asset_count = (
                len(asset_types) if isinstance(asset_types, list) else 0
            )

            normalized.append({
                'id': item_type_id,
                'title': display_name,
                'description': description,
                'gsd': gsd,
                'asset_count': asset_count,
                'raw': item_type,
            })

        self._collections_cache = normalized
        return normalized

    def _discover_open_stac_collections(self) -> List[Dict[str, Any]]:
        """Discover Planet open-data STAC collections from catalog links."""
        if self._open_collections_cache is not None:
            return self._open_collections_cache

        catalog_url = (self._open_stac_catalog_url or self.OPEN_STAC_CATALOG_URL).strip()
        if not catalog_url:
            self._open_collections_cache = []
            return self._open_collections_cache

        catalog = self._request_open_stac_json(
            'GET',
            catalog_url,
            timeout=self.timeout_search,
        )
        if not isinstance(catalog, dict):
            logger.warning('Planet open STAC: failed to fetch catalog')
            self._open_collections_cache = []
            return self._open_collections_cache

        links = catalog.get('links', [])
        if not isinstance(links, list):
            links = []

        search_href: Optional[str] = None
        collections_href: Optional[str] = None
        child_links: List[Dict[str, Any]] = []

        for link in links:
            if not isinstance(link, dict):
                continue
            rel = str(link.get('rel', '')).lower()
            href = str(link.get('href', '')).strip()
            if not href:
                continue
            absolute_href = urljoin(catalog_url, href)
            if rel == 'search' and not search_href:
                search_href = absolute_href
            elif rel == 'collections' and not collections_href:
                collections_href = absolute_href
            elif rel in ('child', 'collection'):
                child_links.append({
                    'id': str(link.get('title') or link.get('name') or href),
                    'title': str(link.get('title') or link.get('name') or href),
                    'description': str(link.get('description') or ''),
                    'href': absolute_href,
                    'source': 'planet_open_stac',
                })

        if search_href:
            self._open_stac_search_url = search_href
        elif catalog_url.endswith('/catalog.json'):
            self._open_stac_search_url = catalog_url[:-len('catalog.json')] + 'search'

        normalized: List[Dict[str, Any]] = []

        if collections_href:
            collections_doc = self._request_open_stac_json(
                'GET',
                collections_href,
                timeout=self.timeout_search,
            )
            collections = (
                collections_doc.get('collections', [])
                if isinstance(collections_doc, dict)
                else []
            )
            if isinstance(collections, list):
                for collection in collections:
                    if not isinstance(collection, dict):
                        continue
                    collection_id = str(collection.get('id', '')).strip()
                    if not collection_id:
                        continue
                    normalized.append({
                        'id': collection_id,
                        'title': str(collection.get('title') or collection_id),
                        'description': str(collection.get('description') or ''),
                        'raw': collection,
                        'source': 'planet_open_stac',
                    })

        if not normalized and child_links:
            normalized = child_links

        self._open_collections_cache = normalized
        return normalized

    def get_collections(self) -> List[Dict[str, Any]]:
        collections: List[Dict[str, Any]] = []

        if self.authenticated:
            collections.extend(self._discover_collections())
        else:
            logger.info('Planet: API key not set; exposing only open STAC collections')

        open_collections = self._discover_open_stac_collections()
        if open_collections:
            collections.extend(open_collections)

        return collections

    def _extract_next_link(self, response: Dict[str, Any]) -> Optional[str]:
        # Planet quick-search can expose paging either as STAC links or
        # under legacy _links/_next keys.
        legacy_next = response.get('_next')
        if isinstance(legacy_next, str) and legacy_next.strip():
            return legacy_next.strip()

        legacy_links = response.get('_links')
        if isinstance(legacy_links, dict):
            next_value = legacy_links.get('_next') or legacy_links.get('next')
            if isinstance(next_value, str) and next_value.strip():
                return next_value.strip()

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
        """Search Planet imagery via authenticated API and open STAC catalogues."""

        if query:
            logger.debug(
                'Planet: text query is not mapped to Planet quick-search '
                'filters and is only partially supported by open STAC backends'
            )

        commercial_ids: List[str] = []
        if self.authenticated:
            commercial_ids = [
                str(c.get('id'))
                for c in self._discover_collections()
                if c.get('id')
            ]

        open_collections = self._discover_open_stac_collections()
        open_ids = [
            str(c.get('id'))
            for c in open_collections
            if c.get('id')
        ]

        available_ids = list(dict.fromkeys(commercial_ids + open_ids))

        if collections:
            if available_ids:
                selected_collections = [
                    c for c in collections if c in available_ids
                ]
            else:
                selected_collections = collections
        else:
            selected_collections = available_ids

        if not selected_collections:
            logger.error('Planet: no item types available/selected for search')
            return []

        selected_commercial = [
            collection_id
            for collection_id in selected_collections
            if collection_id in commercial_ids
        ]
        selected_open = [
            collection_id
            for collection_id in selected_collections
            if collection_id in open_ids
        ]

        requested_limit = max(1, int(limit))
        results: List[Dict[str, Any]] = []

        if selected_commercial:
            if self.authenticated:
                commercial_results = self._search_commercial_api(
                    collections=selected_commercial,
                    bbox=bbox,
                    datetime=datetime,
                    max_cloud_cover=max_cloud_cover,
                    limit=requested_limit,
                )
                results.extend(commercial_results)
            else:
                logger.warning(
                    'Planet: authenticated item types requested but API key is missing; '
                    'skipping commercial Planet API search'
                )

        remaining = max(0, requested_limit - len(results))
        if selected_open and remaining > 0:
            open_results = self._search_open_stac(
                collections=selected_open,
                bbox=bbox,
                datetime=datetime,
                max_cloud_cover=max_cloud_cover,
                limit=remaining,
            )
            results.extend(open_results)

        return results[:requested_limit]

    def _search_commercial_api(
        self,
        collections: List[str],
        bbox: Optional[Tuple[float, float, float, float]],
        datetime: Optional[str],
        max_cloud_cover: Optional[float],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Search authenticated Planet API (POST /data/v1/quick-search)."""
        requested_limit = max(1, int(limit))
        page_limit = min(requested_limit, 100)

        filters: List[Dict[str, Any]] = []

        if bbox:
            filters.append(self._build_geometry_filter(bbox))

        if datetime:
            start_dt = None
            end_dt = None
            if '/' in datetime:
                start_dt, end_dt = datetime.split('/', 1)
                start_dt = start_dt if start_dt not in ['', '..'] else None
                end_dt = end_dt if end_dt not in ['', '..'] else None
            else:
                start_dt = datetime
            date_filter = self._build_date_filter(start_dt, end_dt)
            if date_filter is not None:
                filters.append(date_filter)

        cloud_filter = self._build_cloud_filter(max_cloud_cover)
        if cloud_filter is not None:
            filters.append(cloud_filter)

        payload: Dict[str, Any] = {
            'item_types': collections,
            'limit': page_limit,
        }

        if filters:
            payload['filter'] = (
                filters[0]
                if len(filters) == 1
                else {'type': 'AndFilter', 'config': filters}
            )

        logger.info(
            f"Planet: searching Planet API (item_types="
            f"{len(collections)}, bbox={bbox}, datetime={datetime}, "
            f"limit={requested_limit})"
        )
        logger.debug(
            'Planet: search payload: %s',
            json.dumps(payload, indent=2),
        )

        search_url = self._build_url(self.QUICK_SEARCH_PATH)
        results: List[Dict[str, Any]] = []

        response = self._request_json(
            'POST',
            search_url,
            payload=payload,
            timeout=self.timeout_search,
        )
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
            response = self._request_json(
                'GET',
                next_link,
                timeout=self.timeout_search,
            )
            if response is None:
                break

            next_link = self._extract_next_link(response)

        logger.info('Planet: commercial API search returned %d items', len(results))
        return results

    def _search_open_stac(
        self,
        collections: List[str],
        bbox: Optional[Tuple[float, float, float, float]],
        datetime: Optional[str],
        max_cloud_cover: Optional[float],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Search Planet open-data STAC API when available."""
        _ = self._discover_open_stac_collections()
        search_url = str(self._open_stac_search_url or '').strip()
        if not search_url:
            logger.warning('Planet open STAC: search endpoint not advertised by catalog')
            return []

        requested_limit = max(1, int(limit))
        payload: Dict[str, Any] = {
            'limit': min(requested_limit, 1000),
            'collections': collections,
        }

        if bbox:
            payload['bbox'] = [
                float(bbox[0]),
                float(bbox[1]),
                float(bbox[2]),
                float(bbox[3]),
            ]
        if datetime:
            payload['datetime'] = datetime

        if max_cloud_cover is not None:
            try:
                threshold = float(max_cloud_cover)
                if threshold <= 1.0:
                    threshold *= 100.0
                payload['query'] = {
                    'eo:cloud_cover': {'lte': threshold},
                }
            except Exception:
                pass

        logger.info(
            'Planet open STAC: searching %s (collections=%d, limit=%d)',
            search_url,
            len(collections),
            requested_limit,
        )

        response = self._request_open_stac_json(
            'POST',
            search_url,
            payload=payload,
            timeout=self.timeout_search,
        )
        if response is None:
            logger.error('Planet open STAC: search request failed')
            return []

        results: List[Dict[str, Any]] = []
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
            response = self._request_open_stac_json(
                'GET',
                next_link,
                timeout=self.timeout_search,
            )
            if response is None:
                break

            next_link = self._extract_next_link(response)

        logger.info('Planet open STAC: search returned %d items', len(results))
        return results

    def _feature_to_result(self, feature: Dict[str, Any]) -> Dict[str, Any]:
        props = feature.get('properties', {})

        collection_id = (
            feature.get('collection')
            or props.get('collection')
            or props.get('item_type')
            or props.get('pl:item_type')
            or 'unknown'
        )

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
        if 'cloud_cover' in props:
            result['cloud_percent'] = props['cloud_cover']
        elif 'eo:cloud_cover' in props:
            result['cloud_percent'] = props['eo:cloud_cover']
        if 'gsd' in props:
            result['gsd'] = props['gsd']
        if 'acquired' in props:
            result['acquired'] = props['acquired']

        return result

    def get_tile_url(self, result: dict, z: int, x: int, y: int) -> str:
        """Get a tile/asset URL from a result item."""
        assets = result.get('assets', {})

        for key in ('visual', 'preview', 'thumbnail', 'analytic', 'data'):
            asset = assets.get(key)
            if isinstance(asset, dict) and asset.get('href'):
                return str(asset.get('href'))

        for asset in assets.values():
            if isinstance(asset, dict) and asset.get('href'):
                return str(asset.get('href'))

        return ''

    def list_mosaic_series(
        self,
        name_contains: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return []

        params: Dict[str, Any] = {}
        if name_contains:
            params['name__contains'] = name_contains

        response = self._request_json(
            'GET',
            self._build_url(self.SERIES_PATH),
            params=params,
            timeout=self.timeout_search,
        )
        if not response:
            return []
        return response.get('mosaics') or response.get('series') or []

    def get_mosaics(
        self,
        name_contains: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return []

        params: Dict[str, Any] = {'v': '1.5', '_page_size': 10000}
        if name_contains:
            params['name__contains'] = name_contains

        response = self._request_json(
            'GET',
            self._build_url(self.MOSAICS_PATH),
            params=params,
            timeout=self.timeout_search,
        )
        if not response:
            return []
        return response.get('mosaics') or response.get('collections') or []

    def get_quads_for_mosaic(
        self,
        mosaic: Any,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        minimal: bool = False,
    ) -> List[Dict[str, Any]]:
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return []

        mosaic_id = mosaic if isinstance(mosaic, str) else mosaic.get('id')
        if not mosaic_id:
            return []

        params: Dict[str, Any] = {'v': '1.5'}
        if bbox:
            params['bbox'] = f'{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}'
        if minimal:
            params['minimal'] = 'true'

        response = self._request_json(
            'GET',
            self._build_url(f'{self.MOSAICS_PATH}/{mosaic_id}/quads'),
            params=params,
            timeout=self.timeout_search,
        )
        if not response:
            return []
        return response.get('quads', [])

    def get_items_for_quad(
        self,
        mosaicid: str,
        quadid: str,
    ) -> List[Dict[str, Any]]:
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return []

        response = self._request_json(
            'GET',
            self._build_url(
                f'{self.MOSAICS_PATH}/{mosaicid}/quads/{quadid}/items'
            ),
            timeout=self.timeout_search,
        )
        if not response:
            return []
        return response.get('items', [])

    def create_order(
        self,
        request: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return None

        return self._request_json(
            'POST',
            self._build_url(self.COMPUTE_ORDERS_PATH),
            payload=request,
            timeout=self.timeout_search,
        )

    def create_tasking_order(
        self,
        request: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Create Planet Tasking API order (POST /tasking/v2/orders/)."""
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return None

        return self._request_json(
            'POST',
            self._build_tasking_url(self._tasking_orders_path),
            payload=request,
            timeout=self.timeout_search,
        )

    def list_tasking_orders(
        self,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """List Planet Tasking API orders (GET /tasking/v2/orders/)."""
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return None

        return self._request_json(
            'GET',
            self._build_tasking_url(self._tasking_orders_path),
            params=params,
            timeout=self.timeout_search,
        )

    def get_tasking_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve one Planet tasking order by UUID."""
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return None

        oid = str(order_id or '').strip()
        if not oid:
            return None

        base_url = self._build_tasking_url(self._tasking_orders_path).rstrip('/')
        return self._request_json('GET', f'{base_url}/{oid}', timeout=self.timeout_search)

    def cancel_tasking_order(self, order_id: str) -> bool:
        """Cancel Planet tasking order (DELETE /tasking/v2/orders/{id})."""
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return False

        oid = str(order_id or '').strip()
        if not oid:
            return False

        base_url = self._build_tasking_url(self._tasking_orders_path).rstrip('/')
        response = self._request_json('DELETE', f'{base_url}/{oid}', timeout=self.timeout_search)
        return response is not None

    def estimate_tasking_pricing(
        self,
        request: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Estimate Planet tasking pricing (POST /tasking/v2/pricing/)."""
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return None

        return self._request_json(
            'POST',
            self._build_tasking_url(self._tasking_pricing_path),
            payload=request,
            timeout=self.timeout_search,
        )

    def list_tasking_captures(
        self,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """List Planet tasking captures (GET /tasking/v2/captures/)."""
        if not self.authenticated:
            logger.warning('Planet: not authenticated')
            return None

        return self._request_json(
            'GET',
            self._build_tasking_url(self._tasking_captures_path),
            params=params,
            timeout=self.timeout_search,
        )

    def tasking_url(self) -> str:
        return self._tasking_portal_url or self._build_tasking_url(self._tasking_orders_path)
