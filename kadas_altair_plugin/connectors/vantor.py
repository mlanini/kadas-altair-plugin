"""Vantor Open Data Connector

Architecture inspired by kadas-vantor-plugin:
- GitHub dataset: datasets.csv + {event}.geojson
- Network: QgsNetworkAccessManager (proxy-aware)
- Timeouts: 120s (events), 180s (footprints)
- COG loading: visual, ms_analytic, pan_analytic
- Performance: DataFetchWorker pattern for async loading

References:
- https://github.com/mlanini/kadas-vantor-plugin
- https://github.com/opengeos/maxar-open-data
"""
import json
import os
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin, urlencode
from urllib.parse import urlparse, parse_qs

try:
    from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer, QSettings
    from qgis.PyQt.QtNetwork import QNetworkRequest
    from qgis.core import QgsNetworkAccessManager
    QGIS_AVAILABLE = True
except ImportError:
    QSettings = None
    QGIS_AVAILABLE = False

from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.vantor')


# GitHub URLs for Vantor Open Data (same pattern as kadas-vantor-plugin)
GITHUB_RAW_URL = "https://raw.githubusercontent.com/opengeos/maxar-open-data/master"
DATASETS_CSV_URL = f"{GITHUB_RAW_URL}/datasets.csv"
GEOJSON_URL_TEMPLATE = f"{GITHUB_RAW_URL}/datasets/{{event}}.geojson"

# STAC catalog URLs.
# Include both Vantor and Maxar Open Data catalogs so assets from either source
# are discoverable through the same connector.
STAC_CATALOG_URLS = [
    "https://vantor-opendata.s3.amazonaws.com/events/catalog.json",
    "https://maxar-opendata.s3.dualstack.us-west-2.amazonaws.com/events/catalog.json",
]

# Timeouts (same as kadas-vantor-plugin)
TIMEOUT_EVENTS = 120  # seconds for datasets.csv
TIMEOUT_FOOTPRINTS = 180  # seconds for large GeoJSON files

# Vantor Discovery API (Maxar) - used for archive searches
DISCOVERY_BASE_URL = "https://api.maxar.com/discovery/v1"
DISCOVERY_IMAGERY_SEARCH_PATH = "/catalogs/imagery/search"
DISCOVERY_ROOT_SEARCH_PATH = "/search"
DISCOVERY_TIMEOUT_DEFAULT = 60  # seconds
TASKING_TIMEOUT_DEFAULT = 60  # seconds

# Common imagery collections recommended by Discovery docs for satellite imagery.
DISCOVERY_IMAGERY_COLLECTIONS = [
    "ge01", "wv01", "wv02", "wv03-vnir", "wv04", "lg01", "lg02", "lg03", "lg04",
]


def _event_name_from_collection_href(href: str) -> str:
    """Derive stable event name from a STAC collection href.

    Example:
    - https://.../events/Venezuela-Earthquake-Jun-2026/collection.json
      -> Venezuela-Earthquake-Jun-2026
    """
    text = str(href or '').strip()
    if not text:
        return ''

    parsed = urlparse(text)
    path_parts = [p for p in parsed.path.split('/') if p]
    if not path_parts:
        return ''

    tail = path_parts[-1].lower()
    if tail in ('collection.json', 'collection') and len(path_parts) >= 2:
        return path_parts[-2]

    return path_parts[-1]


