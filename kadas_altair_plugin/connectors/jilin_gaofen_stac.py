"""Jilin-1 Gaofen STAC connector.

This connector targets STAC-compatible catalog/search endpoints that expose
Jilin-1 Gaofen imagery. Endpoint and optional token can be provided via:
- authenticate(credentials={...})
- QSettings (fallback):
    - altair/jilin_stac_base_url
    - altair/jilin_collection
    - altair/jilin_access_token

Notes:
- The connector is endpoint-driven because Jilin deployments vary by tenant/API.
- If no endpoint is configured, searches return an explanatory message.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

try:
    from qgis.PyQt.QtCore import QEventLoop, QTimer, QUrl, QSettings
    from qgis.PyQt.QtNetwork import QNetworkRequest
    from qgis.core import QgsNetworkAccessManager
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False

from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.jilin_gaofen_stac')


class JilinGaofenStacConnector(ConnectorBase):
    """STAC connector for Jilin-1 Gaofen constellation archives."""

    timeout_search = 30.0

    def __init__(self, base_url: Optional[str] = None):
        super().__init__()
        self.authenticated = True
        self._base_url = (base_url or '').strip().rstrip('/')
        self._access_token: Optional[str] = None
        self._default_collection: Optional[str] = None
        self._load_settings_defaults()

    def _load_settings_defaults(self) -> None:
        """Load optional connector defaults from QSettings."""
        try:
            settings = QSettings()
            if not self._base_url:
                self._base_url = str(settings.value('altair/jilin_stac_base_url', '') or '').strip().rstrip('/')

            token = str(settings.value('altair/jilin_access_token', '') or '').strip()
            if token:
                self._access_token = token

            collection = str(settings.value('altair/jilin_collection', '') or '').strip()
            if collection:
                self._default_collection = collection

        except Exception as exc:
            logger.debug(f'Jilin settings read skipped: {exc}')

    def authenticate(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Configure endpoint/token (authentication optional).

        Supported credential keys:
        - base_url / stac_url / api_base_url
        - access_token / token / api_key
        - collection
        """
        credentials = credentials or {}

        endpoint = (
            credentials.get('base_url')
            or credentials.get('stac_url')
            or credentials.get('api_base_url')
            or self._base_url
            or ''
        )
        self._base_url = str(endpoint).strip().rstrip('/')

        token = (
            credentials.get('access_token')
            or credentials.get('token')
            or credentials.get('api_key')
            or self._access_token
            or ''
        )
        token = str(token).strip()
        self._access_token = token or None

        collection = credentials.get('collection') or self._default_collection or ''
        collection = str(collection).strip()
        self._default_collection = collection or None

        if not self._base_url:
            logger.warning('Jilin connector authenticated without endpoint (set altair/jilin_stac_base_url)')
        else:
            logger.info(f'Jilin connector configured for endpoint: {self._base_url}')

        self.authenticated = True
        return True

    def _http_json(
        self,
        url: str,
        method: str = 'GET',
        payload: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        if not QGIS_AVAILABLE:
            logger.error('QGIS network manager not available for Jilin request')
            return None

        try:
            request = QNetworkRequest(QUrl(url))
            request.setRawHeader(b'Accept', b'application/geo+json,application/json')
            request.setRawHeader(b'Content-Type', b'application/json')
            if self._access_token:
                request.setRawHeader(b'Authorization', f'Bearer {self._access_token}'.encode('utf-8'))

            nam = QgsNetworkAccessManager.instance()
            body = json.dumps(payload or {}).encode('utf-8')

            if method.upper() == 'POST':
                reply = nam.post(request, body)
            else:
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
                logger.warning(f'Jilin request timeout after {timeout}s: {url}')
                return None

            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if reply.error() or (status_code and int(status_code) >= 400):
                logger.warning(
                    f'Jilin request failed: HTTP {status_code}, error={reply.errorString()} url={url}'
                )
                reply.deleteLater()
                return None

            response = reply.readAll().data().decode('utf-8', errors='ignore')
            reply.deleteLater()

            if not response.strip():
                return None

            return json.loads(response)
        except Exception as exc:
            logger.warning(f'Jilin HTTP request failed: {exc}')
            return None

    @staticmethod
    def _datetime_interval(start_date: Optional[str], end_date: Optional[str]) -> Optional[str]:
        start = (start_date or '').strip()
        end = (end_date or '').strip()
        if not start and not end:
            return None
        left = f'{start}T00:00:00Z' if start else '..'
        right = f'{end}T23:59:59Z' if end else '..'
        return f'{left}/{right}'

    @staticmethod
    def _normalize_items(items: List[Dict[str, Any]], default_collection: Optional[str]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue

            if item.get('type') != 'Feature':
                item['type'] = 'Feature'

            if 'properties' not in item or not isinstance(item.get('properties'), dict):
                item['properties'] = {}

            if 'assets' not in item or not isinstance(item.get('assets'), dict):
                item['assets'] = {}

            if not item.get('id'):
                props = item.get('properties', {})
                fallback_id = props.get('id') or props.get('identifier') or f'jilin-{idx}'
                item['id'] = str(fallback_id)

            if default_collection and not item.get('collection'):
                item['collection'] = default_collection

            normalized.append(item)

        return normalized

    def search_unified(
        self,
        bbox=None,
        start_date=None,
        end_date=None,
        max_cloud_cover=None,
        collection=None,
        text_query=None,
        limit: int = 100,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        return self.search(
            bbox=bbox,
            start_date=start_date or '',
            end_date=end_date or '',
            max_cloud_cover=max_cloud_cover,
            collection=collection,
            text_query=text_query,
            limit=limit,
        )

    def search(
        self,
        bbox: Optional[List[float]] = None,
        start_date: str = '',
        end_date: str = '',
        max_cloud_cover: Optional[float] = None,
        collection: Optional[str] = None,
        text_query: Optional[str] = None,
        limit: int = 100,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        if not self._base_url:
            return [], 'Jilin endpoint not configured (set altair/jilin_stac_base_url).'

        selected_collection = (collection or self._default_collection or '').strip() or None
        max_items = max(1, int(limit))

        search_payload: Dict[str, Any] = {'limit': max_items}
        if bbox and len(bbox) >= 4:
            search_payload['bbox'] = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]

        dt = self._datetime_interval(start_date, end_date)
        if dt:
            search_payload['datetime'] = dt

        if selected_collection:
            search_payload['collections'] = [selected_collection]

        if text_query:
            search_payload['query'] = {'text': {'ilike': f'%{text_query}%'}}

        if max_cloud_cover is not None:
            threshold = float(max_cloud_cover)
            if threshold <= 1.0:
                threshold *= 100.0
            query_obj = search_payload.setdefault('query', {})
            if isinstance(query_obj, dict):
                query_obj['eo:cloud_cover'] = {'lte': threshold}

        search_url = f'{self._base_url}/search'
        response = self._http_json(search_url, method='POST', payload=search_payload, timeout=self.timeout_search)

        if not response and selected_collection:
            params = [f'limit={max_items}']
            if bbox and len(bbox) >= 4:
                params.append(f'bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}')
            if dt:
                params.append(f'datetime={dt}')
            items_url = f'{self._base_url}/collections/{selected_collection}/items'
            if params:
                items_url = f"{items_url}?{'&'.join(params)}"
            response = self._http_json(items_url, method='GET', timeout=self.timeout_search)

        if not response:
            return [], None

        features = response.get('features', []) if isinstance(response, dict) else []
        if not isinstance(features, list):
            return [], None

        normalized = self._normalize_items(features, selected_collection)
        return normalized[:max_items], None

    def get_tile_url(self, result: Dict[str, Any], z: int, x: int, y: int) -> str:
        assets = result.get('assets') if isinstance(result.get('assets'), dict) else {}
        preferred = ['visual', 'analytic', 'image', 'preview', 'thumbnail', 'quicklook']
        for key in preferred:
            asset = assets.get(key)
            if isinstance(asset, dict) and asset.get('href'):
                return str(asset.get('href'))

        for asset in assets.values():
            if isinstance(asset, dict) and asset.get('href'):
                return str(asset.get('href'))

        return ''
