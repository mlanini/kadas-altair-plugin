"""swisstopo open-data STAC connector.

Supported STAC collections:
- ch.swisstopo.swisseo_s2-sr_v200
- ch.swisstopo.spezialbefliegungen

This connector is public (no authentication required) and exposes STAC Items
from each collection's ``/items`` endpoint.
"""

import json
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urljoin

try:
    import requests
except ImportError:  # pragma: no cover - dependency may be absent in trimmed envs
    requests = None

try:
    from qgis.PyQt.QtCore import QEventLoop, QTimer, QUrl, QSettings
    from qgis.PyQt.QtNetwork import QNetworkRequest
    from qgis.core import QgsNetworkAccessManager
    QGIS_AVAILABLE = True
except ImportError:
    QSettings = None
    QGIS_AVAILABLE = False

from .base import ConnectorBase
from ..logger import get_logger
from ..utilities.qt_compat import qt_exec

logger = get_logger('connectors.swisstopo_stac')


class SwisstopoStacConnector(ConnectorBase):
    """Open-data STAC connector for swisstopo collections."""

    DEFAULT_API_ROOT = 'https://data.geo.admin.ch/api/stac/v1/collections'
    FALLBACK_API_ROOTS = (
        DEFAULT_API_ROOT,
        'https://data.geo.admin.ch/api/stac/v0.9/collections',
    )
    SETTINGS_API_ROOT_KEY = 'AltairEOData/swisstopo_stac_api_root'

    COLLECTION_ID = 'ch.swisstopo.swisseo_s2-sr_v200'
    LEGACY_COLLECTION_ID = 'ch.swisstopo.swisseo_s2-sr_v100'
    SPECIAL_FLIGHTS_COLLECTION_ID = 'ch.swisstopo.spezialbefliegungen'

    SUPPORTED_COLLECTIONS: List[Dict[str, str]] = [
        {
            'id': COLLECTION_ID,
            'title': 'SWISSEO S2-SR v200',
            'description': (
                'swisstopo Sentinel-2 surface reflectance collection.'
            ),
        },
        {
            'id': SPECIAL_FLIGHTS_COLLECTION_ID,
            'title': 'Special flights',
            'description': (
                'swisstopo Spezialbefliegungen '
                '(special flights) collection.'
            ),
        },
    ]

    timeout_search = 60.0

    def __init__(self):
        super().__init__()
        self.authenticated = True
        self._api_root = self.DEFAULT_API_ROOT
        self._load_settings_defaults()

    def _load_settings_defaults(self) -> None:
        if QSettings is None:
            return
        try:
            settings = QSettings()
            api_root = str(
                settings.value(
                    self.SETTINGS_API_ROOT_KEY,
                    self.DEFAULT_API_ROOT,
                )
                or self.DEFAULT_API_ROOT
            ).strip()
            self._api_root = api_root.rstrip('/')
        except Exception as exc:
            logger.debug(f'swisstopo STAC settings read skipped: {exc}')

    def _collection_url(self, collection_id: str) -> str:
        return f'{self._api_root.rstrip("/")}/{collection_id}'

    def _probe_api_root(self, api_root: str, timeout: float = 15.0) -> bool:
        test_root = str(api_root or '').strip().rstrip('/')
        if not test_root:
            return False
        probe_url = f'{test_root}/{self.COLLECTION_ID}'
        payload = self._http_get_json(probe_url, timeout=timeout)
        return isinstance(payload, dict)

    def _select_working_api_root(self) -> bool:
        timeout = max(5.0, min(float(self.timeout_search), 20.0))
        candidate_roots = [self._api_root]
        for root in self.FALLBACK_API_ROOTS:
            normalized = str(root).strip().rstrip('/')
            if normalized and normalized not in candidate_roots:
                candidate_roots.append(normalized)

        for root in candidate_roots:
            if self._probe_api_root(root, timeout=timeout):
                if root != self._api_root:
                    logger.info(
                        'swisstopo STAC switched API root to %s',
                        root,
                    )
                self._api_root = root
                return True
        return False

    def authenticate(self, **kwargs) -> bool:
        credentials = kwargs.get('credentials') if isinstance(kwargs, dict) else None
        if isinstance(credentials, dict):
            override_root = str(
                credentials.get('api_root')
                or credentials.get('base_url')
                or ''
            ).strip()
            if override_root:
                self._api_root = override_root.rstrip('/')

        if not self._select_working_api_root():
            logger.warning(
                'swisstopo STAC API root probe failed for all known roots; '
                'continuing with configured root %s',
                self._api_root,
            )
        self.authenticated = True
        return True

    def _http_get_json(self, url: str, timeout: float = 60.0) -> Optional[Dict[str, Any]]:
        if QGIS_AVAILABLE:
            try:
                request = QNetworkRequest(QUrl(url))
                request.setRawHeader(b'Accept', b'application/geo+json,application/json')

                nam = QgsNetworkAccessManager.instance()
                reply = nam.get(request)

                loop = QEventLoop()
                reply.finished.connect(loop.quit)

                timer = QTimer()
                timer.setSingleShot(True)
                timer.timeout.connect(loop.quit)
                timer.start(int(timeout * 1000))

                qt_exec(loop)

                if not reply.isFinished():
                    reply.abort()
                    logger.warning(f'swisstopo STAC timeout after {timeout}s: {url}')
                    return None

                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if reply.error() or (status_code and int(status_code) >= 400):
                    logger.warning(
                        f'swisstopo STAC request failed: HTTP {status_code}, error={reply.errorString()} url={url}'
                    )
                    reply.deleteLater()
                    return None

                payload = reply.readAll().data().decode('utf-8', errors='ignore')
                reply.deleteLater()
                if not payload.strip():
                    return None
                return json.loads(payload)
            except Exception as exc:
                logger.warning(f'swisstopo STAC GET via QGIS failed: {exc}')

        if requests is None:
            logger.error('QGIS network manager unavailable and requests is not installed for swisstopo STAC request')
            return None

        try:
            response = requests.get(
                url,
                headers={'Accept': 'application/geo+json,application/json'},
                timeout=timeout,
            )
            if response is None:
                return None
            if getattr(response, 'status_code', 0) >= 400:
                logger.warning(
                    'swisstopo STAC request failed via requests: HTTP %s url=%s',
                    getattr(response, 'status_code', None),
                    url,
                )
                return None
            payload = getattr(response, 'text', '') or ''
            if not payload.strip():
                return None
            return json.loads(payload)
        except Exception as exc:
            logger.warning(f'swisstopo STAC GET via requests failed: {exc}')
            return None

    @staticmethod
    def _to_datetime_interval(start_date: str, end_date: str) -> Optional[str]:
        start = (start_date or '').strip()
        end = (end_date or '').strip()
        if not start and not end:
            return None
        left = f'{start}T00:00:00Z' if len(start) == 10 else start or '..'
        right = f'{end}T23:59:59Z' if len(end) == 10 else end or '..'
        return f'{left}/{right}'

    @staticmethod
    def _normalize_item(
        item: Dict[str, Any],
        idx: int,
        collection_id: str,
    ) -> Dict[str, Any]:
        props = item.get('properties') if isinstance(item.get('properties'), dict) else {}

        raw_id = item.get('id')
        if raw_id is None or str(raw_id).strip() == '':
            raw_id = props.get('id') or props.get('identifier') or props.get('datetime')
        item_id = str(raw_id).strip() if raw_id is not None else ''
        if not item_id:
            item_id = f'{collection_id}-{idx}'

        if item.get('type') != 'Feature':
            item['type'] = 'Feature'
        item['id'] = item_id
        if 'properties' not in item or not isinstance(item.get('properties'), dict):
            item['properties'] = props
        if 'assets' not in item or not isinstance(item.get('assets'), dict):
            item['assets'] = {}
        if not item.get('collection'):
            item['collection'] = collection_id

        return item

    def get_collections(self) -> List[Dict[str, Any]]:
        """Return supported swisstopo STAC collections for the UI dropdown."""
        collections: List[Dict[str, Any]] = []
        for coll in self.SUPPORTED_COLLECTIONS:
            collections.append(
                {
                    'id': coll['id'],
                    'title': coll['title'],
                    'description': coll['description'],
                }
            )
        return collections

    def resolve_cog_url(self, item: dict) -> str:
        assets = item.get('assets') if isinstance(item, dict) else {}
        if isinstance(assets, dict):
            for key, asset in assets.items():
                if not str(key).lower().endswith('_tci_10m.tif'):
                    continue
                if self._is_preview_asset(key, asset):
                    continue
                href = self._asset_href(item, asset)
                if href and self._is_raster_asset(href, asset, key):
                    return href
        return super().resolve_cog_url(item)

    def _resolve_collections_for_search(
        self,
        collection: Optional[str],
    ) -> List[str]:
        supported = {c['id'] for c in self.SUPPORTED_COLLECTIONS}
        if collection:
            requested = [
                part.strip()
                for part in str(collection).split(',')
                if part.strip()
            ]
            requested = [
                self.COLLECTION_ID if cid == self.LEGACY_COLLECTION_ID else cid
                for cid in requested
            ]
            return [cid for cid in requested if cid in supported]
        return [c['id'] for c in self.SUPPORTED_COLLECTIONS]

    def search(
        self,
        bbox: Optional[List[float]] = None,
        start_date: str = '',
        end_date: str = '',
        max_cloud_cover: Optional[float] = None,
        collection: Optional[str] = None,
        limit: int = 100,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        result_limit = max(1, int(limit))
        params = {
            'limit': min(100, result_limit),
            'sortby': '-properties.datetime',
        }
        if bbox and len(bbox) >= 4:
            params['bbox'] = ','.join(str(value) for value in bbox[:4])

        datetime_interval = self._to_datetime_interval(start_date, end_date)
        if datetime_interval:
            params['datetime'] = datetime_interval

        collection_ids = self._resolve_collections_for_search(collection)
        if not collection_ids:
            return [], None

        normalized: List[Dict[str, Any]] = []
        seen_keys = set()
        errors: List[str] = []
        deadline = time.monotonic() + float(self.timeout_search)

        for collection_id in collection_ids:
            if len(normalized) >= result_limit:
                break
            items_url = f'{self._collection_url(collection_id)}/items?{urlencode(params)}'
            visited_urls = set()
            item_index = 0
            while items_url and len(normalized) < result_limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    errors.append(f'swisstopo STAC search timed out for {collection_id}')
                    break
                if items_url in visited_urls:
                    errors.append(f'swisstopo STAC pagination loop for {collection_id}')
                    break
                visited_urls.add(items_url)
                response = self._http_get_json(items_url, timeout=remaining)
                features = response.get('features') if isinstance(response, dict) else None
                if not isinstance(features, list):
                    errors.append(f'swisstopo STAC search failed for {collection_id}')
                    break

                for feature in features:
                    item_index += 1
                    if not isinstance(feature, dict):
                        continue
                    item = self._normalize_item(feature, item_index, collection_id)
                    item_key = (item.get('collection', collection_id), item.get('id', ''))
                    if item_key in seen_keys:
                        continue
                    seen_keys.add(item_key)
                    if max_cloud_cover is not None:
                        props = item['properties']
                        cloud = props.get('eo:cloud_cover', props.get('cloud_cover'))
                        if cloud is not None and cloud != '':
                            try:
                                threshold = float(max_cloud_cover)
                                if threshold <= 1.0:
                                    threshold *= 100.0
                                if float(cloud) > threshold:
                                    continue
                            except (TypeError, ValueError):
                                pass
                    normalized.append(item)
                    if len(normalized) >= result_limit:
                        break

                links = response.get('links', [])
                next_href = next(
                    (link.get('href') for link in links
                     if isinstance(link, dict) and link.get('rel') == 'next'
                     and isinstance(link.get('href'), str) and link.get('href')),
                    None,
                ) if isinstance(links, list) else None
                items_url = urljoin(items_url, next_href) if next_href else ''

        if errors:
            logger.warning('; '.join(errors))
        return normalized, '; '.join(errors) or None