class VantorConnector(ConnectorBase):
    """Vantor Open Data connector using GitHub dataset
    
    Features (from kadas-vantor-plugin):
    - Event browsing from datasets.csv
    - Footprint loading from GeoJSON files
    - COG imagery: visual, ms_analytic, pan_analytic
    - Proxy-aware network access
    - Configurable timeouts
    - Cloud cover and date filtering
    
    Data source: https://github.com/opengeos/maxar-open-data
    """
    
    def __init__(self):
        super().__init__()
        self.name = "Vantor Open Data"
        self.events = []  # List of (event_name, tile_count)
        self.current_event = None
        self.footprints_cache = {}  # Cache for loaded GeoJSON
        self.event_sources = {}  # event_name -> {'mode': 'github'|'stac', 'ref': event_or_href}
        self.discovery_enabled = True
        self.discovery_base_url = DISCOVERY_BASE_URL
        self.discovery_timeout = DISCOVERY_TIMEOUT_DEFAULT
        self.discovery_search_path = DISCOVERY_IMAGERY_SEARCH_PATH
        self.discovery_api_key = ""
        self.discovery_access_token = ""
        self.tasking_base_url = ""
        self.tasking_create_path = "/tasking/v2/requests"
        self.tasking_list_path = "/tasking/v2/requests"
        self.tasking_timeout = TASKING_TIMEOUT_DEFAULT
        self.tasking_api_key = ""
        self.tasking_access_token = ""
        self._last_search_next_token: Optional[str] = None
        self.authenticated = True  # No authentication required
        self._load_discovery_config()
        
    def authenticate(self, **kwargs) -> bool:
        """No authentication required for Vantor Open Data
        
        Loads available events from GitHub datasets.csv automatically.
        
        Returns:
            bool: Always True (public data)
        """
        # Optional Discovery API credentials/config can be passed via kwargs.
        self._apply_discovery_kwargs(kwargs)
        self.authenticated = True
        logger.info("Vantor: No authentication required (public data)")
        
        # Preload events from GitHub (like kadas-vantor-plugin pattern)
        try:
            self.load_events()
            logger.info(f"Vantor: Loaded {len(self.events)} events during authentication")
        except Exception as e:
            logger.warning(f"Vantor: Failed to preload events (will retry later): {e}")
            # Don't fail authentication if event loading fails
            # Events can be loaded later when needed
        
        return True

    def _load_discovery_config(self) -> None:
        """Load Discovery API configuration from settings/env.

        Priority:
        1) QSettings (if available)
        2) Environment variables
        """
        # QSettings
        if QSettings is not None:
            try:
                settings = QSettings()
                self.discovery_enabled = settings.value(
                    "AltairEOData/vantor_discovery_enabled", True, type=bool
                )
                self.discovery_base_url = str(
                    settings.value(
                        "AltairEOData/vantor_discovery_base_url",
                        DISCOVERY_BASE_URL,
                    )
                ).strip() or DISCOVERY_BASE_URL
                self.discovery_timeout = int(
                    settings.value(
                        "AltairEOData/vantor_discovery_timeout",
                        DISCOVERY_TIMEOUT_DEFAULT,
                    )
                )
                self.discovery_search_path = str(
                    settings.value(
                        "AltairEOData/vantor_discovery_search_path",
                        DISCOVERY_IMAGERY_SEARCH_PATH,
                    )
                ).strip() or DISCOVERY_IMAGERY_SEARCH_PATH
                self.tasking_base_url = str(
                    settings.value(
                        "AltairEOData/vantor_tasking_base_url",
                        "",
                    )
                ).strip().rstrip('/')
                self.tasking_create_path = str(
                    settings.value(
                        "AltairEOData/vantor_tasking_create_path",
                        '/tasking/v2/requests',
                    )
                ).strip() or '/tasking/v2/requests'
                self.tasking_list_path = str(
                    settings.value(
                        "AltairEOData/vantor_tasking_list_path",
                        '/tasking/v2/requests',
                    )
                ).strip() or '/tasking/v2/requests'
                self.tasking_timeout = int(
                    settings.value(
                        "AltairEOData/vantor_tasking_timeout",
                        TASKING_TIMEOUT_DEFAULT,
                    )
                )
            except Exception as e:
                logger.debug(f"Vantor: failed to read Discovery settings: {e}")

        # Environment overrides / credentials
        self.discovery_api_key = (
            os.environ.get("VANTOR_DISCOVERY_API_KEY", "").strip()
            or os.environ.get("MAXAR_API_KEY", "").strip()
        )
        self.discovery_access_token = (
            os.environ.get("VANTOR_DISCOVERY_ACCESS_TOKEN", "").strip()
            or os.environ.get("MAXAR_ACCESS_TOKEN", "").strip()
        )
        self.discovery_search_path = (
            os.environ.get("VANTOR_DISCOVERY_SEARCH_PATH", "").strip()
            or self.discovery_search_path
        )
        self.tasking_base_url = (
            os.environ.get("VANTOR_TASKING_BASE_URL", "").strip().rstrip('/')
            or self.tasking_base_url
        )
        self.tasking_create_path = (
            os.environ.get("VANTOR_TASKING_CREATE_PATH", "").strip()
            or self.tasking_create_path
        )
        self.tasking_list_path = (
            os.environ.get("VANTOR_TASKING_LIST_PATH", "").strip()
            or self.tasking_list_path
        )
        tasking_timeout_env = os.environ.get("VANTOR_TASKING_TIMEOUT", "").strip()
        if tasking_timeout_env:
            try:
                self.tasking_timeout = max(5, int(tasking_timeout_env))
            except Exception:
                pass
        self.tasking_api_key = (
            os.environ.get("VANTOR_TASKING_API_KEY", "").strip()
            or self.discovery_api_key
        )
        self.tasking_access_token = (
            os.environ.get("VANTOR_TASKING_ACCESS_TOKEN", "").strip()
            or self.discovery_access_token
        )

    def _apply_discovery_kwargs(self, kwargs: Optional[Dict[str, Any]]) -> None:
        """Apply runtime Discovery options passed through authenticate()."""
        if not kwargs:
            return

        # ConnectorManager passes provider settings under the `credentials` key.
        nested_credentials = kwargs.get('credentials')
        if isinstance(nested_credentials, dict):
            merged_kwargs = dict(nested_credentials)
            merged_kwargs.update({
                key: value for key, value in kwargs.items() if key != 'credentials'
            })
            kwargs = merged_kwargs

        if 'discovery_enabled' in kwargs:
            self.discovery_enabled = bool(kwargs.get('discovery_enabled'))

        base_url = str(kwargs.get('discovery_base_url', '') or '').strip()
        if base_url:
            self.discovery_base_url = base_url

        timeout_val = kwargs.get('discovery_timeout')
        if timeout_val is not None:
            try:
                self.discovery_timeout = max(5, int(timeout_val))
            except Exception:
                pass

        search_path = str(
            kwargs.get('discovery_search_path', '')
            or kwargs.get('vantor_discovery_search_path', '')
        ).strip()
        if search_path:
            self.discovery_search_path = search_path

        api_key = str(kwargs.get('api_key', '') or kwargs.get('discovery_api_key', '')).strip()
        if api_key:
            self.discovery_api_key = api_key

        access_token = str(
            kwargs.get('access_token', '') or kwargs.get('discovery_access_token', '')
        ).strip()
        if access_token:
            self.discovery_access_token = access_token

        tasking_base_url = str(kwargs.get('tasking_base_url', '')).strip().rstrip('/')
        if tasking_base_url:
            self.tasking_base_url = tasking_base_url

        tasking_create_path = str(kwargs.get('tasking_create_path', '')).strip()
        if tasking_create_path:
            self.tasking_create_path = tasking_create_path

        tasking_list_path = str(kwargs.get('tasking_list_path', '')).strip()
        if tasking_list_path:
            self.tasking_list_path = tasking_list_path

        tasking_timeout = kwargs.get('tasking_timeout')
        if tasking_timeout is not None:
            try:
                self.tasking_timeout = max(5, int(tasking_timeout))
            except Exception:
                pass

        tasking_api_key = str(
            kwargs.get('tasking_api_key', '') or kwargs.get('api_key', '')
        ).strip()
        if tasking_api_key:
            self.tasking_api_key = tasking_api_key

        tasking_access_token = str(
            kwargs.get('tasking_access_token', '') or kwargs.get('access_token', '')
        ).strip()
        if tasking_access_token:
            self.tasking_access_token = tasking_access_token

    def _discovery_headers(self) -> Dict[str, str]:
        """Build optional auth headers for Discovery API requests."""
        headers = {
            'Accept': 'application/geo+json, application/json',
            'User-Agent': 'KADAS-Altair-Plugin/1.0',
        }

        if self.discovery_api_key:
            # Discovery docs use `maxar-api-key`; keep `x-api-key` for compatibility.
            headers['maxar-api-key'] = self.discovery_api_key
            headers['x-api-key'] = self.discovery_api_key
        if self.discovery_access_token:
            headers['Authorization'] = f'Bearer {self.discovery_access_token}'

        return headers

    def _tasking_headers(self) -> Dict[str, str]:
        """Build auth headers for Vantor tasking requests."""
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'KADAS-Altair-Plugin/1.0',
        }

        api_key = self.tasking_api_key or self.discovery_api_key
        access_token = self.tasking_access_token or self.discovery_access_token
        if api_key:
            headers['maxar-api-key'] = api_key
            headers['x-api-key'] = api_key
        if access_token:
            headers['Authorization'] = f'Bearer {access_token}'

        return headers

    @staticmethod
    def _normalize_path(path: str, default: str) -> str:
        text = str(path or '').strip()
        if not text:
            text = default
        if not text.startswith('/'):
            text = '/' + text
        return text

    def tasking_url(self) -> str:
        """Return configured Vantor tasking endpoint URL."""
        if not self.tasking_base_url:
            return ''
        create_path = self._normalize_path(self.tasking_create_path, '/tasking/v2/requests')
        return f"{self.tasking_base_url.rstrip('/')}{create_path}"

    def create_tasking_request(
        self,
        request: Dict[str, Any],
        timeout: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Submit a Vantor tasking request to a configured tasking endpoint."""
        if not self.tasking_base_url:
            logger.warning('Vantor tasking base URL not configured')
            return None

        create_path = self._normalize_path(self.tasking_create_path, '/tasking/v2/requests')
        url = f"{self.tasking_base_url.rstrip('/')}{create_path}"
        req_timeout = int(timeout or self.tasking_timeout or TASKING_TIMEOUT_DEFAULT)
        payload = request if isinstance(request, dict) else {}

        headers = self._tasking_headers()
        body = json.dumps(payload, separators=(',', ':'))
        if not QGIS_AVAILABLE:
            return None
        try:
            nam = QgsNetworkAccessManager.instance()
            req = QNetworkRequest(QUrl(url))
            for key, value in headers.items():
                req.setRawHeader(str(key).encode('utf-8'), str(value).encode('utf-8'))
            reply = nam.post(req, body.encode('utf-8'))
            loop = QEventLoop()
            reply.finished.connect(loop.quit)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(req_timeout * 1000)
            loop.exec_()
            if not reply.isFinished():
                reply.abort()
                logger.error('Vantor tasking request timeout')
                return None
            if reply.error():
                logger.error(f'Vantor tasking request failed: {reply.errorString()}')
                return None
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if status_code and int(status_code) >= 400:
                logger.error(f'Vantor tasking request HTTP {status_code}')
                return None
            response_text = reply.readAll().data().decode('utf-8', errors='ignore')
            if response_text.strip():
                return json.loads(response_text)
            return {'status': 'submitted'}
        except Exception as exc:
            logger.error(f'Vantor tasking request failed: {exc}')
            return None

    def list_tasking_requests(
        self,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """List tasking requests from configured Vantor tasking endpoint."""
        if not self.tasking_base_url:
            logger.warning('Vantor tasking base URL not configured')
            return None

        list_path = self._normalize_path(self.tasking_list_path, '/tasking/v2/requests')
        base = f"{self.tasking_base_url.rstrip('/')}{list_path}"
        query = urlencode(params or {}) if params else ''
        url = f"{base}?{query}" if query else base
        req_timeout = int(timeout or self.tasking_timeout or TASKING_TIMEOUT_DEFAULT)
        headers = self._tasking_headers()

        try:
            raw = self._fetch_url(url, timeout=req_timeout, headers=headers)
            return json.loads(raw) if raw.strip() else {}
        except Exception as exc:
            logger.error(f'Vantor list tasking requests failed: {exc}')
            return None
    
    def _fetch_url(
        self,
        url: str,
        timeout: int = 120,
        headers: Optional[Dict[str, str]] = None,
    ) -> str:
        """Fetch URL using QGIS network manager (proxy-aware)
        
        Based on kadas-vantor-plugin DataFetchWorker pattern.
        
        Args:
            url: URL to fetch
            timeout: Timeout in seconds
            
        Returns:
            str: Response content
            
        Raises:
            Exception: On network error or timeout
        """
        if not QGIS_AVAILABLE:
            logger.error("QGIS not available - cannot fetch data")
            raise Exception("QGIS libraries not available")
        
        logger.debug(f"Fetching URL: {url} (timeout: {timeout}s)")
        
        # Validate URL
        if not url or not isinstance(url, str):
            raise Exception(f"Invalid URL: {url}")
        
        if not url.startswith(('http://', 'https://')):
            raise Exception(f"Invalid URL protocol: {url}")
        
        # Create network request
        nam = QgsNetworkAccessManager.instance()
        req = QNetworkRequest(QUrl(url))
        
        # Headers for compatibility
        req.setRawHeader(b"User-Agent", b"KADAS-Altair-Plugin/1.0")
        if headers:
            for key, value in headers.items():
                if value is None:
                    continue
                req.setRawHeader(str(key).encode('utf-8'), str(value).encode('utf-8'))
        req.setAttribute(QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.AlwaysNetwork)
        
        # Send request
        reply = nam.get(req)
        loop = QEventLoop()
        reply.finished.connect(loop.quit)
        
        # Timeout timer
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(timeout * 1000)
        
        # Wait for response
        loop.exec_()
        
        # Check timeout
        if not reply.isFinished():
            reply.abort()
            error_msg = f"Request timeout after {timeout} seconds for {url}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        # Check network error
        if reply.error():
            error_code = reply.error()
            error_msg = reply.errorString()
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            
            detailed_error = f"Network error ({error_code}): {error_msg}"
            if status_code:
                detailed_error += f" - HTTP {status_code}"

            if status_code in (401, 403):
                logger.info(
                    "Vantor discovery endpoint requires authentication or is blocked: %s",
                    detailed_error,
                )
            else:
                logger.error(f"{detailed_error} for URL: {url}")
            raise Exception(detailed_error)
        
        # Check HTTP status code
        status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        logger.debug(f"HTTP status code: {status_code}")
        
        if status_code and status_code >= 400:
            error_msg = f"HTTP error {status_code} from {url}"
            if status_code in (401, 403):
                logger.info("Vantor endpoint requires authentication or is blocked: %s", error_msg)
            else:
                logger.error(error_msg)
            raise Exception(error_msg)
        
        # Read data
        data = reply.readAll().data().decode('utf-8')
        logger.info(f"Successfully fetched {len(data)} bytes from {url} (HTTP {status_code})")
        
        return data

    @staticmethod
    def _normalize_iso_datetime(value: str, end_of_day: bool = False) -> str:
        """Normalize YYYY-MM-DD to RFC3339 datetime used by Discovery API."""
        text = str(value or "").strip()
        if not text:
            return ""
        if 'T' in text:
            return text
        return f"{text}T23:59:59Z" if end_of_day else f"{text}T00:00:00Z"

    @staticmethod
    def _extract_discovery_next_token(payload: Dict[str, Any]) -> Optional[str]:
        """Extract next-page token from Discovery links as `page=<n>`."""
        links = payload.get('links', []) if isinstance(payload, dict) else []
        if not isinstance(links, list):
            return None
        for link in links:
            if not isinstance(link, dict):
                continue
            if str(link.get('rel', '')).lower() != 'next':
                continue
            href = str(link.get('href', '')).strip()
            if not href:
                continue
            parsed = urlparse(href)
            query = parse_qs(parsed.query)
            page_vals = query.get('page') or query.get('next')
            if page_vals:
                page_val = str(page_vals[0]).strip()
                if page_val:
                    return f"page={page_val}"
        return None

    def _search_discovery_api(
        self,
        bbox: Optional[List[float]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_cloud_cover: Optional[float] = None,
        collection: Optional[str] = None,
        text_query: Optional[str] = None,
        limit: int = 100,
        timeout: Optional[int] = None,
        page: Optional[int] = None,
        sortby: Optional[str] = None,
        intersects: Optional[Dict[str, Any]] = None,
        filter_expr: Optional[str] = None,
        area_based_calc: Optional[bool] = None,
        discovery_collections: Optional[List[str]] = None,
        discovery_search_path: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Search Vantor archive through Discovery API.

        Uses the imagery sub-catalog endpoint described in Maxar Discovery docs.
        """
        base_url = (self.discovery_base_url or DISCOVERY_BASE_URL).rstrip('/')
        path = (
            discovery_search_path
            or self.discovery_search_path
            or DISCOVERY_IMAGERY_SEARCH_PATH
        )
        path = str(path).strip()
        if not path.startswith('/'):
            path = '/' + path
        endpoint = f"{base_url}{path}"

        params: Dict[str, str] = {}
        if bbox and len(bbox) == 4:
            params['bbox'] = ','.join(str(v) for v in bbox)

        if start_date or end_date:
            start = self._normalize_iso_datetime(start_date or "") or ".."
            end = self._normalize_iso_datetime(end_date or "", end_of_day=True) or ".."
            params['datetime'] = f"{start}/{end}"

        collection_values: List[str] = []
        if discovery_collections:
            collection_values.extend(
                str(v).strip() for v in discovery_collections if str(v).strip()
            )
        if collection:
            collection_values.extend(
                [part.strip() for part in str(collection).split(',') if part.strip()]
            )
        if not collection_values and path == DISCOVERY_ROOT_SEARCH_PATH:
            collection_values = DISCOVERY_IMAGERY_COLLECTIONS.copy()
        if collection_values:
            params['collections'] = ','.join(collection_values)

        try:
            safe_limit = max(1, int(limit))
        except Exception:
            safe_limit = 100
        params['limit'] = str(safe_limit)

        if page is not None:
            try:
                params['page'] = str(max(1, int(page)))
            except Exception:
                pass

        if sortby:
            params['sortby'] = str(sortby)

        if area_based_calc is not None:
            params['area-based-calc'] = 'true' if bool(area_based_calc) else 'false'

        filter_terms: List[str] = []
        if filter_expr:
            filter_terms.append(str(filter_expr).strip())

        if max_cloud_cover is not None:
            try:
                cloud_limit = float(max_cloud_cover)
                # Archive UI often passes 0..1, while metadata is commonly 0..100.
                if 0.0 <= cloud_limit <= 1.0:
                    cloud_limit *= 100.0
                filter_terms.append(f"eo:cloud_cover <= {cloud_limit:g}")
            except Exception:
                pass

        if text_query:
            q_escaped = text_query.replace("'", "''")
            filter_terms.append(
                "(id ILIKE '%{q}%' OR title ILIKE '%{q}%' OR description ILIKE '%{q}%')".format(
                    q=q_escaped
                )
            )

        if filter_terms:
            params['filter'] = ' AND '.join(filter_terms)

        if intersects and isinstance(intersects, dict):
            # Discovery supports intersects in GET as JSON-encoded geometry.
            params['intersects'] = json.dumps(intersects, separators=(',', ':'))

        query = urlencode(params)
        url = f"{endpoint}?{query}" if query else endpoint
        req_timeout = int(timeout or self.discovery_timeout or DISCOVERY_TIMEOUT_DEFAULT)
        headers = self._discovery_headers()

        logger.info(f"Vantor Discovery search: {url}")
        raw = self._fetch_url(url, timeout=req_timeout, headers=headers)
        payload = json.loads(raw)

        if not isinstance(payload, dict):
            raise Exception("Discovery API response is not a JSON object")

        features = payload.get('features', [])
        if not isinstance(features, list):
            raise Exception("Discovery API response missing 'features' array")

        next_token = self._extract_discovery_next_token(payload)

        results: List[Dict[str, Any]] = []
        for idx, feature in enumerate(features):
            if not isinstance(feature, dict):
                continue

            props = feature.get('properties', {}) or {}
            raw_id = feature.get('id') or props.get('id') or props.get('catalog_id')
            item_id = str(raw_id).strip() if raw_id is not None else ''
            if not item_id:
                item_id = f"discovery-item-{idx}"

            collection_id = str(
                feature.get('collection')
                or props.get('collection')
                or collection
                or 'imagery'
            )

            item = {
                'id': item_id,
                'type': feature.get('type', 'Feature'),
                'geometry': feature.get('geometry'),
                'bbox': feature.get('bbox'),
                'properties': props,
                'assets': self._extract_assets(props, feature),
                'collection': collection_id,
                'event_id': collection_id,
            }
            results.append(item)

        logger.info(
            f"Vantor Discovery search returned {len(results)} item(s), "
            f"next_token={next_token}"
        )
        return results, next_token
    
    def load_events(self) -> List[Tuple[str, int]]:
        """Load available events from GitHub datasets.csv
        
        Based on kadas-vantor-plugin pattern.
        
        Returns:
            List[Tuple[str, int]]: List of (event_name, tile_count)
        """
        logger.info("Loading Vantor events from GitHub + STAC catalogs")

        github_events: List[Tuple[str, int]] = []
        github_sources: Dict[str, Dict[str, str]] = {}
        stac_events: List[Tuple[str, int]] = []
        stac_sources: Dict[str, Dict[str, str]] = {}

        # 1) GitHub dataset (legacy Maxar open-data source)
        try:
            github_events, github_sources = self._load_events_from_github_csv()
            logger.info(f"Loaded {len(github_events)} event(s) from GitHub dataset")
        except Exception as e:
            logger.warning(f"GitHub event loading failed: {e}")

        # 2) STAC catalogs (primary includes new vantor-opendata bucket)
        try:
            stac_events, stac_sources = self._load_events_from_stac_catalogs()
            logger.info(f"Loaded {len(stac_events)} event(s) from STAC catalogs")
        except Exception as e:
            logger.warning(f"STAC event loading failed: {e}")

        # 3) Merge both sources; prefer STAC refs so footprint loading can use
        # direct STAC item/assets endpoints (Vantor and Maxar catalogs).
        event_counts: Dict[str, int] = {name: count for name, count in github_events}
        merged_sources: Dict[str, Dict[str, str]] = dict(github_sources)

        for event_name, _ in stac_events:
            source = stac_sources.get(event_name)
            if not source:
                continue
            source_ref = str(source.get('ref', ''))
            source_is_new_bucket = (
                'vantor-opendata.s3.amazonaws.com' in source_ref
            )

            if event_name not in event_counts:
                event_counts[event_name] = 0

            existing = merged_sources.get(event_name)
            existing_ref = str((existing or {}).get('ref', ''))
            existing_mode = str((existing or {}).get('mode', '')).lower()
            prefer_new_bucket = source_is_new_bucket
            existing_is_new_bucket = 'vantor-opendata.s3.amazonaws.com' in existing_ref
            if existing is None:
                merged_sources[event_name] = source
            elif prefer_new_bucket:
                merged_sources[event_name] = source
            elif existing_mode == 'stac' and not existing_is_new_bucket:
                merged_sources[event_name] = source

        if not event_counts:
            raise Exception("No events available from either GitHub or STAC sources")

        merged_events = sorted(event_counts.items(), key=lambda x: x[0].lower())
        self.events = merged_events
        self.event_sources = merged_sources
        logger.info(
            f"Loaded {len(merged_events)} total event(s) "
            f"(GitHub={len(github_events)}, STAC={len(stac_events)})"
        )
        return merged_events

    def _load_events_from_github_csv(self) -> Tuple[List[Tuple[str, int]], Dict[str, Dict[str, str]]]:
        """Load events from legacy GitHub datasets.csv source."""
        logger.info(f"Loading events from: {DATASETS_CSV_URL}")
        csv_data = self._fetch_url(DATASETS_CSV_URL, timeout=TIMEOUT_EVENTS)

        logger.debug(f"Fetched CSV data: {len(csv_data)} bytes")
        if csv_data:
            logger.debug(f"CSV preview: {csv_data[:200]}")
        else:
            logger.error("CSV data is empty")
            return [], {}

        events: List[Tuple[str, int]] = []
        event_sources: Dict[str, Dict[str, str]] = {}
        lines = csv_data.strip().split("\n")
        logger.debug(f"CSV has {len(lines)} lines (including header)")

        # Skip header (first line)
        for i, line in enumerate(lines[1:], start=1):
            line = line.strip()
            if not line:
                continue

            parts = line.split(",")
            if len(parts) < 2:
                continue

            event_name = parts[0].strip()
            tile_count_str = parts[1].strip()

            if i <= 3:
                logger.debug(f"Row {i}: name='{event_name}', count='{tile_count_str}'")

            if not event_name:
                continue

            try:
                tile_count_int = int(tile_count_str)
            except ValueError:
                logger.warning(f"Invalid tile count for {event_name}: {tile_count_str}")
                tile_count_int = 0

            events.append((event_name, tile_count_int))
            event_sources[event_name] = {'mode': 'github', 'ref': event_name}

        logger.info(
            f"Parsed {len(lines)-1} CSV rows (excluding header), "
            f"extracted {len(events)} valid events"
        )
        events.sort(key=lambda x: x[0].lower())
        return events, event_sources

    def _load_events_from_stac_catalogs(self) -> Tuple[List[Tuple[str, int]], Dict[str, Dict[str, str]]]:
        """Load events from Vantor Open Data STAC catalog as fallback.

        Returns:
            List[Tuple[str, int]]: List of (event_name, tile_count). tile_count
            is 0 when not available in catalog metadata.
        """
        aggregated_events: Dict[str, int] = {}
        aggregated_sources: Dict[str, Dict[str, str]] = {}
        last_error = None
        successful_catalogs = 0

        for catalog_url in STAC_CATALOG_URLS:
            try:
                logger.info(f"Loading STAC events from: {catalog_url}")
                catalog_str = self._fetch_url(catalog_url, timeout=TIMEOUT_EVENTS)
                catalog = json.loads(catalog_str)

                links = catalog.get('links', []) if isinstance(catalog, dict) else []
                local_events = 0

                for link in links:
                    if not isinstance(link, dict):
                        continue
                    if link.get('rel') != 'child':
                        continue

                    href = link.get('href')
                    if not href:
                        continue

                    if not href.startswith(('http://', 'https://')):
                        href = urljoin(catalog_url, href)

                    title = str(link.get('title') or '').strip()
                    event_name = title if title else _event_name_from_collection_href(href)

                    # Last fallback: keep non-empty basename from href
                    if not event_name:
                        stripped = href.rstrip('/')
                        event_name = stripped.split('/')[-1] if '/' in stripped else href
                    event_name = str(event_name).strip()
                    if not event_name:
                        continue

                    if event_name.lower().endswith('collection.json'):
                        # Defensive skip when href parsing failed.
                        continue

                    local_events += 1
                    aggregated_events.setdefault(event_name, 0)

                    existing = aggregated_sources.get(event_name)
                    prefer_new_bucket = 'vantor-opendata.s3.amazonaws.com' in href
                    existing_ref = str((existing or {}).get('ref', ''))
                    existing_is_new_bucket = 'vantor-opendata.s3.amazonaws.com' in existing_ref
                    if existing is None or prefer_new_bucket or not existing_is_new_bucket:
                        aggregated_sources[event_name] = {'mode': 'stac', 'ref': href}

                if local_events == 0:
                    raise Exception("STAC catalog returned no child events")

                successful_catalogs += 1
                logger.info(f"Loaded {local_events} STAC event(s) from {catalog_url}")

            except Exception as e:
                last_error = e
                logger.warning(f"STAC fallback URL failed ({catalog_url}): {e}")

        if successful_catalogs == 0 or not aggregated_events:
            raise Exception(f"All STAC fallback URLs failed: {last_error}")

        events = sorted(aggregated_events.items(), key=lambda x: x[0].lower())
        return events, aggregated_sources
    
    def get_collections(self) -> List[Dict[str, Any]]:
        """Get available collections (events)
        
        Returns:
            List[Dict[str, Any]]: List of collection dictionaries
        """
        if not self.events:
            self.load_events()
        
        collections = []
        for event_name, tile_count in self.events:
            collections.append({
                'id': event_name,
                'title': event_name,
                'description': f'Vantor Open Data - {tile_count} tiles',
                'asset_count': tile_count,
                'type': 'Collection'
            })
        
        return collections
    
    def load_footprints(self, event_name: str) -> Dict[str, Any]:
        """Load footprints for a specific event
        
        Based on kadas-vantor-plugin pattern with GeoJSON from GitHub.
        
        Args:
            event_name: Name of the event
            
        Returns:
            Dict[str, Any]: GeoJSON FeatureCollection
        """
        # Check cache
        if event_name in self.footprints_cache:
            logger.debug(f"Using cached footprints for {event_name}")
            return self.footprints_cache[event_name]
        
        source_info = self.event_sources.get(event_name, {'mode': 'github', 'ref': event_name})
        mode = source_info.get('mode', 'github')
        ref = source_info.get('ref', event_name)

        try:
            if mode == 'stac':
                geojson = self._load_footprints_from_stac_collection(ref)
            else:
                # Default GitHub mode
                url = GEOJSON_URL_TEMPLATE.format(event=event_name)
                logger.info(f"Loading footprints from: {url}")
                geojson_data = self._fetch_url(url, timeout=TIMEOUT_FOOTPRINTS)
                geojson = json.loads(geojson_data)

                # Validate structure
                if not isinstance(geojson, dict):
                    raise Exception("Invalid GeoJSON: not a dictionary")
                if 'features' not in geojson:
                    raise Exception("Invalid GeoJSON: missing 'features' key")

            features = geojson.get('features', [])
            logger.info(f"Loaded {len(features)} footprints for {event_name} (source: {mode})")

            # Cache result
            self.footprints_cache[event_name] = geojson
            self.current_event = event_name

            return geojson

        except Exception as e:
            logger.error(f"Failed to load footprints for {event_name}: {e}", exc_info=True)
            raise

    def _load_footprints_from_stac_collection(self, collection_href: str) -> Dict[str, Any]:
        """Load item footprints from a STAC collection href.

        Follows the qgis-vantor-plugin reference pattern:
        - Fetches the collection JSON
        - Iterates links with rel=="item" and fetches each STAC item JSON
        - Builds a GeoJSON-like FeatureCollection from the individual item dicts

        Falls back to the /items endpoint when no item links are found
        (e.g. older static STAC catalogs).

        Args:
            collection_href: Absolute URL to STAC collection JSON

        Returns:
            Dict[str, Any]: GeoJSON-like FeatureCollection of STAC items
        """
        logger.info(f"Loading STAC collection from: {collection_href}")
        collection_str = self._fetch_url(collection_href, timeout=TIMEOUT_EVENTS)
        collection_obj = json.loads(collection_str)

        if not isinstance(collection_obj, dict):
            raise Exception("Invalid STAC collection response")

        # --- Strategy 1: individual item links (qgis-vantor-plugin pattern) ---
        item_links = [
            link for link in collection_obj.get('links', [])
            if isinstance(link, dict) and link.get('rel') == 'item' and link.get('href')
        ]

        if item_links:
            logger.info(f"Found {len(item_links)} item link(s) in collection, fetching individually")
            features: List[Dict[str, Any]] = []
            seen_ids: set = set()

            for link in item_links:
                href = link['href']
                if not href.startswith(('http://', 'https://')):
                    href = urljoin(collection_href, href)
                try:
                    item_str = self._fetch_url(href, timeout=TIMEOUT_EVENTS)
                    item = json.loads(item_str)
                    item_id = item.get('id', '')
                    if item_id not in seen_ids:
                        seen_ids.add(item_id)
                        features.append(item)
                except Exception as e:
                    logger.warning(f"Skipping item {href}: {e}")
                    continue

            logger.info(f"Fetched {len(features)} STAC item(s) individually")
            return {'type': 'FeatureCollection', 'features': features}

        # --- Strategy 2: /items GeoJSON endpoint (older static STAC collections) ---
        items_href = None
        for link in collection_obj.get('links', []):
            if not isinstance(link, dict):
                continue
            if link.get('rel') == 'items' and link.get('href'):
                items_href = link.get('href')
                break

        if not items_href:
            parsed = urlparse(collection_href)
            path = parsed.path.rstrip('/')
            lower_path = path.lower()

            if lower_path.endswith('/collection.json'):
                base_path = path[:-len('/collection.json')]
            elif lower_path.endswith('.json'):
                # Generic fallback for collection-like JSON URLs.
                base_path = path.rsplit('/', 1)[0] if '/' in path else path
            else:
                base_path = path

            base_path = base_path.rstrip('/')
            items_href = f"{parsed.scheme}://{parsed.netloc}{base_path}/items"

        if not items_href.startswith(('http://', 'https://')):
            items_href = urljoin(collection_href, items_href)

        logger.info(f"Loading STAC items endpoint: {items_href}")
        items_str = self._fetch_url(items_href, timeout=TIMEOUT_FOOTPRINTS)
        items_obj = json.loads(items_str)

        if not isinstance(items_obj, dict):
            raise Exception("Invalid STAC items response")
        if 'features' not in items_obj:
            raise Exception("STAC items response missing 'features'")

        return items_obj
    
    def search(
        self,
        bbox: Optional[List[float]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_cloud_cover: Optional[float] = None,
        collection: Optional[str] = None,
        text_query: Optional[str] = None,
        use_discovery_api: Optional[bool] = None,
        discovery_page: Optional[int] = None,
        discovery_sortby: Optional[str] = None,
        discovery_filter: Optional[str] = None,
        discovery_intersects: Optional[Dict[str, Any]] = None,
        discovery_area_based_calc: Optional[bool] = None,
        discovery_collections: Optional[List[str]] = None,
        discovery_search_path: Optional[str] = None,
        timeout: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Search for imagery
        
        Args:
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            start_date: Start date (ISO 8601)
            end_date: End date (ISO 8601)
            max_cloud_cover: Maximum cloud cover percentage (0-100)
            collection: Collection/event name to search; if None, searches all
                        events (cached first, then up to MAX_EVENTS_TO_FETCH
                        additional ones fetched from GitHub/STAC).
            text_query: Optional free text query (Discovery API only)
            use_discovery_api: Force Discovery API usage on/off; if None, uses
                connector setting (enabled by default)
            timeout: Optional request timeout in seconds
            limit: Maximum number of results
            
        Returns:
            List[Dict[str, Any]]: List of STAC-like items
        """
        discovery_active = (
            self.discovery_enabled if use_discovery_api is None else bool(use_discovery_api)
        )

        # First try Discovery API for archive-style searches.
        if discovery_active:
            try:
                discovery_items, discovery_next = self._search_discovery_api(
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=max_cloud_cover,
                    collection=collection,
                    text_query=text_query,
                    limit=limit,
                    timeout=timeout,
                    page=discovery_page,
                    sortby=discovery_sortby,
                    intersects=discovery_intersects,
                    filter_expr=discovery_filter,
                    area_based_calc=discovery_area_based_calc,
                    discovery_collections=discovery_collections,
                    discovery_search_path=discovery_search_path,
                )
                self._last_search_next_token = discovery_next
                return self._filter_search_results(
                    discovery_items,
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=max_cloud_cover,
                    text_query=text_query,
                    limit=limit,
                )
            except Exception as e:
                logger.info(
                    "Vantor Discovery search unavailable, falling back to open-data "
                    f"catalog search: {e}"
                )

        # Maximum events to download when collection is not specified
        MAX_EVENTS_TO_FETCH = 10
        MAX_EVENTS_TO_FETCH_FALLBACK = 50

        logger.info(f"Vantor.search() called: collection={collection}, bbox={bbox}, "
                   f"dates={start_date} to {end_date}, cloud<={max_cloud_cover}, limit={limit}, "
                   f"discovery={discovery_active}")

        # Ensure event list is available
        if not self.events:
            try:
                self.load_events()
            except Exception as e:
                logger.error(f"Vantor: failed to load event list: {e}")
                return []

        # Build the list of event names to search
        if collection:
            events_to_search = [collection]
        else:
            # Cached events first (already in memory — free), then STAC-backed
            # events from the Vantor bucket, then remaining GitHub events.
            cached = list(self.footprints_cache.keys())
            remaining = [ev for ev, _ in self.events if ev not in self.footprints_cache]

            stac_first = [
                ev for ev in remaining
                if str(self.event_sources.get(ev, {}).get('mode', '')) == 'stac'
            ]
            github_rest = [ev for ev in remaining if ev not in stac_first]
            events_to_search = cached + stac_first + github_rest

        results: List[Dict[str, Any]] = []
        events_fetched = 0

        for event_name in events_to_search:
            if len(results) >= limit:
                break

            in_cache = event_name in self.footprints_cache
            # Limit network fetches when doing a broad search
            if not in_cache and collection is None:
                if events_fetched >= MAX_EVENTS_TO_FETCH:
                    logger.debug(
                        f"Vantor: reached MAX_EVENTS_TO_FETCH ({MAX_EVENTS_TO_FETCH}), "
                        "stopping broad event scan"
                    )
                    break
                events_fetched += 1

            try:
                geojson = self.load_footprints(event_name)
            except Exception as e:
                logger.warning(f"Vantor: skipping event {event_name!r}: {e}")
                continue

            features = geojson.get('features', [])
            for feature_idx, feature in enumerate(features):
                if len(results) >= limit:
                    break

                props = feature.get('properties', {})

                raw_id = feature.get('id')
                if raw_id is None or str(raw_id).strip() == '':
                    raw_id = props.get('id') or props.get('catalog_id') or props.get('datetime')
                item_id = str(raw_id).strip() if raw_id is not None else ''
                if not item_id:
                    item_id = f"{event_name}-{feature_idx}"

                item = {
                    'id': item_id,
                    'type': 'Feature',
                    'geometry': feature.get('geometry'),
                    'bbox': feature.get('bbox'),
                    'properties': props,
                    'assets': self._extract_assets(props, feature),
                    'collection': event_name,
                    'event_id': event_name,
                }
                if not self._item_matches_filters(
                    item,
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=max_cloud_cover,
                    text_query=text_query,
                ):
                    continue
                results.append(item)

        if (
            collection is None
            and not results
            and events_fetched >= MAX_EVENTS_TO_FETCH
            and len(events_to_search) > events_fetched
        ):
            logger.info(
                "Vantor: zero results after initial capped scan; retrying with "
                f"expanded cap ({MAX_EVENTS_TO_FETCH_FALLBACK})"
            )
            for event_name in events_to_search:
                if len(results) >= limit:
                    break
                if event_name in self.footprints_cache:
                    continue
                if events_fetched >= MAX_EVENTS_TO_FETCH_FALLBACK:
                    break

                events_fetched += 1
                try:
                    geojson = self.load_footprints(event_name)
                except Exception as e:
                    logger.warning(f"Vantor: skipping event {event_name!r}: {e}")
                    continue

                features = geojson.get('features', [])
                for feature_idx, feature in enumerate(features):
                    if len(results) >= limit:
                        break

                    props = feature.get('properties', {})

                    raw_id = feature.get('id')
                    if raw_id is None or str(raw_id).strip() == '':
                        raw_id = props.get('id') or props.get('catalog_id') or props.get('datetime')
                    item_id = str(raw_id).strip() if raw_id is not None else ''
                    if not item_id:
                        item_id = f"{event_name}-{feature_idx}"

                    item = {
                        'id': item_id,
                        'type': 'Feature',
                        'geometry': feature.get('geometry'),
                        'bbox': feature.get('bbox'),
                        'properties': props,
                        'assets': self._extract_assets(props, feature),
                        'collection': event_name,
                        'event_id': event_name,
                    }
                    if not self._item_matches_filters(
                        item,
                        bbox=bbox,
                        start_date=start_date,
                        end_date=end_date,
                        max_cloud_cover=max_cloud_cover,
                        text_query=text_query,
                    ):
                        continue
                    results.append(item)

        logger.info(
            f"Vantor search: {len(results)} result(s) "
            f"(events searched: {len(events_to_search)}, "
            f"fetched from network: {events_fetched})"
        )
        self._last_search_next_token = None
        return results

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
        use_discovery_api: Optional[bool] = None,
        vantor_use_discovery_api: Optional[bool] = None,
        discovery_page: Optional[int] = None,
        discovery_sortby: Optional[str] = None,
        discovery_filter: Optional[str] = None,
        discovery_area_based_calc: Optional[bool] = None,
        discovery_collections: Optional[List[str]] = None,
        discovery_search_path: Optional[str] = None,
        page: Optional[int] = None,
        sortby: Optional[str] = None,
        filter: Optional[str] = None,
        area_based_calc: Optional[bool] = None,
        intersects: Optional[Dict[str, Any]] = None,
        discovery_intersects: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> tuple:
        """Unified search entrypoint with Discovery API support.

        Optional extra filters accepted from ConnectorManager:
        - use_discovery_api
        - vantor_use_discovery_api
        """
        if use_discovery_api is None:
            use_discovery_api = vantor_use_discovery_api

        result = self.search(
            bbox=bbox,
            start_date=start_date or "",
            end_date=end_date or "",
            max_cloud_cover=max_cloud_cover,
            collection=collection,
            text_query=text_query,
            use_discovery_api=use_discovery_api,
            discovery_page=discovery_page if discovery_page is not None else page,
            discovery_sortby=discovery_sortby or sortby,
            discovery_filter=discovery_filter or filter,
            discovery_intersects=discovery_intersects or intersects,
            discovery_area_based_calc=(
                discovery_area_based_calc
                if discovery_area_based_calc is not None
                else area_based_calc
            ),
            discovery_collections=discovery_collections,
            discovery_search_path=discovery_search_path,
            timeout=int(timeout) if timeout else None,
            limit=limit,
        )
        if isinstance(result, tuple):
            return result
        return result, self._last_search_next_token
    
    def _get_item_bbox(self, item: Dict[str, Any]) -> Optional[List[float]]:
        """Return an item bbox from the item itself or from its geometry."""
        if not isinstance(item, dict):
            return None

        bbox = item.get('bbox')
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            try:
                return [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
            except (TypeError, ValueError):
                pass

        geometry = item.get('geometry')
        if not isinstance(geometry, dict):
            return None

        geom_type = str(geometry.get('type') or '').lower()
        coordinates = geometry.get('coordinates')
        if geom_type == 'point' and isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
            lon = float(coordinates[0])
            lat = float(coordinates[1])
            return [lon, lat, lon, lat]

        if geom_type == 'polygon' and isinstance(coordinates, (list, tuple)) and coordinates:
            rings = coordinates
            if isinstance(rings[0], (list, tuple)):
                coords = [point for ring in rings for point in ring if isinstance(point, (list, tuple)) and len(point) >= 2]
                if coords:
                    lons = [float(point[0]) for point in coords]
                    lats = [float(point[1]) for point in coords]
                    return [min(lons), min(lats), max(lons), max(lats)]

        if geom_type == 'multipolygon' and isinstance(coordinates, (list, tuple)) and coordinates:
            all_coords = []
            for polygon in coordinates:
                if isinstance(polygon, (list, tuple)):
                    for ring in polygon:
                        if isinstance(ring, (list, tuple)):
                            all_coords.extend(
                                point for point in ring if isinstance(point, (list, tuple)) and len(point) >= 2
                            )
            if all_coords:
                lons = [float(point[0]) for point in all_coords]
                lats = [float(point[1]) for point in all_coords]
                return [min(lons), min(lats), max(lons), max(lats)]

        return None

    def _item_matches_filters(
        self,
        item: Dict[str, Any],
        bbox: Optional[List[float]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_cloud_cover: Optional[float] = None,
        text_query: Optional[str] = None,
    ) -> bool:
        """Return True when an item matches the active search filters."""
        props = item.get('properties') if isinstance(item.get('properties'), dict) else {}

        if bbox is not None:
            item_bbox = self._get_item_bbox(item)
            if not item_bbox or not self._bbox_intersects(bbox, item_bbox):
                return False

        if max_cloud_cover is not None:
            cloud_cover = props.get('cloud_cover', props.get('eo:cloud_cover', 0))
            try:
                cloud_limit = float(max_cloud_cover)
                cloud_value = float(cloud_cover)

                # UI often sends 0..1 while open-data metadata commonly stores
                # cloud cover in 0..100.
                if 0.0 <= cloud_limit <= 1.0:
                    cloud_limit *= 100.0

                if cloud_value > cloud_limit:
                    return False
            except (TypeError, ValueError):
                pass

        if start_date or end_date:
            date_part = ''
            for field in (
                'datetime',
                'start_datetime',
                'end_datetime',
                'acquired',
                'acquisition_date',
                'date',
            ):
                raw_value = props.get(field)
                if raw_value is None:
                    continue
                text_value = str(raw_value).strip()
                if len(text_value) >= 10:
                    date_part = text_value[:10]
                    break

            if not date_part:
                return False

            start_day = str(start_date)[:10] if start_date else ''
            end_day = str(end_date)[:10] if end_date else ''
            # Safety-net: swap if range is inverted
            if start_day and end_day and start_day > end_day:
                start_day, end_day = end_day, start_day
            if start_day and date_part < start_day:
                return False
            if end_day and date_part > end_day:
                return False

        if text_query:
            query = str(text_query).strip().lower()
            if query:
                haystack = ' '.join(
                    str(value).lower()
                    for value in [
                        item.get('id', ''),
                        props.get('id', ''),
                        props.get('title', ''),
                        props.get('description', ''),
                        props.get('platform', ''),
                        props.get('satellite', ''),
                    ]
                    if value is not None
                )
                if query not in haystack:
                    return False

        return True

    def _filter_search_results(
        self,
        items: List[Dict[str, Any]],
        bbox: Optional[List[float]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_cloud_cover: Optional[float] = None,
        text_query: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Filter a list of Vantor results to the active search constraints."""
        filtered: List[Dict[str, Any]] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            if self._item_matches_filters(
                item,
                bbox=bbox,
                start_date=start_date,
                end_date=end_date,
                max_cloud_cover=max_cloud_cover,
                text_query=text_query,
            ):
                filtered.append(item)
                if limit is not None and len(filtered) >= int(limit):
                    break
        return filtered

    def _bbox_intersects(self, bbox1: List[float], bbox2: List[float]) -> bool:
        """Check if two bboxes intersect
        
        Args:
            bbox1: [min_lon, min_lat, max_lon, max_lat]
            bbox2: [min_lon, min_lat, max_lon, max_lat]
            
        Returns:
            bool: True if bboxes intersect
        """
        return not (bbox1[2] < bbox2[0] or  # bbox1 right < bbox2 left
                   bbox1[0] > bbox2[2] or  # bbox1 left > bbox2 right
                   bbox1[3] < bbox2[1] or  # bbox1 top < bbox2 bottom
                   bbox1[1] > bbox2[3])    # bbox1 bottom > bbox2 top
    
    def _extract_assets(self, props: Dict[str, Any], feature: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, str]]:
        """Extract assets from properties (and optionally from the feature-level assets dict).
        
        Based on kadas-vantor-plugin GeoJSON structure:
        - visual: RGB imagery URL
        - ms_analytic: Multispectral imagery URL
        - pan_analytic: Panchromatic imagery URL
        
        Args:
            props: Feature properties
            feature: Full feature dict (used as fallback for feature-level assets)
            
        Returns:
            Dict[str, Dict[str, str]]: Assets dictionary
        """
        assets = {}

        # Feature-level assets dict (native STAC items from vantor-opendata S3
        # and newer vantor GeoJSON schema both store URLs here)
        feature_assets: Dict[str, Any] = {}
        if isinstance(feature, dict):
            feature_assets = feature.get('assets', {}) or {}

        def _href(key: str) -> Optional[str]:
            """Resolve href: feature-level STAC assets → props fallback.

            Priority order matches qgis-vantor-plugin (stac_client.get_cog_url):
            native STAC assets take precedence over GeoJSON properties.
            """
            # 1. Standard STAC asset (vantor-opendata S3 items)
            a = feature_assets.get(key)
            if isinstance(a, dict):
                return a.get('href')
            if isinstance(a, str):
                return a
            # 2. GeoJSON property fallback (GitHub maxar-open-data format)
            url = props.get(key, '')
            if url:
                return url
            return None
        
        # Visual (RGB)
        visual_url = _href('visual')
        if visual_url:
            assets['visual'] = {
                'href': visual_url,
                'type': 'image/tiff; application=geotiff; profile=cloud-optimized',
                'roles': ['visual']
            }

        # Multispectral
        ms_url = _href('ms_analytic')
        if ms_url:
            assets['ms_analytic'] = {
                'href': ms_url,
                'type': 'image/tiff; application=geotiff; profile=cloud-optimized',
                'roles': ['data']
            }

        # Panchromatic
        pan_url = _href('pan_analytic')
        if pan_url:
            assets['pan_analytic'] = {
                'href': pan_url,
                'type': 'image/tiff; application=geotiff; profile=cloud-optimized',
                'roles': ['data']
            }

        # Thumbnail / quicklook (non-raster preview image)
        for thumb_key in ('thumbnail', 'overview', 'quicklook', 'preview'):
            thumb_val = feature_assets.get(thumb_key) or props.get(thumb_key) or props.get(f'{thumb_key}_url') or props.get(f'{thumb_key}_href')
            if thumb_val:
                href = thumb_val.get('href') if isinstance(thumb_val, dict) else str(thumb_val)
                if href and thumb_key not in assets:
                    assets[thumb_key] = {
                        'href': href,
                        'type': (thumb_val.get('type', 'image/jpeg') if isinstance(thumb_val, dict) else 'image/jpeg'),
                        'roles': ['thumbnail'],
                    }
                    break  # first match wins

        # Passthrough: include any additional raster assets from native STAC items
        # (e.g. 'pan', 'ms', 'rgb', 'data' — names used by vantor-opendata catalog)
        # that were not already captured by the three keys above
        _raster_mime = (
            'image/tiff', 'image/geotiff', 'image/jp2',
            'image/jpeg2000', 'application/jp2',
        )
        for asset_key, asset_val in feature_assets.items():
            if asset_key in assets:
                continue  # already captured
            if not isinstance(asset_val, dict):
                continue
            href = asset_val.get('href', '')
            if not href:
                continue
            mime = asset_val.get('type', '').lower()
            href_lower = href.lower()
            is_raster = (
                any(m in mime for m in _raster_mime)
                or href_lower.endswith(('.tif', '.tiff', '.cog', '.jp2', '.j2k'))
            )
            if is_raster:
                assets[asset_key] = asset_val
                logger.debug(f"Vantor: passthrough asset '{asset_key}' (type={mime or 'ext-based'})")

        return assets
    
    def get_cog_url(self, item: Dict[str, Any], asset_type: str = 'visual') -> Optional[str]:
        """Get COG URL from item
        
        Args:
            item: STAC item
            asset_type: Asset type ('visual', 'ms_analytic', 'pan_analytic')
            
        Returns:
            Optional[str]: COG URL or None
        """
        # Try assets first
        assets = item.get('assets', {})
        if asset_type in assets:
            return assets[asset_type].get('href')
        
        # Try properties (direct from GeoJSON)
        props = item.get('properties', {})
        return props.get(asset_type)
    
    def test_connection(self) -> bool:
        """Test connection to GitHub dataset
        
        Returns:
            bool: True if connection successful
        """
        try:
            logger.info("Testing Vantor connection...")
            events = self.load_events()
            logger.info(f"Connection test successful: {len(events)} events available")
            return True
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
