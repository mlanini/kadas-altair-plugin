"""Configurable STAC API connector for custom archive endpoints."""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from .element84_stac import Element84StacConnector, qgis_request_json
from ..logger import get_logger

logger = get_logger('connectors.custom_stac')


class CustomStacConnector(Element84StacConnector):
    """Search any STAC API endpoint using optional Bearer or Basic auth."""

    def __init__(self):
        super().__init__()
        self._api_root = ''
        self._auth_headers: Dict[str, str] = {}
        self._collections: List[Dict[str, Any]] = []
        self.authenticated = False
        self.last_error: Optional[str] = None
        self.timeout_search = 30.0

    def authenticate(
        self,
        credentials: Optional[Dict[str, Any]] = None,
    ) -> bool:
        credentials = credentials or {}
        endpoint = str(
            credentials.get('endpoint') or credentials.get('api_root') or ''
        ).strip().rstrip('/')
        for suffix in ('/search', '/collections'):
            if endpoint.lower().endswith(suffix):
                endpoint = endpoint[:-len(suffix)].rstrip('/')

        parsed = urlsplit(endpoint)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            self.last_error = 'Endpoint must be an absolute HTTP(S) URL'
            logger.warning('Custom STAC %s', self.last_error)
            self.authenticated = False
            return False

        self._api_root = endpoint
        try:
            self.timeout_search = max(
                5.0,
                min(float(credentials.get('timeout', self.timeout_search)), 120.0),
            )
        except (TypeError, ValueError):
            self.timeout_search = 30.0

        self._auth_headers = {'Accept': 'application/json'}
        access_token = str(credentials.get('access_token') or '').strip()
        username = str(credentials.get('username') or '').strip()
        password = str(credentials.get('password') or '')
        if access_token:
            self._auth_headers['Authorization'] = f'Bearer {access_token}'
        elif username or password:
            if not username or not password:
                self.last_error = 'Basic authentication requires both username and password'
                logger.warning('Custom STAC %s', self.last_error)
                self.authenticated = False
                return False
            basic = base64.b64encode(f'{username}:{password}'.encode('utf-8')).decode('ascii')
            self._auth_headers['Authorization'] = f'Basic {basic}'

        data, error = self._request_json('GET', f'{self._api_root}/collections')
        collections = data.get('collections') if isinstance(data, dict) else None
        if error or not isinstance(collections, list):
            self.last_error = error or 'Invalid STAC collections response'
            logger.warning('Custom STAC connection check failed: %s', self.last_error)
            self._collections = []
            self.authenticated = False
            return False

        self._collections = [
            {
                'id': str(collection.get('id') or '').strip(),
                'title': str(collection.get('title') or collection.get('id') or '').strip(),
                'description': str(collection.get('description') or ''),
            }
            for collection in collections
            if isinstance(collection, dict) and str(collection.get('id') or '').strip()
        ]
        self.last_error = None
        self.authenticated = True
        return True

    def _request_json(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        request_timeout = timeout if timeout is not None else self.timeout_search
        data, error, _ = qgis_request_json(
            method=method,
            url=url,
            headers=self._auth_headers,
            payload=payload,
            params=params,
            timeout=request_timeout,
        )
        if error is None:
            return data, None

        session = self.get_session()
        if session is None:
            return None, error

        try:
            if method == 'POST':
                response = session.post(
                    url,
                    headers=self._auth_headers,
                    json=payload,
                    timeout=request_timeout,
                )
            else:
                response = session.get(
                    url,
                    headers=self._auth_headers,
                    params=params,
                    timeout=request_timeout,
                )
            response.raise_for_status()
            result = response.json() if response.content else {}
            if isinstance(result, dict):
                return result, None
            return None, 'STAC endpoint returned a non-object JSON response'
        except Exception as exc:
            return None, str(exc)

    def get_collections(self) -> List[Dict[str, Any]]:
        return [dict(collection) for collection in self._collections]

    def get_asset_auth_headers(
        self,
        item: Dict[str, Any],
        href: str,
    ) -> Dict[str, str]:
        _ = item
        _ = href
        authorization = self._auth_headers.get('Authorization')
        return {'Authorization': authorization} if authorization else {}

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
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        if not self._api_root:
            return [], 'Custom STAC endpoint is not configured'

        request_timeout = self.timeout_search
        if timeout is not None:
            try:
                request_timeout = max(5.0, min(float(timeout), 120.0))
            except (TypeError, ValueError):
                pass

        payload: Dict[str, Any] = {'limit': max(1, min(int(limit), 1000))}
        if bbox and len(bbox) >= 4:
            payload['bbox'] = [float(value) for value in bbox[:4]]
        if start_date or end_date:
            payload['datetime'] = self._build_datetime_range(
                str(start_date or ''), str(end_date or '')
            )
        if collection:
            payload['collections'] = [
                part.strip() for part in str(collection).split(',') if part.strip()
            ]

        data, error = self._request_json(
            'POST', f'{self._api_root}/search', payload, timeout=request_timeout
        )
        if error:
            get_params = {
                key: ','.join(str(value) for value in values)
                if isinstance(values, list) else values
                for key, values in payload.items()
            }
            data, error = self._request_json(
                'GET',
                f'{self._api_root}/search',
                timeout=request_timeout,
                params=get_params,
            )

        if error:
            logger.warning('Custom STAC search failed: %s', error)
            return [], error
        if not isinstance(data, dict):
            return [], 'Invalid STAC search response'

        features = data.get('features') or []
        items = [
            self._normalize_item(feature)
            for feature in features
            if isinstance(feature, dict)
        ]
        items = self._filter_by_cloud(items, max_cloud_cover)
        items = self._filter_by_text(items, str(text_query or ''))
        return items[:max(0, int(limit))], None