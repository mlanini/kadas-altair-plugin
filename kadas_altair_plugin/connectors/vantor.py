"""Vantor (Maxar Open Data) Connector

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
import csv
import json
from typing import List, Dict, Any, Optional, Tuple
from io import StringIO
from urllib.parse import urljoin

try:
    from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
    from qgis.PyQt.QtNetwork import QNetworkRequest
    from qgis.core import QgsNetworkAccessManager
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False

from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.vantor')


# GitHub URLs for Maxar Open Data (same pattern as kadas-vantor-plugin)
GITHUB_RAW_URL = "https://raw.githubusercontent.com/opengeos/maxar-open-data/master"
DATASETS_CSV_URL = f"{GITHUB_RAW_URL}/datasets.csv"
GEOJSON_URL_TEMPLATE = f"{GITHUB_RAW_URL}/datasets/{{event}}.geojson"

# STAC catalog fallback URLs (used in kadas-vantor-plugin and more robust
# than GitHub in restricted networks)
STAC_CATALOG_URLS = [
    "https://maxar-opendata.s3.dualstack.us-west-2.amazonaws.com/events/catalog.json",
    "https://maxar-opendata.s3.amazonaws.com/events/catalog.json",
]

# Timeouts (same as kadas-vantor-plugin)
TIMEOUT_EVENTS = 120  # seconds for datasets.csv
TIMEOUT_FOOTPRINTS = 180  # seconds for large GeoJSON files


class VantorConnector(ConnectorBase):
    """Vantor/Maxar Open Data connector using GitHub dataset
    
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
        self.authenticated = True  # No authentication required
        
    def authenticate(self, **kwargs) -> bool:
        """No authentication required for Vantor Open Data
        
        Loads available events from GitHub datasets.csv automatically.
        
        Returns:
            bool: Always True (public data)
        """
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
    
    def _fetch_url(self, url: str, timeout: int = 120) -> str:
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
            
            logger.error(f"{detailed_error} for URL: {url}")
            raise Exception(detailed_error)
        
        # Check HTTP status code
        status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        logger.debug(f"HTTP status code: {status_code}")
        
        if status_code and status_code >= 400:
            error_msg = f"HTTP error {status_code} from {url}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        # Read data
        data = reply.readAll().data().decode('utf-8')
        logger.info(f"Successfully fetched {len(data)} bytes from {url} (HTTP {status_code})")
        
        return data
    
    def load_events(self) -> List[Tuple[str, int]]:
        """Load available events from GitHub datasets.csv
        
        Based on kadas-vantor-plugin pattern.
        
        Returns:
            List[Tuple[str, int]]: List of (event_name, tile_count)
        """
        logger.info(f"Loading events from: {DATASETS_CSV_URL}")

        try:
            csv_data = self._fetch_url(DATASETS_CSV_URL, timeout=TIMEOUT_EVENTS)
            
            # Debug: Log CSV data length and first 200 chars
            logger.debug(f"Fetched CSV data: {len(csv_data)} bytes")
            if csv_data:
                logger.debug(f"CSV preview: {csv_data[:200]}")
            else:
                logger.error("CSV data is empty!")
                return []
            
            # Parse CSV manually (same as kadas-vantor-plugin for robustness)
            # Format: name,count
            # Example:
            # name,count
            # Afghanistan-earthquake-Jun22,345
            # American-Samoa-cyclone-Jan23,123
            events = []
            lines = csv_data.strip().split("\n")
            
            logger.debug(f"CSV has {len(lines)} lines (including header)")
            
            # Skip header (first line)
            for i, line in enumerate(lines[1:], start=1):
                line = line.strip()
                if not line:
                    continue  # Skip empty lines
                
                parts = line.split(",")
                if len(parts) >= 2:
                    event_name = parts[0].strip()
                    tile_count_str = parts[1].strip()
                    
                    # Debug: Log first 3 rows
                    if i <= 3:
                        logger.debug(f"Row {i}: name='{event_name}', count='{tile_count_str}'")
                    
                    if event_name:
                        try:
                            tile_count_int = int(tile_count_str)
                        except ValueError:
                            logger.warning(f"Invalid tile count for {event_name}: {tile_count_str}")
                            tile_count_int = 0
                        
                        events.append((event_name, tile_count_int))
            
            logger.info(f"Parsed {len(lines)-1} CSV rows (excluding header), extracted {len(events)} valid events")
            
            # Sort by event name
            events.sort(key=lambda x: x[0].lower())
            
            self.events = events
            self.event_sources = {
                event_name: {'mode': 'github', 'ref': event_name}
                for event_name, _ in events
            }
            logger.info(f"Loaded {len(events)} events")
            
            return events
            
        except Exception as e:
            logger.warning(f"GitHub event loading failed, trying STAC fallback: {e}")
            try:
                return self._load_events_from_stac()
            except Exception as stac_error:
                logger.error(f"Failed to load events from both GitHub and STAC fallback: {stac_error}", exc_info=True)
                raise

    def _load_events_from_stac(self) -> List[Tuple[str, int]]:
        """Load events from Maxar Open Data STAC catalog as fallback.

        Returns:
            List[Tuple[str, int]]: List of (event_name, tile_count). tile_count
            is 0 when not available in catalog metadata.
        """
        last_error = None

        for catalog_url in STAC_CATALOG_URLS:
            try:
                logger.info(f"Loading STAC events from: {catalog_url}")
                catalog_str = self._fetch_url(catalog_url, timeout=TIMEOUT_EVENTS)
                catalog = json.loads(catalog_str)

                links = catalog.get('links', []) if isinstance(catalog, dict) else []
                events: List[Tuple[str, int]] = []
                event_sources: Dict[str, Dict[str, str]] = {}

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

                    title = link.get('title')
                    if not title:
                        stripped = href.rstrip('/')
                        title = stripped.split('/')[-1] if '/' in stripped else href

                    event_name = str(title).strip()
                    if not event_name:
                        continue

                    if event_name in event_sources:
                        continue

                    events.append((event_name, 0))
                    event_sources[event_name] = {'mode': 'stac', 'ref': href}

                if not events:
                    raise Exception("STAC catalog returned no child events")

                events.sort(key=lambda x: x[0].lower())
                self.events = events
                self.event_sources = event_sources

                logger.info(f"Loaded {len(events)} events from STAC fallback")
                return events

            except Exception as e:
                last_error = e
                logger.warning(f"STAC fallback URL failed ({catalog_url}): {e}")

        raise Exception(f"All STAC fallback URLs failed: {last_error}")
    
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

        Args:
            collection_href: Absolute URL to STAC collection JSON

        Returns:
            Dict[str, Any]: GeoJSON-like FeatureCollection from STAC items endpoint
        """
        logger.info(f"Loading STAC collection metadata from: {collection_href}")
        collection_str = self._fetch_url(collection_href, timeout=TIMEOUT_EVENTS)
        collection_obj = json.loads(collection_str)

        if not isinstance(collection_obj, dict):
            raise Exception("Invalid STAC collection response")

        items_href = None
        for link in collection_obj.get('links', []):
            if not isinstance(link, dict):
                continue
            if link.get('rel') == 'items' and link.get('href'):
                items_href = link.get('href')
                break

        if not items_href:
            # Fallback commonly used by static STAC collections
            items_href = collection_href.rstrip('/') + '/items'

        if not items_href.startswith(('http://', 'https://')):
            items_href = urljoin(collection_href, items_href)

        logger.info(f"Loading STAC items from: {items_href}")
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
            limit: Maximum number of results
            
        Returns:
            List[Dict[str, Any]]: List of STAC-like items
        """
        # Maximum events to download when collection is not specified
        MAX_EVENTS_TO_FETCH = 10

        logger.info(f"Vantor.search() called: collection={collection}, bbox={bbox}, "
                   f"dates={start_date} to {end_date}, cloud<={max_cloud_cover}, limit={limit}")

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
            # Cached events first (already in memory — free), then remaining
            cached = list(self.footprints_cache.keys())
            remaining = [ev for ev, _ in self.events if ev not in self.footprints_cache]
            events_to_search = cached + remaining

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
            for feature in features:
                if len(results) >= limit:
                    break

                props = feature.get('properties', {})

                # Cloud cover filter
                if max_cloud_cover is not None:
                    cloud_cover = props.get('cloud_cover', props.get('eo:cloud_cover', 0))
                    try:
                        if float(cloud_cover) > max_cloud_cover:
                            continue
                    except (ValueError, TypeError):
                        pass

                # Date range filter
                datetime_str = props.get('datetime', '')
                if (start_date or end_date) and datetime_str:
                    date_part = datetime_str[:10]
                    if start_date and date_part < start_date:
                        continue
                    if end_date and date_part > end_date:
                        continue

                # Bbox intersection filter
                if bbox:
                    geom = feature.get('geometry', {})
                    if geom and geom.get('type') == 'Polygon':
                        coords = geom.get('coordinates', [])
                        if coords:
                            lons = [pt[0] for pt in coords[0]]
                            lats = [pt[1] for pt in coords[0]]
                            feature_bbox = [min(lons), min(lats), max(lons), max(lats)]
                            if not self._bbox_intersects(bbox, feature_bbox):
                                continue

                item = {
                    'id': feature.get('id', ''),
                    'type': 'Feature',
                    'geometry': feature.get('geometry'),
                    'bbox': feature.get('bbox'),
                    'properties': props,
                    'assets': self._extract_assets(props, feature),
                    'collection': event_name,
                    'event_id': event_name,
                }
                results.append(item)

        logger.info(
            f"Vantor search: {len(results)} result(s) "
            f"(events searched: {len(events_to_search)}, "
            f"fetched from network: {events_fetched})"
        )
        return results
    
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

        # Feature-level assets dict (newer Maxar GeoJSON schema)
        feature_assets: Dict[str, Any] = {}
        if isinstance(feature, dict):
            feature_assets = feature.get('assets', {}) or {}

        def _href(key: str) -> Optional[str]:
            """Resolve href: props → feature-level assets → None."""
            url = props.get(key, '')
            if url:
                return url
            a = feature_assets.get(key)
            if isinstance(a, dict):
                return a.get('href')
            if isinstance(a, str):
                return a
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
