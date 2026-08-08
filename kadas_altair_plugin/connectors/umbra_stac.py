"""
Umbra STAC Connector (dual mode)

- Open Data mode (default): public Umbra SAR Open Data catalog
- Commercial mode: Umbra Canopy STAC API v2 (Bearer token)

References:
- Open data catalog: https://s3.us-west-2.amazonaws.com/umbra-open-data-catalog/stac/catalog.json?.language=en
- Commercial STAC v2 overview: https://docs.canopy.umbra.space/reference/v2-stac-overview
"""

import logging
import json
import time
from typing import List, Dict, Optional, Any
from datetime import datetime

from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.umbra_stac')

try:
    from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager
    from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
    from qgis.PyQt.QtNetwork import QNetworkRequest
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False
    logger.warning("QGIS not available - Umbra connector will use fallback HTTP")


class UmbraSTACConnector(ConnectorBase):
    """
    Connector for Umbra SAR Open Data via STAC API
    
    Umbra provides up to 16cm resolution SAR imagery with frequent updates.
    SAR can capture images at night, through clouds, smoke, and rain.
    
    Architecture:
    - Root catalog: https://s3.us-west-2.amazonaws.com/umbra-open-data-catalog/stac/catalog.json?.language=en
    - Hierarchy: catalog.json → year/catalog.json → year-month/catalog.json → collection.json → items
    - No authentication required (public open data)
    - STAC 1.1.0 compliant
    """
    
    timeout_auth: float = 5.0      # Not used (no auth required)
    timeout_catalog: float = 30.0  # Root catalog load
    timeout_search: float = 60.0   # Full hierarchy traversal
    timeout_item: float = 15.0     # Individual item fetch
    
    # Umbra STAC endpoints
    CATALOG_URL = 'https://s3.us-west-2.amazonaws.com/umbra-open-data-catalog/stac/catalog.json?.language=en'
    CATALOG_BASE = 'https://s3.us-west-2.amazonaws.com/umbra-open-data-catalog/stac'

    # Umbra Canopy STAC v2 endpoints (commercial/archive)
    DEFAULT_API_BASE = 'https://api.canopy.umbra.space'
    COMMERCIAL_LANDING_PATH = '/v2/stac/'
    COMMERCIAL_COLLECTIONS_PATH = '/v2/stac/collections'
    COMMERCIAL_SEARCH_PATH = '/v2/stac/search'
    AUTH_TOKEN_URL = 'https://auth.canopy.umbra.space/oauth/token'
    
    def __init__(self):
        """Initialize Umbra STAC connector"""
        super().__init__()
        self._catalog = None
        self._collections = []
        self._items_cache = {}
        self._commercial_collections_cache: Optional[List[Dict[str, Any]]] = None
        self._use_commercial = False
        self._access_token: Optional[str] = None
        self._client_id: Optional[str] = None
        self._client_secret: Optional[str] = None
        self._token_expires_at: Optional[float] = None
        self._api_base_url: str = self.DEFAULT_API_BASE
        self._auth_header: Optional[str] = None
        logger.info("Initialized Umbra SAR Open Data STAC connector")
    
    def _build_commercial_url(self, path: str) -> str:
        base = (self._api_base_url or self.DEFAULT_API_BASE).strip().rstrip('/')
        if not path.startswith('/'):
            path = '/' + path
        return f"{base}{path}"

    def authenticate(self, credentials: dict) -> bool:
        """
        Authenticate connector.

        Behavior:
        - If ``access_token`` is provided, enable commercial STAC v2 mode.
        - Otherwise keep/open open-data mode.
        
        Args:
            credentials: Optional auth fields:
                - access_token: Umbra Canopy bearer token
                - client_id/client_secret: OAuth2 client credentials
                - api_base_url: Optional API base (default https://api.canopy.umbra.space)
            
            Missing/empty credentials fallback to open-data mode.
            
        Returns:
            bool: True if selected mode is usable
        """
        credentials = credentials or {}
        self._api_base_url = str(credentials.get('api_base_url') or self.DEFAULT_API_BASE).strip().rstrip('/')
        access_token = str(credentials.get('access_token') or '').strip()
        client_id = str(credentials.get('client_id') or '').strip()
        client_secret = str(credentials.get('client_secret') or '').strip()

        self._client_id = client_id or None
        self._client_secret = client_secret or None

        if not access_token and self._client_id and self._client_secret:
            token_response = self._request_m2m_access_token(self._client_id, self._client_secret)
            if token_response:
                access_token = token_response.get('access_token', '').strip()

        if not access_token:
            self._use_commercial = False
            self._access_token = None
            self._auth_header = None
            self._token_expires_at = None
            self._commercial_collections_cache = None
            logger.info("Umbra: open-data mode active (no authentication required)")
            return True

        self._use_commercial = True
        self._access_token = access_token
        self._auth_header = f"Bearer {access_token}"
        if self._token_expires_at is None:
            self._token_expires_at = time.time() + 23 * 3600
        self._commercial_collections_cache = None

        try:
            logger.info("Umbra: verifying commercial STAC token...")
            landing = self._commercial_get(self._build_commercial_url(self.COMMERCIAL_LANDING_PATH), self.timeout_auth)
            if landing is None:
                logger.error("Umbra: commercial authentication verification failed")
                return False

            if isinstance(landing, dict) and (landing.get('type') in ('Catalog', 'Collection') or 'links' in landing):
                logger.info("Umbra: commercial authentication successful")
                return True

            logger.error("Umbra: unexpected response from commercial STAC landing endpoint")
            return False
        except Exception as e:
            logger.error(f"Umbra: authentication error: {e}")
            return False

    def _request_m2m_access_token(self, client_id: str, client_secret: str) -> Optional[Dict[str, Any]]:
        """Request OAuth2 access token using Umbra client credentials flow."""
        try:
            audience = (self._api_base_url or self.DEFAULT_API_BASE).rstrip('/')
            payload = {
                'client_id': client_id,
                'client_secret': client_secret,
                'audience': audience,
                'grant_type': 'client_credentials',
            }

            if QGIS_AVAILABLE:
                request = QNetworkRequest(QUrl(self.AUTH_TOKEN_URL))
                request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
                request.setRawHeader(b"Accept", b"application/json")
                request.setRawHeader(b"User-Agent", b"KADAS-Altair-Plugin/1.0")

                nam = QgsNetworkAccessManager.instance()
                body = json.dumps(payload).encode('utf-8')
                reply = nam.post(request, body)

                loop = QEventLoop()
                reply.finished.connect(loop.quit)

                timer = QTimer()
                timer.setSingleShot(True)
                timer.timeout.connect(loop.quit)
                timer.start(int(self.timeout_auth * 1000))
                loop.exec_()

                if not reply.isFinished():
                    reply.abort()
                    logger.error('Umbra token request timeout')
                    return None

                if reply.error():
                    logger.error(f"Umbra token request error: {reply.errorString()}")
                    return None

                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if status_code and status_code >= 400:
                    logger.error(f"Umbra token request HTTP {status_code}")
                    return None

                data = reply.readAll().data().decode('utf-8')
            else:
                session = self.get_session()
                response = session.post(
                    self.AUTH_TOKEN_URL,
                    headers={
                        'Accept': 'application/json',
                        'Content-Type': 'application/json',
                    },
                    json=payload,
                    timeout=self.timeout_auth,
                    verify=self._verify_ssl,
                )
                response.raise_for_status()
                data = response.text

            token_payload = json.loads(data) if data else {}
            token = str(token_payload.get('access_token') or '').strip()
            expires_in = int(token_payload.get('expires_in') or 0)

            if not token:
                logger.error('Umbra token request succeeded but access_token missing')
                return None

            self._access_token = token
            self._auth_header = f"Bearer {token}"
            if expires_in > 0:
                self._token_expires_at = time.time() + max(60, expires_in - 120)
            else:
                self._token_expires_at = time.time() + 23 * 3600

            logger.info('Umbra: obtained M2M access token via client credentials')
            return token_payload

        except Exception as e:
            logger.error(f"Umbra token request failed: {e}")
            return None

    def _ensure_valid_commercial_token(self) -> bool:
        """Ensure commercial bearer token is available and not expired."""
        if self._auth_header and self._token_expires_at and time.time() < self._token_expires_at:
            return True

        if self._auth_header and self._token_expires_at is None:
            return True

        if self._client_id and self._client_secret:
            token_response = self._request_m2m_access_token(self._client_id, self._client_secret)
            return token_response is not None

        return bool(self._auth_header)

    def _commercial_get(self, url: str, timeout: float) -> Optional[Dict[str, Any]]:
        """Authenticated GET helper for commercial STAC v2."""
        if not self._ensure_valid_commercial_token() or not self._auth_header:
            logger.error("Umbra commercial: not authenticated")
            return None

        try:
            if QGIS_AVAILABLE:
                request = QNetworkRequest(QUrl(url))
                request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
                request.setRawHeader(b"Accept", b"application/json, application/geo+json")
                request.setRawHeader(b"Authorization", self._auth_header.encode("utf-8"))
                request.setRawHeader(b"User-Agent", b"KADAS-Altair-Plugin/1.0")

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
                    logger.error(f"Umbra commercial GET timeout after {timeout}s")
                    return None

                if reply.error():
                    logger.error(f"Umbra commercial GET error: {reply.errorString()}")
                    return None

                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if status_code and status_code >= 400:
                    logger.error(f"Umbra commercial GET HTTP {status_code}")
                    return None

                data = reply.readAll().data().decode('utf-8')
            else:
                session = self.get_session()
                response = session.get(
                    url,
                    headers={
                        'Accept': 'application/json, application/geo+json',
                        'Authorization': self._auth_header,
                    },
                    timeout=timeout,
                    verify=self._verify_ssl,
                )
                response.raise_for_status()
                data = response.text

            return json.loads(data) if data else {}
        except Exception as e:
            logger.error(f"Umbra commercial GET failed ({url}): {e}")
            return None

    def _commercial_post(self, url: str, payload: Dict[str, Any], timeout: float) -> Optional[Dict[str, Any]]:
        """Authenticated POST helper for commercial STAC v2."""
        if not self._ensure_valid_commercial_token() or not self._auth_header:
            logger.error("Umbra commercial: not authenticated")
            return None

        try:
            if QGIS_AVAILABLE:
                request = QNetworkRequest(QUrl(url))
                request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
                request.setRawHeader(b"Accept", b"application/json, application/geo+json")
                request.setRawHeader(b"Authorization", self._auth_header.encode("utf-8"))
                request.setRawHeader(b"User-Agent", b"KADAS-Altair-Plugin/1.0")

                nam = QgsNetworkAccessManager.instance()
                body = json.dumps(payload).encode('utf-8')
                reply = nam.post(request, body)

                loop = QEventLoop()
                reply.finished.connect(loop.quit)

                timer = QTimer()
                timer.setSingleShot(True)
                timer.timeout.connect(loop.quit)
                timer.start(int(timeout * 1000))

                loop.exec_()

                if not reply.isFinished():
                    reply.abort()
                    logger.error(f"Umbra commercial POST timeout after {timeout}s")
                    return None

                if reply.error():
                    logger.error(f"Umbra commercial POST error: {reply.errorString()}")
                    return None

                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if status_code and status_code >= 400:
                    logger.error(f"Umbra commercial POST HTTP {status_code}")
                    return None

                data = reply.readAll().data().decode('utf-8')
            else:
                session = self.get_session()
                response = session.post(
                    url,
                    headers={
                        'Accept': 'application/json, application/geo+json',
                        'Content-Type': 'application/json',
                        'Authorization': self._auth_header,
                    },
                    json=payload,
                    timeout=timeout,
                    verify=self._verify_ssl,
                )
                response.raise_for_status()
                data = response.text

            return json.loads(data) if data else {}
        except Exception as e:
            logger.error(f"Umbra commercial POST failed ({url}): {e}")
            return None
    
    def load_catalog(self, timeout: Optional[float] = None) -> bool:
        """
        Load root STAC catalog
        
        Args:
            timeout: Request timeout in seconds (default: self.timeout_catalog)
            
        Returns:
            bool: True if catalog loaded successfully
        """
        if timeout is None:
            timeout = self.timeout_catalog
            
        try:
            logger.info(f"Loading Umbra STAC catalog from {self.CATALOG_URL}")
            
            if QGIS_AVAILABLE:
                catalog_data = self._fetch_qgis(self.CATALOG_URL, timeout)
            else:
                catalog_data = self._fetch_fallback(self.CATALOG_URL, timeout)
            
            if not catalog_data:
                logger.error("Failed to fetch Umbra catalog")
                return False
            
            self._catalog = json.loads(catalog_data)
            logger.info(f"Loaded Umbra catalog: {self._catalog.get('title', 'Unknown')}")
            logger.info(f"STAC version: {self._catalog.get('stac_version', 'Unknown')}")
            
            return True
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Umbra catalog JSON: {e}")
            return False
        except Exception as e:
            logger.error(f"Error loading Umbra catalog: {e}")
            return False
    
    def get_collections(self) -> List[Dict]:
        """
        Get available year/month collections from catalog
        
        Returns:
            List of collection info dicts with keys: id, title, href, asset_count
        """
        if self._use_commercial:
            return self._get_commercial_collections()

        if not self._catalog:
            if not self.load_catalog():
                logger.error("Failed to load catalog for collections")
                return []
        
        collections = []
        
        # Extract year catalogs (child links)
        for link in self._catalog.get('links', []):
            if link.get('rel') == 'child':
                year_title = link.get('title', 'Unknown')
                year_href = f"{self.CATALOG_BASE}/{link.get('href', '')}"
                
                # Fetch year catalog to count month collections
                try:
                    if QGIS_AVAILABLE:
                        year_data = self._fetch_qgis(year_href, self.timeout_item)
                    else:
                        year_data = self._fetch_fallback(year_href, self.timeout_item)
                    
                    if year_data:
                        year_catalog = json.loads(year_data)
                        # Count month collections in this year
                        month_count = len([l for l in year_catalog.get('links', []) if l.get('rel') == 'child'])
                        
                        collections.append({
                            'id': year_title,
                            'title': year_title,
                            'href': year_href,
                            'asset_count': month_count,  # Number of month catalogs
                            'type': 'year_catalog'
                        })
                    else:
                        # Fallback: add without count
                        collections.append({
                            'id': year_title,
                            'title': year_title,
                            'href': year_href,
                            'asset_count': 0,
                            'type': 'year_catalog'
                        })
                except Exception as e:
                    logger.warning(f"Error fetching year catalog {year_href}: {e}")
                    # Add anyway with 0 count
                    collections.append({
                        'id': year_title,
                        'title': year_title,
                        'href': year_href,
                        'asset_count': 0,
                        'type': 'year_catalog'
                    })
        
        logger.info(f"Found {len(collections)} year catalogs")
        return collections

    def _get_commercial_collections(self) -> List[Dict[str, Any]]:
        """Get commercial Umbra collections from /v2/stac/collections."""
        if not self._auth_header:
            logger.warning('Umbra commercial collections requested without authentication')
            return []

        if self._commercial_collections_cache is not None:
            return self._commercial_collections_cache

        url = self._build_commercial_url(self.COMMERCIAL_COLLECTIONS_PATH)
        payload = self._commercial_get(url, self.timeout_search)
        if payload is None:
            self._commercial_collections_cache = []
            return self._commercial_collections_cache

        collections = payload.get('collections', []) if isinstance(payload, dict) else []
        normalized: List[Dict[str, Any]] = []
        for collection in collections if isinstance(collections, list) else []:
            if not isinstance(collection, dict):
                continue
            collection_id = str(collection.get('id', '')).strip()
            if not collection_id:
                continue
            normalized.append({
                'id': collection_id,
                'title': collection.get('title') or collection_id,
                'description': collection.get('description') or '',
                'asset_count': 0,
                'type': 'collection',
            })

        self._commercial_collections_cache = normalized
        return normalized
    
    def get_month_collections(self, year_href: str, timeout: Optional[float] = None) -> List[Dict]:
        """
        Get month collections for a specific year
        
        Args:
            year_href: URL to year catalog
            timeout: Request timeout
            
        Returns:
            List of month collection dicts
        """
        if timeout is None:
            timeout = self.timeout_item
        
        try:
            if QGIS_AVAILABLE:
                year_data = self._fetch_qgis(year_href, timeout)
            else:
                year_data = self._fetch_fallback(year_href, timeout)
            
            if not year_data:
                return []
            
            year_catalog = json.loads(year_data)
            months = []
            
            for link in year_catalog.get('links', []):
                if link.get('rel') == 'child':
                    href_relative = link.get('href', '')
                    # Convert relative to absolute URL
                    if href_relative.startswith('./'):
                        base_url = year_href.rsplit('/', 1)[0]
                        href_absolute = f"{base_url}/{href_relative[2:]}"
                    else:
                        href_absolute = href_relative
                    
                    months.append({
                        'id': link.get('title', 'Unknown'),
                        'title': link.get('title', 'Unknown'),
                        'href': href_absolute,
                        'type': 'month_catalog'
                    })
            
            return months
            
        except Exception as e:
            logger.error(f"Error loading month collections from {year_href}: {e}")
            return []
    
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
        """Normalized entrypoint for ConnectorManager.

        Builds the dict expected by :meth:`search` from the standard
        ``search_unified`` parameters.
        """
        query_dict: dict = {'limit': limit}
        if bbox:
            query_dict['bbox'] = bbox
        if start_date and end_date:
            query_dict['datetime'] = f"{start_date}/{end_date}"
        elif start_date:
            query_dict['datetime'] = f"{start_date}/.."
        elif end_date:
            query_dict['datetime'] = f"../{end_date}"
        if collection:
            if len(collection) == 4 and collection.isdigit():
                query_dict['year'] = collection
            elif len(collection) == 7 and collection[4] == '-':
                query_dict['month'] = collection
        results = self.search(query_dict)
        return results, None

    def search(self, query: dict) -> List[Dict]:
        """
        Search Umbra STAC catalog
        
        Args:
            query: Search parameters dict with optional keys:
                - bbox: [west, south, east, north]
                - datetime: ISO 8601 date range
                - year: Filter by year (e.g., "2025")
                - month: Filter by year-month (e.g., "2025-01")
                - limit: Max results (default: 10000 - effectively unlimited)
        
        Returns:
            List of STAC items matching query
        """
        if self._use_commercial:
            return self._search_commercial(query)

        if not self._catalog:
            if not self.load_catalog():
                logger.error("Failed to load catalog for search")
                return []
        
        # High default limit to retrieve all matching results
        limit = query.get('limit', 10000)
        year_filter = query.get('year')
        month_filter = query.get('month')
        bbox = query.get('bbox')
        
        logger.info(f"🔍 Umbra search START: limit={limit}, bbox={'YES' if bbox else 'NO'}, year={year_filter or 'ALL'}, month={month_filter or 'ALL'}")
        
        results = []
        total_months_searched = 0
        total_days_searched = 0
        
        # Get year collections
        year_collections = self.get_collections()
        
        # Filter by year if specified
        if year_filter:
            year_collections = [c for c in year_collections if c['id'] == year_filter]
        
        logger.info(f"Searching {len(year_collections)} year catalogs...")
        
        for year_idx, year_col in enumerate(year_collections, 1):
            if len(results) >= limit:
                logger.info(f"Reached limit of {limit} items, stopping search")
                break
            
            # Get month collections for this year
            month_collections = self.get_month_collections(year_col['href'])
            
            # Filter by month if specified
            if month_filter:
                month_collections = [c for c in month_collections if c['id'] == month_filter]
            
            logger.info(f"Year {year_col['id']}: found {len(month_collections)} months to search")
            
            for month_idx, month_col in enumerate(month_collections, 1):
                if len(results) >= limit:
                    break
                
                total_months_searched += 1
                logger.info(f"📅 Searching month {month_col['id']} ({month_idx}/{len(month_collections)}) - current results: {len(results)}/{limit}")
                
                # Fetch items from month collection (includes day navigation)
                items = self._fetch_collection_items(month_col['href'])
                
                logger.info(f"   Found {len(items)} items in month {month_col['id']}")
                
                # Filter by bbox if specified
                if bbox and items:
                    items_before = len(items)
                    items = self._filter_by_bbox(items, bbox)
                    logger.info(f"   Bbox filter: {items_before} → {len(items)} items")
                
                results.extend(items[:limit - len(results)])
        
        logger.info(f"📊 Umbra search STATS:")
        logger.info(f"   Months searched: {total_months_searched}")
        logger.info(f"   Items found: {len(results)}")
        logger.info(f"✅ Search completed: {len(results)} items")
        return results

    def _search_commercial(self, query: dict) -> List[Dict[str, Any]]:
        """Search Umbra commercial archive via /v2/stac/search."""
        if not self._auth_header:
            logger.error('Umbra commercial search requested without authentication')
            return []

        requested_limit = int(query.get('limit', 100))
        requested_limit = max(1, requested_limit)

        collections = query.get('collections')
        if collections is None:
            if query.get('collection'):
                collections = [query.get('collection')]
            else:
                collections_info = self._get_commercial_collections()
                collections = [c.get('id') for c in collections_info if c.get('id')]

        if not collections:
            logger.warning('Umbra commercial search: no collections selected/available')
            return []

        page_limit = min(requested_limit, 10000)

        payload: Dict[str, Any] = {
            'collections': collections,
            'limit': page_limit,
        }

        bbox = query.get('bbox')
        if bbox and len(bbox) >= 4:
            payload['bbox'] = [bbox[0], bbox[1], bbox[2], bbox[3]]

        datetime_expr = query.get('datetime')
        if datetime_expr:
            payload['datetime'] = datetime_expr

        url = self._build_commercial_url(self.COMMERCIAL_SEARCH_PATH)
        results: List[Dict[str, Any]] = []
        next_token = None
        iteration = 0

        while len(results) < requested_limit:
            iteration += 1
            req_body = dict(payload)
            if next_token:
                req_body['token'] = next_token

            response = self._commercial_post(url, req_body, self.timeout_search)
            if response is None:
                break

            features = response.get('features', []) if isinstance(response, dict) else []
            if not isinstance(features, list) or not features:
                break

            for feature in features:
                if len(results) >= requested_limit:
                    break
                if isinstance(feature, dict):
                    results.append(feature)

            context = response.get('context', {}) if isinstance(response, dict) else {}
            context_next = context.get('next') if isinstance(context, dict) else None
            token_next = response.get('token') if isinstance(response, dict) else None

            if context_next is not None and context_next != '':
                next_token = str(context_next)
            elif token_next is not None and token_next != '':
                next_token = str(token_next)
            else:
                break

            if iteration > 100:
                logger.warning('Umbra commercial search: pagination safety stop')
                break

        logger.info(f"Umbra commercial search completed: {len(results)} items")
        return results
    
    def _fetch_collection_items(self, collection_href: str) -> List[Dict]:
        """
        Fetch STAC items from a month collection catalog.
        Umbra structure: month -> day catalogs -> items
        
        Args:
            collection_href: URL to month catalog
            
        Returns:
            List of STAC items
        """
        try:
            if QGIS_AVAILABLE:
                catalog_data = self._fetch_qgis(collection_href, self.timeout_item)
            else:
                catalog_data = self._fetch_fallback(collection_href, self.timeout_item)
            
            if not catalog_data:
                return []
            
            catalog = json.loads(catalog_data)
            items = []
            
            # First look for child day catalogs
            day_catalogs = []
            for link in catalog.get('links', []):
                if link.get('rel') == 'child':
                    day_href = link.get('href', '')
                    # Convert relative to absolute
                    if day_href.startswith('./'):
                        base_url = collection_href.rsplit('/', 1)[0]
                        day_href = f"{base_url}/{day_href[2:]}"
                    day_catalogs.append(day_href)
            
            # Fetch items from each day catalog
            if day_catalogs:
                logger.debug(f"Found {len(day_catalogs)} day catalogs in {collection_href}")
                for day_href in day_catalogs:
                    day_items = self._fetch_day_items(day_href)
                    logger.debug(f"Fetched {len(day_items)} items from day catalog {day_href}")
                    items.extend(day_items)
            else:
                # Fallback: look for direct item links (older STAC versions)
                for link in catalog.get('links', []):
                    if link.get('rel') == 'item':
                        item_href = link.get('href', '')
                        # Convert relative to absolute
                        if item_href.startswith('./'):
                            base_url = collection_href.rsplit('/', 1)[0]
                            item_href = f"{base_url}/{item_href[2:]}"
                        
                        # Fetch individual item
                        item = self._fetch_item(item_href)
                        if item:
                            items.append(item)
            
            logger.debug(f"Fetched {len(items)} items from {collection_href}")
            return items
            
        except Exception as e:
            logger.error(f"Error fetching items from {collection_href}: {e}")
            return []
    
    def _fetch_day_items(self, day_href: str) -> List[Dict]:
        """
        Fetch STAC items from a day catalog
        
        Args:
            day_href: URL to day catalog
            
        Returns:
            List of STAC items
        """
        try:
            if QGIS_AVAILABLE:
                day_data = self._fetch_qgis(day_href, self.timeout_item)
            else:
                day_data = self._fetch_fallback(day_href, self.timeout_item)
            
            if not day_data:
                return []
            
            day_catalog = json.loads(day_data)
            items = []
            
            # Look for item links in day catalog
            for link in day_catalog.get('links', []):
                if link.get('rel') == 'item':
                    item_href = link.get('href', '')
                    # Convert relative to absolute
                    if item_href.startswith('./'):
                        base_url = day_href.rsplit('/', 1)[0]
                        item_href = f"{base_url}/{item_href[2:]}"
                    
                    # Fetch individual item
                    item = self._fetch_item(item_href)
                    if item:
                        items.append(item)
            
            return items
            
        except Exception as e:
            logger.error(f"Error fetching day items from {day_href}: {e}")
            return []
    
    def _fetch_item(self, item_href: str) -> Optional[Dict]:
        """
        Fetch individual STAC item
        
        Args:
            item_href: URL to item JSON
            
        Returns:
            STAC item dict or None
        """
        try:
            if QGIS_AVAILABLE:
                item_data = self._fetch_qgis(item_href, self.timeout_item)
            else:
                item_data = self._fetch_fallback(item_href, self.timeout_item)
            
            if item_data:
                return json.loads(item_data)
            return None
            
        except Exception as e:
            logger.error(f"Error fetching item {item_href}: {e}")
            return None
    
    def _filter_by_bbox(self, items: List[Dict], bbox: List[float]) -> List[Dict]:
        """
        Filter STAC items by bounding box
        
        Args:
            items: List of STAC items
            bbox: [west, south, east, north]
            
        Returns:
            Filtered list of items
        """
        filtered = []
        west, south, east, north = bbox
        
        logger.debug(f"Filtering {len(items)} items by bbox {bbox}")
        
        for item in items:
            item_bbox = item.get('bbox')
            if not item_bbox or len(item_bbox) < 4:
                continue
            
            # Check if bboxes intersect
            item_west, item_south, item_east, item_north = item_bbox[:4]
            
            if not (item_east < west or item_west > east or 
                    item_north < south or item_south > north):
                filtered.append(item)
        
        logger.debug(f"Bbox filter: {len(filtered)} items match out of {len(items)}")
        return filtered
    
    def _fetch_qgis(self, url: str, timeout: float) -> Optional[str]:
        """
        Fetch URL content using QGIS network manager (proxy-aware)
        
        Args:
            url: URL to fetch
            timeout: Timeout in seconds
            
        Returns:
            Response content as string or None
        """
        try:
            # Setup proxy
            QgsNetworkAccessManager.instance().setupDefaultProxyAndCache()
            
            # Create event loop for timeout
            loop = QEventLoop()
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            
            # Make request
            request = QNetworkRequest(QUrl(url))
            blocking_request = QgsBlockingNetworkRequest()
            
            # Start timeout timer
            timeout_ms = int(timeout * 1000)
            timer.start(timeout_ms)
            
            # Execute request
            error = blocking_request.get(request, forceRefresh=True)
            
            # Stop timer
            timer.stop()
            
            if error != QgsBlockingNetworkRequest.NoError:
                logger.error(f"QGIS network request failed: {blocking_request.errorMessage()}")
                return None
            
            reply = blocking_request.reply()
            content = reply.content()
            
            return content.data().decode('utf-8')
            
        except Exception as e:
            logger.error(f"QGIS fetch error for {url}: {e}")
            return None
    
    def _fetch_fallback(self, url: str, timeout: float) -> Optional[str]:
        """
        Fallback HTTP fetch using requests library
        
        Args:
            url: URL to fetch
            timeout: Timeout in seconds
            
        Returns:
            Response content as string or None
        """
        try:
            session = self.get_session()
            response = session.get(url, timeout=timeout, verify=self._verify_ssl)
            response.raise_for_status()
            return response.text
            
        except Exception as e:
            logger.error(f"Fallback fetch error for {url}: {e}")
            return None
    
    def get_tile_url(self, result: dict, z: int, x: int, y: int) -> str:
        """
        Umbra provides GeoTIFF assets, not tiled services
        
        Returns empty string as Umbra uses COG/GeoTIFF assets
        """
        return ""
    
    def get_asset_urls(self, item: Dict) -> Dict[str, str]:
        """
        Extract asset URLs from STAC item
        
        Umbra provides multiple product types:
        - GEC: Geocoded Ellipsoid Corrected (GeoTIFF)
        - SICD: Sensor Independent Complex Data
        - SIDD: Sensor Independent Derived Data
        - CPHD: Compensated Phase History Data
        
        Args:
            item: STAC item dict
            
        Returns:
            Dict of asset_key -> URL
        """
        assets = {}
        
        for asset_key, asset_info in item.get('assets', {}).items():
            href = asset_info.get('href', '')
            asset_type = asset_info.get('type', '')
            title = asset_info.get('title', asset_key)
            
            # Prioritize GEC (GeoTIFF) for visualization
            if 'GEC' in asset_key.upper() or 'image/tiff' in asset_type:
                assets[asset_key] = {
                    'href': href,
                    'type': asset_type,
                    'title': title,
                    'priority': 1
                }
            elif any(fmt in asset_key.upper() for fmt in ['SICD', 'SIDD', 'CPHD']):
                assets[asset_key] = {
                    'href': href,
                    'type': asset_type,
                    'title': title,
                    'priority': 2
                }
            else:
                assets[asset_key] = {
                    'href': href,
                    'type': asset_type,
                    'title': title,
                    'priority': 3
                }
        
        return assets
    
    def get_preview_url(self, item: Dict) -> Optional[str]:
        """
        Get preview/thumbnail URL for STAC item
        
        Args:
            item: STAC item dict
            
        Returns:
            Preview image URL or None
        """
        # Look for thumbnail or preview asset
        for asset_key in ['thumbnail', 'preview', 'overview']:
            asset = item.get('assets', {}).get(asset_key)
            if asset:
                return asset.get('href')
        
        return None
