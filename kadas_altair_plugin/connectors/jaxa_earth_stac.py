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
    from qgis.PyQt.QtCore import QByteArray, QEventLoop, QTimer, QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest
    from qgis.core import QgsNetworkAccessManager, QgsBlockingNetworkRequest
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False

from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.jaxa_earth_stac')

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CATALOG_URL = 'https://data.earth.jaxa.jp/stac/cog/v1/catalog.json'
STAC_API_ROOT = 'https://data.earth.jaxa.jp/stac/cog/v1/'
# Standard STAC API search endpoint (may not be supported — we fall back to
# catalog navigation if the server returns 404 / 405)
STAC_SEARCH_URL = 'https://data.earth.jaxa.jp/stac/cog/v1/search'

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
        logger.info('JaxaEarthStacConnector initialised')

    def authenticate(self, credentials: Optional[Dict] = None) -> bool:
        """Verify that the JAXA catalog is reachable (no credentials needed)."""
        logger.info('Authenticating JAXA Earth STAC connector (public catalog)…')
        cat = self._fetch_json(CATALOG_URL, timeout=15.0)
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

        # Build datetime interval string
        datetime_interval = self._build_datetime_interval(start_date, end_date)

        # Try STAC /search API first (fast server-side filtering)
        if self._has_search_api is not False:
            items, err = self._search_via_api(bbox, datetime_interval, collection, limit)
            if items is not None:
                self._has_search_api = True
                logger.info(f'JAXA /search API returned {len(items)} items')
                return items, None
            if err and 'not supported' not in (err or '').lower():
                # Transient network error — do not fall back silently
                logger.warning(f'JAXA /search failed: {err}')

        # Fall back to catalog-walk
        self._has_search_api = False
        logger.info('JAXA falling back to catalog-walk search')
        items, err = self._search_via_catalog_walk(
            bbox, datetime_interval, collection, limit
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

        data = self._post_json(STAC_SEARCH_URL, body, timeout=30.0)
        if data is None:
            return None, 'search endpoint not available'

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
    ) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """Walk the STAC catalog hierarchy and collect matching items."""

        # Load root catalog
        cat = self._catalog_cache or self._fetch_json(CATALOG_URL)
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
            child_url = self._resolve_url(CATALOG_URL, child_url)
            child_doc = self._fetch_json(child_url)
            if not child_doc:
                continue

            # Collect item links from this collection (and sub-catalogs)
            item_links = self._collect_item_links(
                child_url, child_doc, remaining=limit - len(collected)
            )

            for item_url in item_links:
                if len(collected) >= limit:
                    break
                item = self._fetch_json(item_url)
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
            child_doc = self._fetch_json(child_url)
            if child_doc:
                sub = self._collect_item_links(
                    child_url,
                    child_doc,
                    remaining - len(item_urls),
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

        cat = self._catalog_cache or self._fetch_json(CATALOG_URL)
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
        self, url: str, timeout: float = 20.0
    ) -> Optional[Dict[str, Any]]:
        """GET *url*, decode JSON and return dict, or None on failure."""
        if not QGIS_AVAILABLE:
            logger.error('QGIS network manager not available')
            return None

        try:
            req = QNetworkRequest(QUrl(url))
            req.setRawHeader(b'Accept', b'application/json, application/geo+json')

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
    ) -> Optional[Dict[str, Any]]:
        """POST JSON *body* to *url*, return decoded response or None."""
        if not QGIS_AVAILABLE:
            logger.error('QGIS network manager not available')
            return None

        try:
            payload = QByteArray(json.dumps(body).encode('utf-8'))
            req = QNetworkRequest(QUrl(url))
            req.setHeader(
                QNetworkRequest.ContentTypeHeader, 'application/json'
            )
            req.setRawHeader(b'Accept', b'application/geo+json, application/json')

            # Use QgsBlockingNetworkRequest for POST (simpler than async loop)
            blocking = QgsBlockingNetworkRequest()
            err_code = blocking.post(req, payload, forceRefresh=True)

            if err_code != QgsBlockingNetworkRequest.NoError:
                logger.debug(
                    f'JAXA POST blocking error {err_code}: {url}'
                )
                return None

            reply = blocking.reply()
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if status and int(status) >= 400:
                logger.debug(f'JAXA POST HTTP {status}: {url}')
                return None

            raw = bytes(reply.content()).decode('utf-8', errors='replace')
            return json.loads(raw) if raw.strip() else None

        except Exception as exc:
            logger.warning(f'JAXA POST failed [{url}]: {exc}')
            return None
