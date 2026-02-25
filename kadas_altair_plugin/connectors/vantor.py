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
            logger.info(f"Loaded {len(events)} events")
            
            return events
            
        except Exception as e:
            logger.error(f"Failed to load events: {e}", exc_info=True)
            raise
    
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
        
        # Construct URL
        url = GEOJSON_URL_TEMPLATE.format(event=event_name)
        logger.info(f"Loading footprints from: {url}")
        
        try:
            geojson_data = self._fetch_url(url, timeout=TIMEOUT_FOOTPRINTS)
            
            # Parse GeoJSON
            geojson = json.loads(geojson_data)
            
            # Validate structure
            if not isinstance(geojson, dict):
                raise Exception("Invalid GeoJSON: not a dictionary")
            
            if 'features' not in geojson:
                raise Exception("Invalid GeoJSON: missing 'features' key")
            
            features = geojson.get('features', [])
            logger.info(f"Loaded {len(features)} footprints for {event_name}")
            
            # Cache result
            self.footprints_cache[event_name] = geojson
            self.current_event = event_name
            
            return geojson
            
        except Exception as e:
            logger.error(f"Failed to load footprints for {event_name}: {e}", exc_info=True)
            raise
    
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
            collection: Collection/event name to search
            limit: Maximum number of results
            
        Returns:
            List[Dict[str, Any]]: List of STAC-like items
        """
        logger.info(f"Vantor.search() called: collection={collection}, bbox={bbox}, "
                   f"dates={start_date} to {end_date}, cloud<={max_cloud_cover}, limit={limit}")
        
        if not collection:
            logger.warning("No collection specified - returning empty results")
            return []
        
        # Load footprints for the event
        try:
            geojson = self.load_footprints(collection)
        except Exception as e:
            logger.error(f"Failed to load footprints: {e}")
            return []
        
        features = geojson.get('features', [])
        results = []
        
        for feature in features:
            # Apply filters
            props = feature.get('properties', {})
            
            # Cloud cover filter
            if max_cloud_cover is not None:
                cloud_cover = props.get('cloud_cover', 0)
                try:
                    cloud_val = float(cloud_cover)
                    if cloud_val > max_cloud_cover:
                        continue
                except (ValueError, TypeError):
                    pass
            
            # Date range filter
            datetime_str = props.get('datetime', '')
            if start_date or end_date:
                if datetime_str:
                    date_part = datetime_str[:10]  # Extract YYYY-MM-DD
                    
                    if start_date and date_part < start_date:
                        continue
                    
                    if end_date and date_part > end_date:
                        continue
            
            # Bbox filter (if feature has geometry)
            if bbox:
                geom = feature.get('geometry', {})
                if geom and geom.get('type') == 'Polygon':
                    coords = geom.get('coordinates', [])
                    if coords:
                        # Get feature bbox
                        lons = [pt[0] for pt in coords[0]]
                        lats = [pt[1] for pt in coords[0]]
                        feature_bbox = [min(lons), min(lats), max(lons), max(lats)]
                        
                        # Check intersection
                        if not self._bbox_intersects(bbox, feature_bbox):
                            continue
            
            # Convert to STAC-like format
            item = {
                'id': feature.get('id', ''),
                'type': 'Feature',
                'geometry': feature.get('geometry'),
                'properties': props,
                'assets': self._extract_assets(props),
                'collection': collection,
                'event_id': collection
            }
            
            results.append(item)
            
            # Respect limit
            if len(results) >= limit:
                break
        
        logger.info(f"Search returned {len(results)} results (filtered from {len(features)} features)")
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
    
    def _extract_assets(self, props: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
        """Extract assets from properties
        
        Based on kadas-vantor-plugin GeoJSON structure:
        - visual: RGB imagery URL
        - ms_analytic: Multispectral imagery URL
        - pan_analytic: Panchromatic imagery URL
        
        Args:
            props: Feature properties
            
        Returns:
            Dict[str, Dict[str, str]]: Assets dictionary
        """
        assets = {}
        
        # Visual (RGB)
        visual_url = props.get('visual', '')
        if visual_url:
            assets['visual'] = {
                'href': visual_url,
                'type': 'image/tiff; application=geotiff; profile=cloud-optimized',
                'roles': ['visual']
            }
        
        # Multispectral
        ms_url = props.get('ms_analytic', '')
        if ms_url:
            assets['ms_analytic'] = {
                'href': ms_url,
                'type': 'image/tiff; application=geotiff; profile=cloud-optimized',
                'roles': ['data']
            }
        
        # Panchromatic
        pan_url = props.get('pan_analytic', '')
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
