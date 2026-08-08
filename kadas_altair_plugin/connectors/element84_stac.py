"""Earth Search (Element84) STAC connector.

Open-data archive connector for Sentinel and Landsat imagery exposed by
Earth Search v1:
https://earth-search.aws.element84.com/v1/

This connector is intended for archive search and COG item loading.
No authentication is required.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from qgis.PyQt.QtCore import QSettings
except Exception:
    QSettings = None

from .base import ConnectorBase
from ..logger import get_logger
from ..utilities.qgis_network import qgis_request_json

logger = get_logger('connectors.element84_stac')


class Element84StacConnector(ConnectorBase):
    """Archive STAC connector for Earth Search (Element84)."""

    DEFAULT_API_ROOT = 'https://earth-search.aws.element84.com/v1'
    SETTINGS_API_ROOT_KEY = 'AltairEOData/element84_stac_api_url'
    SETTINGS_TIMEOUT_KEY = 'AltairEOData/element84_stac_timeout'

    # Known sentinel/landsat collection ids historically used by Earth Search.
    DEFAULT_ALLOWED_COLLECTIONS = [
        'sentinel-2-l2a',
        'sentinel-s2-l2a-cogs',
        'sentinel-1-grd',
        'landsat-c2-l2',
    ]

    timeout_search = 30.0

    def __init__(self):
        super().__init__()
        self.authenticated = True
        self._api_root = self.DEFAULT_API_ROOT
        self._allowed_collection_ids: List[str] = list(self.DEFAULT_ALLOWED_COLLECTIONS)
        self._load_settings_defaults()

    def _load_settings_defaults(self) -> None:
        if QSettings is None:
            return
        try:
            settings = QSettings()
            api_root = str(
                settings.value(self.SETTINGS_API_ROOT_KEY, self.DEFAULT_API_ROOT)
                or self.DEFAULT_API_ROOT
            ).strip()
            self._api_root = api_root.rstrip('/')

            timeout_v = settings.value(
                self.SETTINGS_TIMEOUT_KEY,
                int(self.timeout_search),
                type=int,
            )
            self.timeout_search = float(max(5, min(int(timeout_v), 120)))
        except Exception as exc:
            logger.debug(f'Element84 settings read skipped: {exc}')

    def authenticate(self, credentials: Optional[Dict[str, Any]] = None, **_kwargs) -> bool:
        """Configure endpoint and validate reachability of STAC API root."""
        credentials = credentials or {}

        api_root = str(
            credentials.get('api_root')
            or credentials.get('base_url')
            or self._api_root
            or self.DEFAULT_API_ROOT
        ).strip()
        self._api_root = api_root.rstrip('/')

        timeout = credentials.get('timeout')
        if timeout is not None:
            try:
                self.timeout_search = float(max(5, min(int(timeout), 120)))
            except Exception:
                pass

        data, err, status = qgis_request_json(
            method='GET',
            url=f'{self._api_root}/',
            headers={'Accept': 'application/json'},
            timeout=self.timeout_search,
        )
        if err is not None:
            logger.warning(
                'Element84 root probe failed (status=%s): %s',
                status,
                err,
            )
            # Keep connector enabled even when probe fails.
            self.authenticated = True
            return False

        if not isinstance(data, dict):
            logger.warning('Element84 root probe returned non-object payload')
            self.authenticated = True
            return False

        self.authenticated = True
        return True

    def _iso_start(self, date_value: str) -> str:
        date_value = (date_value or '').strip()
        if not date_value:
            return ''
        if 'T' in date_value:
            return date_value if date_value.endswith('Z') else f'{date_value}Z'
        return f'{date_value}T00:00:00Z'

    def _iso_end(self, date_value: str) -> str:
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
        fallback_start = datetime.utcnow().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return f"{fallback_start.strftime('%Y-%m-%dT00:00:00Z')}/{now_utc}"

    @staticmethod
    def _is_sentinel_or_landsat(collection_id: str) -> bool:
        cid = str(collection_id or '').strip().lower()
        return cid.startswith('sentinel') or cid.startswith('landsat')

    def _resolve_requested_collections(self, collection: Optional[str]) -> List[str]:
        requested: List[str] = []
        if collection:
            requested = [part.strip() for part in str(collection).split(',') if part.strip()]
            requested = [cid for cid in requested if self._is_sentinel_or_landsat(cid)]

        if requested:
            return requested

        dynamic = [
            coll.get('id', '')
            for coll in self.get_collections()
            if isinstance(coll, dict)
        ]
        dynamic = [cid for cid in dynamic if self._is_sentinel_or_landsat(cid)]
        if dynamic:
            return dynamic

        return list(self.DEFAULT_ALLOWED_COLLECTIONS)

    def _request_search(self, payload: Dict[str, Any], timeout: float) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        headers = {
            'Accept': 'application/geo+json, application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'KADAS-Altair-Plugin/1.0',
        }
        search_url = f'{self._api_root}/search'

        data, err, status = qgis_request_json(
            method='POST',
            url=search_url,
            headers=headers,
            payload=payload,
            timeout=timeout,
        )
        if err is None:
            if isinstance(data, dict):
                return data, None
            return {'features': data}, None

        logger.warning(
            'Element84 search via QGIS network failed (status=%s): %s',
            status,
            err,
        )

        session = self.get_session()
        if session is None:
            return None, err

        try:
            response = session.post(search_url, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            if not response.content:
                return {}, None
            response_data = response.json()
            if isinstance(response_data, dict):
                return response_data, None
            return {'features': response_data}, None
        except Exception as exc:
            return None, str(exc)

    @staticmethod
    def _normalize_item(feature: Dict[str, Any]) -> Dict[str, Any]:
        properties = feature.get('properties') if isinstance(feature.get('properties'), dict) else {}
        assets = feature.get('assets') if isinstance(feature.get('assets'), dict) else {}

        cloud_cover = properties.get('eo:cloud_cover', properties.get('cloud_cover'))
        if cloud_cover is not None:
            properties['eo:cloud_cover'] = cloud_cover
            properties['cloud_cover'] = cloud_cover

        normalized = {
            'type': 'Feature',
            'id': str(feature.get('id') or 'unknown'),
            'collection': feature.get('collection') or '',
            'bbox': feature.get('bbox'),
            'geometry': feature.get('geometry'),
            'properties': properties,
            'assets': assets,
            'links': feature.get('links') or [],
            'stac_feature': feature,
            'is_collection': False,
        }
        return normalized

    @staticmethod
    def _filter_by_text(items: List[Dict[str, Any]], text_query: str) -> List[Dict[str, Any]]:
        query = str(text_query or '').strip().lower()
        if not query:
            return items

        filtered: List[Dict[str, Any]] = []
        for item in items:
            properties = item.get('properties') if isinstance(item.get('properties'), dict) else {}
            item_id = str(item.get('id') or '').lower()
            platform = str(properties.get('platform') or '').lower()
            title = str(properties.get('title') or properties.get('description') or '').lower()
            if query in item_id or query in platform or query in title:
                filtered.append(item)
        return filtered

    @staticmethod
    def _filter_by_cloud(items: List[Dict[str, Any]], max_cloud_cover: Optional[float]) -> List[Dict[str, Any]]:
        if max_cloud_cover is None:
            return items

        try:
            threshold = float(max_cloud_cover)
        except Exception:
            return items

        if threshold <= 1.0:
            threshold *= 100.0

        filtered: List[Dict[str, Any]] = []
        for item in items:
            properties = item.get('properties') if isinstance(item.get('properties'), dict) else {}
            cloud = properties.get('eo:cloud_cover', properties.get('cloud_cover'))
            if cloud in (None, ''):
                filtered.append(item)
                continue
            try:
                if float(cloud) <= threshold:
                    filtered.append(item)
            except Exception:
                filtered.append(item)
        return filtered

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
        **_kwargs,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        request_timeout = float(timeout) if timeout is not None else float(self.timeout_search)
        request_timeout = max(5.0, min(request_timeout, 120.0))

        payload: Dict[str, Any] = {
            'limit': max(1, min(int(limit), 1000)),
            'collections': self._resolve_requested_collections(collection),
            'datetime': self._build_datetime_range(str(start_date or ''), str(end_date or '')),
        }

        if bbox and len(bbox) >= 4:
            payload['bbox'] = [
                float(bbox[0]),
                float(bbox[1]),
                float(bbox[2]),
                float(bbox[3]),
            ]

        data, error = self._request_search(payload, timeout=request_timeout)
        if error is not None:
            logger.error(f'Element84 STAC search failed: {error}')
            return [], error

        if not isinstance(data, dict):
            return [], 'Invalid STAC response payload'

        features = data.get('features') or []
        items = [
            self._normalize_item(feature)
            for feature in features
            if isinstance(feature, dict)
        ]

        items = self._filter_by_cloud(items, max_cloud_cover=max_cloud_cover)
        items = self._filter_by_text(items, text_query=text_query)

        if len(items) > int(limit):
            items = items[: int(limit)]

        logger.info('Element84 STAC search returned %s item(s)', len(items))
        return items, None

    def get_collections(self) -> List[Dict[str, Any]]:
        url = f'{self._api_root}/collections'
        data, err, status = qgis_request_json(
            method='GET',
            url=url,
            headers={'Accept': 'application/json'},
            timeout=self.timeout_search,
        )
        if err is not None:
            logger.warning(
                'Element84 collections via QGIS failed (status=%s): %s',
                status,
                err,
            )
            session = self.get_session()
            if session is not None:
                try:
                    response = session.get(url, timeout=self.timeout_search)
                    response.raise_for_status()
                    data = response.json() if response.content else {}
                except Exception as exc:
                    logger.warning(f'Element84 collections via requests failed: {exc}')
                    data = {}
            else:
                data = {}

        collections = data.get('collections') if isinstance(data, dict) else []
        if not isinstance(collections, list):
            collections = []

        normalized: List[Dict[str, Any]] = []
        for coll in collections:
            if not isinstance(coll, dict):
                continue
            coll_id = str(coll.get('id') or '').strip()
            if not coll_id or not self._is_sentinel_or_landsat(coll_id):
                continue
            normalized.append({
                'id': coll_id,
                'title': str(coll.get('title') or coll_id),
                'description': str(coll.get('description') or ''),
            })

        if normalized:
            self._allowed_collection_ids = [c['id'] for c in normalized]
            return normalized

        return [
            {'id': cid, 'title': cid, 'description': ''}
            for cid in self.DEFAULT_ALLOWED_COLLECTIONS
            if self._is_sentinel_or_landsat(cid)
        ]
