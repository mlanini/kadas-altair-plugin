"""swisstopo SWISSEO S2-SR open-data STAC connector.

Endpoint base collection:
https://data.geo.admin.ch/api/stac/v0.9/collections/ch.swisstopo.swisseo_s2-sr_v100

This connector is public (no authentication required) and exposes STAC Items
from the collection's ``/items`` endpoint.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except ImportError:  # pragma: no cover - dependency may be absent in trimmed envs
    requests = None

try:
    from qgis.PyQt.QtCore import QEventLoop, QTimer, QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest
    from qgis.core import QgsNetworkAccessManager
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False

from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.swisstopo_stac')


class SwisstopoStacConnector(ConnectorBase):
    """Open-data STAC connector for swisstopo SWISSEO S2-SR."""

    COLLECTION_URL = (
        'https://data.geo.admin.ch/api/stac/v0.9/collections/'
        'ch.swisstopo.swisseo_s2-sr_v100'
    )
    COLLECTION_ID = 'ch.swisstopo.swisseo_s2-sr_v100'

    timeout_search = 30.0

    def __init__(self):
        super().__init__()
        self.authenticated = True

    def authenticate(self, **kwargs) -> bool:
        self.authenticated = True
        return True

    def _http_get_json(self, url: str, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
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

                loop.exec_()

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
        left = f'{start}T00:00:00Z' if start else '..'
        right = f'{end}T23:59:59Z' if end else '..'
        return f'{left}/{right}'

    @staticmethod
    def _normalize_item(item: Dict[str, Any], idx: int) -> Dict[str, Any]:
        props = item.get('properties') if isinstance(item.get('properties'), dict) else {}

        raw_id = item.get('id')
        if raw_id is None or str(raw_id).strip() == '':
            raw_id = props.get('id') or props.get('identifier') or props.get('datetime')
        item_id = str(raw_id).strip() if raw_id is not None else ''
        if not item_id:
            item_id = f'{SwisstopoStacConnector.COLLECTION_ID}-{idx}'

        if item.get('type') != 'Feature':
            item['type'] = 'Feature'
        item['id'] = item_id
        if 'properties' not in item or not isinstance(item.get('properties'), dict):
            item['properties'] = props
        if 'assets' not in item or not isinstance(item.get('assets'), dict):
            item['assets'] = {}

        return item

    def search(
        self,
        bbox: Optional[List[float]] = None,
        start_date: str = '',
        end_date: str = '',
        max_cloud_cover: Optional[float] = None,
        collection: Optional[str] = None,
        limit: int = 100,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        params: List[str] = [f'limit={max(1, int(limit))}']
        if bbox and len(bbox) >= 4:
            params.append(f'bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}')

        datetime_interval = self._to_datetime_interval(start_date, end_date)
        if datetime_interval:
            params.append(f'datetime={datetime_interval}')

        items_url = f"{self.COLLECTION_URL}/items"
        if params:
            items_url = f"{items_url}?{'&'.join(params)}"

        response = self._http_get_json(items_url, timeout=self.timeout_search)
        if not response:
            return [], None

        features = response.get('features', []) if isinstance(response, dict) else []
        if not isinstance(features, list):
            return [], None

        normalized: List[Dict[str, Any]] = []
        for idx, feature in enumerate(features):
            if isinstance(feature, dict):
                normalized.append(self._normalize_item(feature, idx))

        if max_cloud_cover is not None:
            filtered: List[Dict[str, Any]] = []
            for item in normalized:
                props = item.get('properties', {})
                cloud = props.get('eo:cloud_cover', props.get('cloud_cover'))
                if cloud is None or cloud == '':
                    filtered.append(item)
                    continue
                try:
                    cloud_value = float(cloud)
                    threshold = float(max_cloud_cover)
                    if threshold <= 1.0:
                        threshold *= 100.0
                    if cloud_value <= threshold:
                        filtered.append(item)
                except Exception:
                    filtered.append(item)
            normalized = filtered

        return normalized[: max(1, int(limit))], None
