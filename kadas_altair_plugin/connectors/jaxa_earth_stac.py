"""JAXA Earth STAC Connector for KADAS Altair

Provides archive search over JAXA Earth Observation data via the public
COG-STAC catalog hosted at data.earth.jaxa.jp.

Data Source: JAXA Earth Observation Research Center (EORC)
- STAC Catalog root: https://data.earth.jaxa.jp/stac/cog/v1/catalog.json
- Catalog Browser:   https://data.earth.jaxa.jp/
- Python API docs:   https://data.earth.jaxa.jp/api/python/index.html
- MIERUNE QGIS ref:  https://github.com/MIERUNE/qgis-jaxa-earth-plugin

Available datasets include (non-exhaustive):
  - ALOS/PRISM AW3D30  : Global 30 m DSM (elevation)
  - ALOS-2/PALSAR-2    : SAR backscatter, mosaic products
  - GCOM-C/SGLI        : Optical (LST, NDVI, ocean colour, …)
  - GPM IMERG          : Global precipitation estimates
  - MODIS & Himawari   : Atmospheric / land-surface products

Authentication: NOT required — all datasets are openly accessible.

Result format: STAC-compatible item dicts augmented with:
  _provider   : 'JAXA Earth'
  _connector  : 'jaxa_earth_stac'
  _satellite  : sensor / collection title
  _asset_href : URL of the selected COG asset (first data band)
  geometry    : GeoJSON geometry
  bbox        : [west, south, east, north]
  properties  : standard STAC properties (datetime, …)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

try:
    from qgis.PyQt.QtCore import QByteArray, QEventLoop, QTimer, QUrl, QSettings
    from qgis.PyQt.QtNetwork import QNetworkRequest
    from qgis.core import QgsNetworkAccessManager, QgsBlockingNetworkRequest
    QGIS_AVAILABLE = True
except ImportError:
    QSettings = None
    QGIS_AVAILABLE = False

from .base import ConnectorBase
from ..logger import get_logger
from ..utilities.qgis_network import qgis_request_json

logger = get_logger('connectors.jaxa_earth_stac')

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CATALOG_URL = 'https://data.earth.jaxa.jp/stac/cog/v1/catalog.json'
STAC_API_ROOT = 'https://data.earth.jaxa.jp/stac/cog/v1/'
# Standard STAC API search endpoint (may not be supported — we fall back to
# catalog navigation if the server returns 404 / 405)
STAC_SEARCH_URL = 'https://data.earth.jaxa.jp/stac/cog/v1/search'

CATALOG_URL_KEY = 'AltairEOData/jaxa_catalog_url'
SEARCH_URL_KEY = 'AltairEOData/jaxa_search_url'
TASKING_BASE_KEY = 'AltairEOData/jaxa_tasking_base_url'
TASKING_CREATE_PATH_KEY = 'AltairEOData/jaxa_tasking_create_path'
TASKING_LIST_PATH_KEY = 'AltairEOData/jaxa_tasking_list_path'
TASKING_TOKEN_KEY = 'AltairEOData/jaxa_tasking_access_token'

# Maximum number of collection-level catalog items we'll inspect when doing
# a catalog-walk search (safety cap to avoid run-away HTTP calls)
_MAX_CATALOG_ITEMS_WALK = 500


class JaxaEarthStacConnector(ConnectorBase):
    """Public STAC connector for JAXA Earth Observation data (no auth required).

    Supports:
    - BBOX-filtered search
    - Date-range filtering
    - Optional collection selection
    - Cloud Optimized GeoTIFF (COG) asset links

    Search strategy
    ---------------
    1. POST to ``STAC_SEARCH_URL`` (standard STAC API /search).
    2. If the endpoint is unavailable, fall back to walking the catalog JSON
       hierarchy and filtering items client-side.
    """

    # -----------------------------------------------------------------------
    # Construction / authentication
    # -----------------------------------------------------------------------

    def __init__(self):
        super().__init__()
        self._catalog_cache: Optional[Dict[str, Any]] = None
        self._collections_cache: Optional[List[Dict[str, Any]]] = None
        # Whether the server supports the standard STAC /search endpoint
        self._has_search_api: Optional[bool] = None
        self._catalog_url: str = CATALOG_URL
        self._search_url: str = STAC_SEARCH_URL
        self._tasking_base_url: str = ''
        self._tasking_create_path: str = '/tasking/v2/requests'
        self._tasking_list_path: str = '/tasking/v2/requests'
        self._tasking_access_token: str = ''
        self._last_post_error: str = ''
        self._load_settings_defaults()
        logger.info('JaxaEarthStacConnector initialised')

    def _load_settings_defaults(self) -> None:
        if QSettings is None:
            return
        try:
            settings = QSettings()
            self._catalog_url = str(settings.value(CATALOG_URL_KEY, CATALOG_URL) or CATALOG_URL).strip()
            self._search_url = str(settings.value(SEARCH_URL_KEY, STAC_SEARCH_URL) or STAC_SEARCH_URL).strip()
            self._tasking_base_url = str(settings.value(TASKING_BASE_KEY, '') or '').strip().rstrip('/')
            self._tasking_create_path = str(
                settings.value(TASKING_CREATE_PATH_KEY, '/tasking/v2/requests')
                or '/tasking/v2/requests'
            ).strip()
            self._tasking_list_path = str(
                settings.value(TASKING_LIST_PATH_KEY, '/tasking/v2/requests')
                or '/tasking/v2/requests'
            ).strip()
            self._tasking_access_token = str(settings.value(TASKING_TOKEN_KEY, '') or '').strip()
        except Exception as exc:
            logger.debug(f'JAXA settings defaults unavailable: {exc}')

    def authenticate(self, credentials: Optional[Dict] = None) -> bool:
        """Verify that the JAXA catalog is reachable (no credentials needed)."""
        credentials = credentials or {}
        self._catalog_url = str(credentials.get('catalog_url') or credentials.get('base_url') or self._catalog_url or CATALOG_URL).strip()
        self._search_url = str(credentials.get('search_url') or self._search_url or STAC_SEARCH_URL).strip()
        self._tasking_base_url = str(credentials.get('tasking_base_url') or self._tasking_base_url or '').strip().rstrip('/')
        self._tasking_create_path = str(
            credentials.get('tasking_create_path') or self._tasking_create_path or '/tasking/v2/requests'
        ).strip()
        self._tasking_list_path = str(
            credentials.get('tasking_list_path') or self._tasking_list_path or '/tasking/v2/requests'
        ).strip()
        token = str(
            credentials.get('tasking_access_token')
            or credentials.get('access_token')
            or self._tasking_access_token
            or ''
        ).strip()
        self._tasking_access_token = token

        logger.info('Authenticating JAXA Earth STAC connector (public catalog)…')
        cat = self._fetch_json(self._catalog_url, timeout=15.0)
        if cat:
            logger.info('✅  JAXA Earth STAC catalog reachable')
            self._catalog_cache = cat
            return True
        logger.error('❌  Unable to reach JAXA Earth STAC catalog')
        return False

    # -----------------------------------------------------------------------
    # Main search entry-point
    # -----------------------------------------------------------------------

    def search_unified(
        self,
        bbox: Optional[List[float]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_cloud_cover: Optional[float] = None,
        collection: Optional[str] = None,
        text_query: Optional[str] = None,
        timeout: Optional[float] = None,
        limit: int = 100,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Search JAXA Earth STAC for imagery.

        Args:
            bbox: [west, south, east, north] in WGS-84, or None for global.
            start_date: ``YYYY-MM-DD`` string, or None.
            end_date:   ``YYYY-MM-DD`` string, or None.
            max_cloud_cover: Ignored (JAXA does not expose cloud-cover metadata
                             consistently across its multi-sensor catalogue).
            collection: Collection ID to restrict search, or None (all).
            text_query: Ignored.
            limit: Maximum results to return.

        Returns:
            ``(items, next_token_or_error)``  — items is a list of STAC-like
            dicts; next_token is None on success or an error string on failure.
        """
        logger.info(
            f'JAXA search | bbox={bbox} | dates={start_date}→{end_date} '
            f'| collection={collection} | limit={limit}'
        )

        try:
            request_timeout = float(timeout) if timeout is not None else 20.0
        except (TypeError, ValueError):
            request_timeout = 20.0
        request_timeout = max(5.0, min(60.0, request_timeout))

        # Build datetime interval string
        datetime_interval = self._build_datetime_interval(start_date, end_date)

        # Try STAC /search API first (fast server-side filtering)
        if self._has_search_api is not False:
            items, err = self._search_via_api(
                bbox,
                datetime_interval,
                collection,
                limit,
                request_timeout,
            )
            if items is not None:
                self._has_search_api = True
                logger.info(f'JAXA /search API returned {len(items)} items')
                return items, None
            if err and 'not supported' not in (err or '').lower():
                # Transient network error — fast-fail instead of expensive
                # catalog walk that can freeze search UX.
                logger.info('JAXA /search unavailable for this request, falling back to catalog-walk: %s', err)
                return [], err

        # Fall back to catalog-walk
        self._has_search_api = False
        logger.info('JAXA falling back to catalog-walk search')
        items, err = self._search_via_catalog_walk(
            bbox, datetime_interval, collection, limit, request_timeout
        )
        if items is None:
            return [], err or 'JAXA search failed'
        logger.info(f'JAXA catalog-walk returned {len(items)} items')
        return items, None

    # -----------------------------------------------------------------------
    # Strategy 1 — standard STAC /search API (POST)
    # -----------------------------------------------------------------------

    def _search_via_api(
        self,
        bbox: Optional[List[float]],
        datetime_interval: Optional[str],
        collection: Optional[str],
        limit: int,
        timeout: float,
    ) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """POST to the STAC search endpoint.  Returns (None, err) if the
        endpoint is not available so that the caller can fall back."""

        body: Dict[str, Any] = {'limit': min(limit, 1000)}
        if bbox:
            body['bbox'] = bbox
        if datetime_interval:
            body['datetime'] = datetime_interval
        if collection:
            body['collections'] = [collection]

        data = self._post_json(self._search_url or STAC_SEARCH_URL, body, timeout=timeout)
        if data is None:
            detail = (self._last_post_error or '').strip()
            if detail.lower().startswith('http 404') or detail.lower().startswith('http 405'):
                return None, f'search endpoint not supported ({detail})'
            return None, f'search endpoint not available ({detail or "unknown error"})'

        raw_items = data.get('features') or data.get('items') or []
        items = [self._normalise_item(i) for i in raw_items]
        return items, None

    # -----------------------------------------------------------------------
    # Strategy 2 — catalog-walk (navigate STAC JSON hierarchy)
    # -----------------------------------------------------------------------

    def _search_via_catalog_walk(
        self,
        bbox: Optional[List[float]],
        datetime_interval: Optional[str],
        collection_filter: Optional[str],
        limit: int,
        timeout: float,
    ) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """Walk the STAC catalog hierarchy and collect matching items."""

        # Load root catalog
        cat = self._catalog_cache or self._fetch_json(self._catalog_url or CATALOG_URL, timeout=timeout)
        if not cat:
            return None, 'Failed to fetch JAXA root catalog'
        self._catalog_cache = cat

        # Collect child (collection) URLs
        child_links = [
            lnk['href']
            for lnk in (cat.get('links') or [])
            if lnk.get('rel') in ('child', 'collection')
        ]
        if not child_links:
            return None, 'No collections found in JAXA root catalog'

        # Optionally filter by requested collection id
        if collection_filter:
            child_links = [u for u in child_links if collection_filter in u]

        collected: List[Dict] = []
        for child_url in child_links:
            if len(collected) >= limit:
                break
            child_url = self._resolve_url(self._catalog_url or CATALOG_URL, child_url)
            child_doc = self._fetch_json(child_url, timeout=timeout)
            if not child_doc:
                continue

            # Collect item links from this collection (and sub-catalogs)
            item_links = self._collect_item_links(
                child_url, child_doc, remaining=limit - len(collected), request_timeout=timeout
            )

            for item_url in item_links:
                if len(collected) >= limit:
                    break
                item = self._fetch_json(item_url, timeout=timeout)
                if not item:
                    continue
                if bbox and not self._bbox_intersects(item, bbox):
                    continue
                if datetime_interval and not self._item_in_datetime(
                    item, datetime_interval
                ):
                    continue
                collected.append(self._normalise_item(item))

        return collected, None

    def _collect_item_links(
        self,
        base_url: str,
        doc: Dict[str, Any],
        remaining: int,
        request_timeout: float,
        _depth: int = 0,
    ) -> List[str]:
        """Recursively collect item href links from a STAC catalog/collection
        document, respecting the *remaining* cap and a max recursion depth."""
        if remaining <= 0 or _depth > 4:
            return []

        links = doc.get('links') or []
        item_urls: List[str] = []
        child_urls: List[str] = []

        for lnk in links:
            rel = lnk.get('rel', '')
            href = lnk.get('href', '')
            if not href:
                continue
            if rel == 'item':
                item_urls.append(self._resolve_url(base_url, href))
            elif rel in ('child', 'collection') and _depth < 3:
                child_urls.append(self._resolve_url(base_url, href))

        # Recurse into sub-catalogs
        for child_url in child_urls:
            if len(item_urls) >= remaining:
                break
            child_doc = self._fetch_json(child_url, timeout=request_timeout)
            if child_doc:
                sub = self._collect_item_links(
                    child_url,
                    child_doc,
                    remaining - len(item_urls),
                    request_timeout,
                    _depth + 1,
                )
                item_urls.extend(sub)

        return item_urls[:remaining]

    # -----------------------------------------------------------------------
    # Item normalisation
    # -----------------------------------------------------------------------

    def _normalise_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Augment a raw STAC item with Altair-standard fields."""
        props = item.get('properties') or {}
        assets = item.get('assets') or {}
        if not isinstance(assets, dict):
            assets = {}

        # Pick the best asset href (prefer the first data asset that is not
        # a thumbnail/overview)
        asset_href = self._pick_asset_href(item)
        thumbnail_href = self._pick_thumbnail_href(item)

        # Satellite / collection label
        sat_label = (
            props.get('platform')
            or props.get('instruments')
            or item.get('collection')
            or 'JAXA Earth'
        )
        if isinstance(sat_label, list):
            sat_label = ', '.join(str(s) for s in sat_label)

        item['_provider'] = 'JAXA Earth'
        item['_connector'] = 'jaxa_earth_stac'
        item['_satellite'] = str(sat_label)
        item['_asset_href'] = asset_href or ''
        item['_thumbnail'] = thumbnail_href or ''
        item['_cloud_cover'] = props.get('eo:cloud_cover')
        item['_datetime'] = (
            props.get('datetime')
            or props.get('start_datetime')
            or ''
        )
        item['_collection'] = item.get('collection', '')

        # Ensure quicklook/cog are visible through standard asset keys used by UI.
        if thumbnail_href and 'thumbnail' not in assets:
            assets['thumbnail'] = {
                'href': str(thumbnail_href),
                'type': 'image/jpeg',
                'roles': ['thumbnail'],
            }
        if asset_href and 'data' not in assets and 'visual' not in assets:
            assets['data'] = {
                'href': str(asset_href),
                'type': 'image/tiff; application=geotiff',
                'roles': ['data'],
            }
        item['assets'] = assets

        # Normalise geometry to a simple bbox list for footprint drawing
        if 'bbox' not in item:
            geom = item.get('geometry') or {}
            coords = geom.get('coordinates')
            if coords:
                flat = self._flatten_coords(coords)
                if flat:
                    xs = [c[0] for c in flat]
                    ys = [c[1] for c in flat]
                    item['bbox'] = [min(xs), min(ys), max(xs), max(ys)]

        return item

    @staticmethod
    def _pick_asset_href(item: Dict[str, Any]) -> Optional[str]:
        """Return the href of the most useful COG asset."""
        assets: Dict[str, Any] = item.get('assets') or {}
        preferred_roles = (
            ('data',), ('overview',), ('cog',), ('visual',), ('analytic',)
        )
        # Exclude thumbnails / quicklooks
        skip_types = {'image/png', 'image/jpeg', 'image/jpg'}

        def _role_match(asset: Dict, roles: tuple) -> bool:
            asset_roles = asset.get('roles') or []
            return any(r in asset_roles for r in roles)

        for role_group in preferred_roles:
            for _key, asset in assets.items():
                media_type = (asset.get('type') or '').lower()
                if media_type in skip_types:
                    continue
                if _role_match(asset, role_group):
                    return asset.get('href')

        # Fallback: first non-thumbnail asset
        for _key, asset in assets.items():
            media_type = (asset.get('type') or '').lower()
            if media_type not in skip_types:
                return asset.get('href')

        return None

    @staticmethod
    def _pick_thumbnail_href(item: Dict[str, Any]) -> Optional[str]:
        assets: Dict[str, Any] = item.get('assets') or {}
        for _key, asset in assets.items():
            roles = asset.get('roles') or []
            if 'thumbnail' in roles or 'overview' in roles:
                return asset.get('href')
        return None

    # -----------------------------------------------------------------------
    # Catalog / collection listing (for UI dropdowns)
    # -----------------------------------------------------------------------

    def get_collections(self) -> List[Dict[str, str]]:
        """Return list of {id, title} dicts from the JAXA root catalog.

        Results are cached after the first successful fetch.
        """
        if self._collections_cache is not None:
            return self._collections_cache

        cat = self._catalog_cache or self._fetch_json(self._catalog_url or CATALOG_URL)
        if not cat:
            logger.warning('Could not load JAXA catalog for collection listing')
            return []

        self._catalog_cache = cat
        collections: List[Dict[str, str]] = []

        for lnk in (cat.get('links') or []):
            if lnk.get('rel') not in ('child', 'collection'):
                continue
            href = lnk.get('href', '')
            title = lnk.get('title', '')
            # Extract collection id from the href
            col_id = href.rstrip('/').split('/')[-1].replace('.json', '')
            collections.append({'id': col_id, 'title': title or col_id, 'href': href})

        self._collections_cache = collections
        return collections

    # -----------------------------------------------------------------------
    # Optional tasking integration
    # -----------------------------------------------------------------------

    @staticmethod
    def _normalize_path(path: str, default: str) -> str:
        text = str(path or '').strip()
        if not text:
            text = default
        if not text.startswith('/'):
            text = '/' + text
        return text

    def _tasking_headers(self) -> Dict[str, str]:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        if self._tasking_access_token:
            headers['Authorization'] = f'Bearer {self._tasking_access_token}'
            headers['x-api-key'] = self._tasking_access_token
        return headers

    def tasking_url(self) -> str:
        if not self._tasking_base_url:
            return ''
        path = self._normalize_path(self._tasking_create_path, '/tasking/v2/requests')
        return f"{self._tasking_base_url.rstrip('/')}{path}"

    def create_tasking_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._tasking_base_url:
            logger.warning('JAXA tasking base URL not configured')
            return None

        path = self._normalize_path(self._tasking_create_path, '/tasking/v2/requests')
        url = f"{self._tasking_base_url.rstrip('/')}{path}"
        payload = request if isinstance(request, dict) else {}

        return self._post_json(
            url,
            payload,
            timeout=30.0,
            headers=self._tasking_headers(),
        )

    def list_tasking_requests(self, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        if not self._tasking_base_url:
            logger.warning('JAXA tasking base URL not configured')
            return None

        path = self._normalize_path(self._tasking_list_path, '/tasking/v2/requests')
        base_url = f"{self._tasking_base_url.rstrip('/')}{path}"
        if params:
            query = '&'.join(f"{k}={v}" for k, v in params.items() if v is not None)
            url = f"{base_url}?{query}" if query else base_url
        else:
            url = base_url

        return self._fetch_json(url, timeout=30.0, headers=self._tasking_headers())

    # -----------------------------------------------------------------------
    # Geometry / datetime helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _bbox_intersects(item: Dict[str, Any], bbox: List[float]) -> bool:
        """Return True if the item's bbox overlaps with the search bbox."""
        item_bbox = item.get('bbox')
        if not item_bbox or len(item_bbox) < 4:
            return True  # Unknown bbox → include

        west, south, east, north = item_bbox[:4]
        q_west, q_south, q_east, q_north = bbox[:4]

        return not (east < q_west or west > q_east or north < q_south or south > q_north)

    @staticmethod
    def _item_in_datetime(item: Dict[str, Any], interval: str) -> bool:
        """Return True if the item's datetime falls inside *interval*
        (``start/end`` ISO format, ``..`` for open ends)."""
        try:
            parts = interval.split('/')
            if len(parts) != 2:
                return True

            dt_str = (
                (item.get('properties') or {}).get('datetime')
                or (item.get('properties') or {}).get('start_datetime')
                or ''
            )
            if not dt_str:
                return True  # Unknown time → include conservatively

            # Strip trailing Z/offset for simple comparison
            dt_item = dt_str[:19]  # 'YYYY-MM-DDTHH:MM:SS'

            start_part, end_part = parts[0][:19], parts[1][:19]
            if start_part != '..' and dt_item < start_part:
                return False
            if end_part != '..' and dt_item > end_part:
                return False
            return True
        except Exception:
            return True

    @staticmethod
    def _build_datetime_interval(
        start: Optional[str], end: Optional[str]
    ) -> Optional[str]:
        s = (start or '').strip()
        e = (end or '').strip()
        if not s and not e:
            return None
        left = f'{s}T00:00:00Z' if s else '..'
        right = f'{e}T23:59:59Z' if e else '..'
        return f'{left}/{right}'

    @staticmethod
    def _flatten_coords(coords: Any) -> List[List[float]]:
        """Recursively flatten nested coordinate arrays."""
        if not coords:
            return []
        if isinstance(coords[0], (int, float)):
            return [coords]  # type: ignore[list-item]
        flat: List[List[float]] = []
        for sub in coords:
            flat.extend(JaxaEarthStacConnector._flatten_coords(sub))
        return flat

    @staticmethod
    def _resolve_url(base: str, href: str) -> str:
        """Resolve *href* relative to *base* catalog URL."""
        if href.startswith('http://') or href.startswith('https://'):
            return href
        return urljoin(base, href)

    # -----------------------------------------------------------------------
    # HTTP helpers (QGIS network manager)
    # -----------------------------------------------------------------------

    def _fetch_json(
        self,
        url: str,
        timeout: float = 20.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """GET *url*, decode JSON and return dict, or None on failure."""
        if not QGIS_AVAILABLE:
            logger.error('QGIS network manager not available')
            return None

        try:
            QgsNetworkAccessManager.instance().setupDefaultProxyAndCache()
            req = QNetworkRequest(QUrl(url))
            req.setRawHeader(b'Accept', b'application/json, application/geo+json')
            if headers:
                for key, value in headers.items():
                    req.setRawHeader(str(key).encode('utf-8'), str(value).encode('utf-8'))

            nam = QgsNetworkAccessManager.instance()
            reply = nam.get(req)

            loop = QEventLoop()
            reply.finished.connect(loop.quit)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(int(timeout * 1000))
            loop.exec_()

            if not reply.isFinished():
                reply.abort()
                logger.warning(f'JAXA GET timeout ({timeout}s): {url}')
                return None

            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if reply.error() or (status and int(status) >= 400):
                logger.debug(f'JAXA GET HTTP {status}: {url}')
                reply.deleteLater()
                return None

            raw = reply.readAll().data().decode('utf-8', errors='replace')
            reply.deleteLater()
            return json.loads(raw) if raw.strip() else None

        except Exception as exc:
            logger.warning(f'JAXA GET failed [{url}]: {exc}')
            return None

    def _post_json(
        self,
        url: str,
        body: Dict[str, Any],
        timeout: float = 30.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """POST JSON *body* to *url*, return decoded response or None."""
        if not QGIS_AVAILABLE:
            self._last_post_error = 'QGIS network manager not available'
            logger.error('QGIS network manager not available')
            return None

        self._last_post_error = ''

        merged_headers: Dict[str, str] = {
            'Accept': 'application/geo+json, application/json',
            'Content-Type': 'application/json',
        }
        if headers:
            merged_headers.update(headers)

        # Preferred path: shared QGIS helper (proxy/cache aware, standard error handling)
        data, error, http_status = qgis_request_json(
            method='POST',
            url=url,
            headers=merged_headers,
            payload=body,
            timeout=timeout,
        )
        if data is not None:
            return data

        if http_status is not None:
            self._last_post_error = f'HTTP {http_status}'
        elif error:
            self._last_post_error = str(error)

        try:
            QgsNetworkAccessManager.instance().setupDefaultProxyAndCache()
            payload = QByteArray(json.dumps(body).encode('utf-8'))
            req = QNetworkRequest(QUrl(url))
            req.setHeader(
                QNetworkRequest.ContentTypeHeader, 'application/json'
            )
            req.setRawHeader(b'Accept', b'application/geo+json, application/json')
            if merged_headers:
                for key, value in merged_headers.items():
                    req.setRawHeader(str(key).encode('utf-8'), str(value).encode('utf-8'))

            # Use QgsBlockingNetworkRequest for POST (simpler than async loop)
            blocking = QgsBlockingNetworkRequest()
            err_code = blocking.post(req, payload, forceRefresh=True)

            if err_code != QgsBlockingNetworkRequest.NoError:
                self._last_post_error = f'blocking error {err_code}'
                logger.debug(
                    f'JAXA POST blocking error {err_code}: {url}'
                )
                return None

            reply = blocking.reply()
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if status and int(status) >= 400:
                self._last_post_error = f'HTTP {int(status)}'
                logger.debug(f'JAXA POST HTTP {status}: {url}')
                return None

            raw = bytes(reply.content()).decode('utf-8', errors='replace')
            return json.loads(raw) if raw.strip() else None

        except Exception as exc:
            self._last_post_error = str(exc)
            logger.warning(f'JAXA POST failed [{url}]: {exc}')
            return None
