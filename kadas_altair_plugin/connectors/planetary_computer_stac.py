"""Microsoft Planetary Computer STAC connector.

Open-data archive connector for the Planetary Computer STAC API:
https://planetarycomputer.microsoft.com/api/stac/v1/

Focus:
- Archive search only
- Prefer Imagery and Fire collections with COG assets
- Return items ready for COG loading in map viewer
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

logger = get_logger('connectors.planetary_computer_stac')


class PlanetaryComputerStacConnector(ConnectorBase):
    """Archive STAC connector for Microsoft Planetary Computer."""

    DEFAULT_API_ROOT = 'https://planetarycomputer.microsoft.com/api/stac/v1'
    SETTINGS_API_ROOT_KEY = 'AltairEOData/planetary_computer_stac_api_url'
    SETTINGS_TIMEOUT_KEY = 'AltairEOData/planetary_computer_stac_timeout'

    timeout_search = 60.0

    SUPPORTED_COLLECTION_KEYWORDS = (
        'imagery',
        'fire',
    )

    EXCLUDED_COLLECTION_KEYWORDS = (
        'sentinel-1',
        'sar',
        'rtc',
        'insar',
        'dem',
        'elevation',
    )

    RGB_ASSET_PRIORITY = ('visual', 'render', 'preview')

    RASTER_MEDIA_HINTS = (
        'image/tiff',
        'image/geotiff',
        'image/jp2',
        'image/x.geotiff',
        'image/vnd.stac.geotiff',
    )

    def __init__(self):
        super().__init__()
        self.authenticated = True
        self._api_root = self.DEFAULT_API_ROOT
        self._collection_cache: Optional[List[Dict[str, Any]]] = None
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
            logger.debug(f'Planetary Computer settings read skipped: {exc}')

    def authenticate(self, credentials: Optional[Dict[str, Any]] = None, **_kwargs) -> bool:
        """Apply endpoint/timeout settings and probe API root."""
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
                'Planetary Computer root probe failed (status=%s): %s',
                status,
                err,
            )
            self.authenticated = True
            return False

        self.authenticated = True
        return isinstance(data, dict)

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
        fallback_start = datetime.utcnow().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return f"{fallback_start.strftime('%Y-%m-%dT00:00:00Z')}/{now_utc}"

    @classmethod
    def _is_supported_collection(
        cls,
        collection_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        cid = str(collection_id or '').strip().lower()
        title = str((metadata or {}).get('title') or '').lower()
        description = str((metadata or {}).get('description') or '').lower()
        keywords = (metadata or {}).get('keywords') or []
        if not isinstance(keywords, list):
            keywords = []
        keyword_haystack = ' '.join(str(keyword or '').lower() for keyword in keywords)
        haystack = f'{cid} {title} {description} {keyword_haystack}'

        if any(token in haystack for token in cls.EXCLUDED_COLLECTION_KEYWORDS):
            return False

        return any(token in haystack for token in cls.SUPPORTED_COLLECTION_KEYWORDS)

    @classmethod
    def _is_raster_like_asset(cls, asset: Dict[str, Any]) -> bool:
        href = str(asset.get('href') or '').strip().lower()
        media_type = str(asset.get('type') or '').strip().lower()

        if href.endswith(('.tif', '.tiff', '.jp2', '.j2k', '.cog')):
            return True

        if any(hint in media_type for hint in cls.RASTER_MEDIA_HINTS):
            return True

        return False

    @classmethod
    def _resolve_preferred_rgb_cog_href(cls, assets: Dict[str, Any]) -> Optional[str]:
        if not isinstance(assets, dict):
            return None

        for key in cls.RGB_ASSET_PRIORITY:
            asset = assets.get(key)
            if not isinstance(asset, dict):
                continue
            href = str(asset.get('href') or '').strip()
            if href and cls._is_raster_like_asset(asset):
                return href

        for _key, asset in assets.items():
            if not isinstance(asset, dict):
                continue
            href = str(asset.get('href') or '').strip()
            if href and cls._is_raster_like_asset(asset):
                return href

        return None

    def _request_collections(self, timeout: float) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        url = f'{self._api_root}/collections'
        data, err, status = qgis_request_json(
            method='GET',
            url=url,
            headers={'Accept': 'application/json'},
            timeout=timeout,
        )
        if err is None and isinstance(data, dict):
            collections = data.get('collections') or []
            if isinstance(collections, list):
                return [c for c in collections if isinstance(c, dict)], None

        logger.warning(
            'Planetary Computer collections via QGIS failed (status=%s): %s',
            status,
            err,
        )

        session = self.get_session()
        if session is None:
            return [], err or 'Collections request failed'

        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            payload = response.json() if response.content else {}
            collections = payload.get('collections') if isinstance(payload, dict) else []
            if isinstance(collections, list):
                return [c for c in collections if isinstance(c, dict)], None
            return [], 'Invalid collections payload'
        except Exception as exc:
            return [], str(exc)

    def get_collections(self) -> List[Dict[str, Any]]:
        if self._collection_cache is not None:
            return self._collection_cache

        collections_raw, _error = self._request_collections(timeout=self.timeout_search)
        normalized: List[Dict[str, Any]] = []
        for coll in collections_raw:
            coll_id = str(coll.get('id') or '').strip()
            if not coll_id:
                continue
            if not self._is_supported_collection(coll_id, coll):
                continue
            normalized.append({
                'id': coll_id,
                'title': str(coll.get('title') or coll_id),
                'description': str(coll.get('description') or ''),
                'keywords': coll.get('keywords') or [],
            })

        self._collection_cache = normalized
        return normalized

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
            'Planetary Computer search via QGIS failed (status=%s): %s',
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

    def _resolve_collections_for_search(self, collection: Optional[str]) -> List[str]:
        if collection:
            requested = [part.strip() for part in str(collection).split(',') if part.strip()]
            if requested:
                return requested

        candidates = self.get_collections()
        ids = [str(c.get('id') or '').strip() for c in candidates if isinstance(c, dict)]
        return [cid for cid in ids if cid]

    def _normalize_item_with_rgb_priority(self, feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        properties = feature.get('properties') if isinstance(feature.get('properties'), dict) else {}
        assets = feature.get('assets') if isinstance(feature.get('assets'), dict) else {}

        preferred_href = self._resolve_preferred_rgb_cog_href(assets)
        if not preferred_href:
            return None

        visual_asset = assets.get('visual')
        if not isinstance(visual_asset, dict):
            assets = dict(assets)
            assets['visual'] = {'href': preferred_href}
        else:
            visual_href = str(visual_asset.get('href') or '').strip()
            if visual_href != preferred_href:
                assets = dict(assets)
                assets['visual'] = {'href': preferred_href}

        cloud_cover = properties.get('eo:cloud_cover', properties.get('cloud_cover'))
        if cloud_cover is not None:
            properties['eo:cloud_cover'] = cloud_cover
            properties['cloud_cover'] = cloud_cover

        properties['preferred_cog_href'] = preferred_href

        return {
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

        collections = self._resolve_collections_for_search(collection)
        if not collections:
            return [], 'No Imagery/Fire COG collections available on Planetary Computer endpoint'

        payload: Dict[str, Any] = {
            'limit': max(1, min(int(limit), 1000)),
            'collections': collections,
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
            logger.error(f'Planetary Computer STAC search failed: {error}')
            return [], error

        if not isinstance(data, dict):
            return [], 'Invalid STAC response payload'

        features = data.get('features') or []
        if not isinstance(features, list):
            features = []

        items: List[Dict[str, Any]] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            item = self._normalize_item_with_rgb_priority(feature)
            if item is not None:
                items.append(item)

        items = self._filter_by_cloud(items, max_cloud_cover=max_cloud_cover)

        query = str(text_query or '').strip().lower()
        if query:
            filtered: List[Dict[str, Any]] = []
            for item in items:
                props = item.get('properties') if isinstance(item.get('properties'), dict) else {}
                searchable = ' '.join([
                    str(item.get('id') or ''),
                    str(item.get('collection') or ''),
                    str(props.get('platform') or ''),
                    str(props.get('constellation') or ''),
                    str(props.get('title') or ''),
                ]).lower()
                if query in searchable:
                    filtered.append(item)
            items = filtered

        if len(items) > int(limit):
            items = items[: int(limit)]

        logger.info('Planetary Computer STAC search returned %s item(s)', len(items))
        return items, None

    def resolve_cog_url(self, item: dict) -> str:
        """Prefer visual/render/preview RGB assets before generic COG pick."""
        assets = item.get('assets') if isinstance(item, dict) else {}
        assets = assets if isinstance(assets, dict) else {}

        for key in self.RGB_ASSET_PRIORITY:
            asset = assets.get(key)
            if not isinstance(asset, dict):
                continue
            href = str(asset.get('href') or '').strip()
            if href and self._is_raster_like_asset(asset):
                return href

        return super().resolve_cog_url(item)
