"""
ICEYE Connector for KADAS Altair

Supports both:
- ICEYE commercial Catalog API (token-based archive search), and
- ICEYE Open Data STAC catalog (fallback mode).

Data Source: ICEYE Open Data Program on AWS
- Catalog: https://iceye-open-data-catalog.s3-us-west-2.amazonaws.com/catalog.json
- S3 Bucket: iceye-open-data-catalog (us-west-2, public access)
- STAC Browser: https://radiantearth.github.io/stac-browser/#/external/iceye-open-data-catalog.s3-us-west-2.amazonaws.com/catalog.json
- Documentation: https://sar.iceye.com/6.0.5/opendata/opendata/

Asset Types:
- SLC COG: Single Look Complex image (full phase/amplitude SAR data)
- GRD COG: Ground Range Detected image (processed, georeferenced)
- QLK COG: Quicklook preview image (visualization)
- CSI COG: Colorized Subaperture image (Dwell mode only)
- VID: SAR Video in COG/GIF/MP4 formats (Dwell mode only)
- Metadata JSON: STAC compliant product metadata

All products are Cloud-Optimized GeoTIFFs (COGs) that can be opened directly
over the network in QGIS and other GIS tools.

License: CC-BY 4.0 (Creative Commons Attribution)
Users are free to use, modify, and redistribute for academic, research, and
commercial purposes with attribution to ICEYE.

Catalog Structure:
The catalog contains 3 organizational views:
- ICEYE SAR - all
- ICEYE SAR - by mode (imaging modes)
- ICEYE SAR - by continent (geographic organization)

Each collection has direct item links (rel=item) rather than paginated search endpoints.
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urljoin, urlencode
from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.core import (
    QgsBlockingNetworkRequest,
    QgsNetworkAccessManager,
    QgsNetworkReplyContent
)
from qgis.PyQt.QtNetwork import QNetworkRequest

from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.iceye_stac')


DEFAULT_BASE = 'https://iceye-open-data-catalog.s3-us-west-2.amazonaws.com/catalog.json'
S3_BUCKET = 'iceye-open-data-catalog'
AWS_REGION = 'us-west-2'
DEFAULT_API_BASE = 'https://api.iceye.com'
CATALOG_ITEMS_PATH = '/api/catalog/v2/items'


class IceyeStacConnector(ConnectorBase):
    """
    ICEYE connector (Catalog API + Open Data STAC fallback)
    
    Connects to ICEYE's SAR open data catalog (CC-BY 4.0 licensed) and provides
    search/download capabilities for high-resolution SAR imagery.
    
    Features:
    - Catalog API authentication (Bearer token) for commercial archive
    - Open-data fallback for public AWS S3 bucket
    - Cloud-Optimized GeoTIFF (COG) support
    - Multiple asset types: SLC, GRD, QLK, CSI, VID
    - STAC-compliant metadata
    - Direct QGIS layer integration
    """
    
    # Asset type definitions
    ASSET_TYPES = {
        'slc': {
            'name': 'Single Look Complex (SLC)',
            'description': 'Full phase and amplitude SAR data',
            'format': 'COG',
            'typical_use': 'Advanced SAR processing, interferometry'
        },
        'grd': {
            'name': 'Ground Range Detected (GRD)',
            'description': 'Processed and georeferenced amplitude image',
            'format': 'COG',
            'typical_use': 'General purpose SAR imagery analysis'
        },
        'qlk': {
            'name': 'Quicklook (QLK)',
            'description': 'Preview/browse image',
            'format': 'COG/PNG',
            'typical_use': 'Quick visualization and browsing'
        },
        'csi': {
            'name': 'Colorized Subaperture Image (CSI)',
            'description': 'Colorized image from Dwell imaging mode',
            'format': 'COG',
            'typical_use': 'Dwell mode visualization'
        },
        'vid': {
            'name': 'SAR Video (VID)',
            'description': 'Video from Dwell imaging mode',
            'format': 'COG/GIF/MP4',
            'typical_use': 'Dwell mode dynamic visualization'
        }
    }
    
    # Imaging modes (from ICEYE documentation)
    IMAGING_MODES = [
        'STRIP', 'SPOT', 'SCAN', 'DWELL'
    ]

    def __init__(self, base_url: Optional[str] = None, capabilities: Optional[Dict[str, bool]] = None):
        """
        Initialize ICEYE STAC connector.
        
        Args:
            base_url: Base catalog URL (defaults to ICEYE public catalog)
            capabilities: Connector capabilities override
        """
        super().__init__()
        
        # Store capabilities
        self._capabilities = {
            'BBOX_SEARCH': True,
            'DATE_RANGE': True,
            'COLLECTIONS': True,
            'COG_SUPPORT': True,
            'CLOUD_COVER': False,  # SAR imagery doesn't have cloud cover
            'NO_AUTH': True,  # Public data, no authentication needed
            'DIRECT_COG_URL': True,  # COGs can be loaded directly from S3
        }
        if capabilities:
            self._capabilities.update(capabilities)
        
        self.base_url = base_url or DEFAULT_BASE
        self._catalog: Optional[Dict[str, Any]] = None
        self._allow_network = True
        self._api_base_url: Optional[str] = None
        self._api_access_token: Optional[str] = None
        self._api_contract_id: Optional[str] = None
        self._api_collections: Optional[List[str]] = None
        
        logger.info(f"IceyeStacConnector initialized")
        logger.debug(f"Catalog URL: {self.base_url}")
        logger.debug(f"S3 Bucket: {S3_BUCKET} (region: {AWS_REGION})")
        logger.info("License: CC-BY 4.0 - Free use with attribution to ICEYE")

    def authenticate(self, credentials: Optional[Dict] = None) -> bool:
        """
        Authenticate to ICEYE STAC (public catalog, no auth needed).
        
        Args:
            credentials: Not used (public catalog)
        
        Returns:
            bool: True if catalog accessible
        """
        # Commercial archive mode (ICEYE Catalog API)
        if credentials and credentials.get('access_token'):
            self._api_access_token = str(credentials.get('access_token')).strip()
            self._api_base_url = str(credentials.get('api_base_url') or DEFAULT_API_BASE).strip().rstrip('/')
            self._api_contract_id = str(credentials.get('contract_id') or '').strip() or None
            self._api_collections = self._normalize_collections(credentials.get('collections'))

            success = self._verify_catalog_api_access()
            if success:
                logger.info("✅ ICEYE Catalog API authentication successful")
            else:
                logger.error("❌ ICEYE Catalog API authentication failed")
            return success

        # Open-data fallback mode
        logger.info("Authenticating ICEYE STAC connector (verifying open-data catalog access)")
        success = self._fetch_catalog_if_needed()
        
        if success:
            logger.info("✅ ICEYE open-data catalog accessible")
        else:
            logger.error("❌ Failed to access ICEYE open-data catalog")
            
        return success

    def _catalog_items_url(self) -> str:
        base = (self._api_base_url or DEFAULT_API_BASE).rstrip('/')
        if base.endswith('/api/catalog/v2/items'):
            return base
        if base.endswith('/catalog/v2/items'):
            return base if '/api/' in base else f"{base}"
        if base.endswith('/api'):
            return f"{base}/catalog/v2/items"
        return f"{base}{CATALOG_ITEMS_PATH}"

    @staticmethod
    def _normalize_collections(value: Any) -> Optional[List[str]]:
        if value is None:
            return None
        if isinstance(value, list):
            out = [str(v).strip() for v in value if str(v).strip()]
            return out or None
        text = str(value).strip()
        if not text:
            return None
        parts = [p.strip() for p in text.split(',') if p.strip()]
        return parts or None

    def _verify_catalog_api_access(self) -> bool:
        if not self._api_access_token:
            logger.error("ICEYE Catalog API access token is missing")
            return False

        headers = {
            'Accept': 'application/json, application/problem+json',
            'Authorization': f'Bearer {self._api_access_token}',
        }
        payload = self._http_get_json(
            self._catalog_items_url(),
            timeout=15,
            headers=headers,
            params={'limit': '1'},
        )
        return isinstance(payload, dict)

    def _fetch_catalog_if_needed(self) -> bool:
        """Fetch catalog if not already cached."""
        if self._catalog is not None:
            return True
        
        if not self._allow_network:
            logger.warning("Network requests disabled")
            return False

        try:
            logger.info(f"Fetching ICEYE catalog from {self.base_url}")
            data = self._http_get(self.base_url, timeout=15)
            
            if not data:
                logger.error("Failed to fetch catalog (empty response)")
                return False
            
            if not isinstance(data, dict):
                logger.error(f"Invalid catalog format (not a dict): {type(data)}")
                return False
            
            self._catalog = data
            logger.info("✅ ICEYE catalog fetched successfully")
            return True
            
        except Exception as e:
            logger.exception(f"Error fetching ICEYE catalog: {e}")
            return False

    def _http_get(self, url: str, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """
        Perform HTTP GET using QGIS network manager.
        
        Args:
            url: URL to fetch
            timeout: Timeout in seconds
            
        Returns:
            Parsed JSON response or None on error
        """
        return self._http_get_json(url=url, timeout=timeout)

    def _http_get_json(
        self,
        url: str,
        timeout: int = 30,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self._allow_network:
            return None

        try:
            final_url = url
            if params:
                qp = urlencode({k: v for k, v in params.items() if v is not None and v != ''})
                if qp:
                    sep = '&' if '?' in final_url else '?'
                    final_url = f"{final_url}{sep}{qp}"

            request = QNetworkRequest(QUrl(final_url))
            request.setRawHeader(b"User-Agent", b"KADAS-Altair-Plugin/1.0")

            for key, value in (headers or {}).items():
                request.setRawHeader(str(key).encode('utf-8'), str(value).encode('utf-8'))

            blocking_request = QgsBlockingNetworkRequest()
            error_code = blocking_request.get(request, forceRefresh=False)

            if error_code != QgsBlockingNetworkRequest.NoError:
                logger.error(f"Network error for {final_url}: {blocking_request.errorMessage()}")
                return None

            reply: QgsNetworkReplyContent = blocking_request.reply()
            content: QByteArray = reply.content()

            if content.isEmpty():
                logger.warning(f"Empty response from {final_url}")
                return None

            json_str = bytes(content).decode('utf-8')
            return json.loads(json_str)

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for {url}: {e}")
            return None
        except Exception as e:
            logger.exception(f"HTTP GET error for {url}: {e}")
            return None

    def get_collections(self) -> List[Dict[str, Any]]:
        """
        Return list of ICEYE collections.
        
        ICEYE catalog has 3 child links to different organizational views:
        - ICEYE SAR - all
        - ICEYE SAR - by mode
        - ICEYE SAR - by continent
        
        Each child is a collection with direct item links (rel=item).
        
        Returns:
            List of dicts with keys: id, title, asset_count
        """
        cols: List[Dict[str, Any]] = []
        
        if not self._fetch_catalog_if_needed():
            logger.error("Cannot get collections: catalog not available")
            return cols

        # Get child links from catalog
        links = self._catalog.get('links', [])
        child_links = [l for l in links if l.get('rel') == 'child' and l.get('href')]
        
        if not child_links:
            logger.warning("No child collection links found in ICEYE catalog")
            return cols

        logger.info(f"Found {len(child_links)} child collection links")

        # Fetch each child collection
        for link in child_links:
            try:
                href = urljoin(self.base_url, link.get('href'))
                title = link.get('title', 'Unknown Collection')
                
                logger.debug(f"Fetching collection: {title} from {href}")
                data = self._http_get(href, timeout=10)
                
                if not data or not isinstance(data, dict):
                    logger.warning(f"Failed to fetch collection {title}")
                    continue
                
                # Extract collection info
                col_id = data.get('id', 'unknown')
                col_title = data.get('title') or title or col_id
                
                # Count item links (rel=item)
                col_links = data.get('links', [])
                item_links = [l for l in col_links if l.get('rel') == 'item']
                asset_count = len(item_links)
                
                col_dict = {
                    'id': col_id,
                    'title': col_title,
                    'asset_count': asset_count
                }
                
                cols.append(col_dict)
                logger.info(f"✅ Loaded collection '{col_title}' with {asset_count} items")
                
            except Exception as e:
                logger.exception(f"Error fetching collection {link.get('title', 'unknown')}: {e}")
                continue

        logger.info(f"Loaded {len(cols)} ICEYE collections total")
        return cols

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

        Translates the standard ``search_unified`` signature into the
        ICEYE-specific one (``collections`` list instead of a single
        ``collection`` string, and a ``query`` positional arg).
        """
        collections_list = [collection] if collection else None
        results = self.search(
            query=text_query or "",
            bbox=bbox,
            start_date=start_date,
            end_date=end_date,
            collections=collections_list,
            limit=limit,
        )
        return results, None

    def search(
        self,
        query: str = "",
        bbox: Optional[List[float]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        collections: Optional[List[str]] = None,
        limit: int = 1000,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Search ICEYE STAC items by navigating collection hierarchy.
        
        ICEYE catalog structure:
        1. Root catalog.json → child links to organizational collections
        2. Organizational collection → item links to GeoJSON items  
        3. Item GeoJSON → assets (SLC, GRD, QLK, CSI, VID COG files)
        
        This method recursively navigates all levels and returns individual items.
        
        NOTE: Default limit reduced from 100 to 30 for better performance.
        ICEYE static catalog requires fetching each item individually (slow).
        
        Args:
            query: Free-text search query (not used for ICEYE static catalog)
            bbox: [west, south, east, north] in WGS84
            start_date: ISO 8601 start date (e.g., '2023-01-01')
            end_date: ISO 8601 end date (e.g., '2023-12-31')
            collections: List of collection IDs to search (e.g., ['iceye-sar-all'])
            limit: Maximum items to return (default: 30, reduced from 100)
            **kwargs: Additional search parameters:
                - imaging_mode: Filter by imaging mode (STRIP, SPOT, SCAN, DWELL)
                - asset_type: Filter by asset type (slc, grd, qlk, csi, vid)
            
        Returns:
            List of STAC items matching criteria, with enriched metadata
        """
        logger.info(f"🔍 ICEYE Search START: bbox={bbox}, dates={start_date} to {end_date}, "
                   f"collections={collections}, limit={limit}")

        if self._api_access_token:
            return self._search_catalog_api(
                bbox=bbox,
                start_date=start_date,
                end_date=end_date,
                collections=collections,
                limit=limit,
            )
        
        if bbox:
            logger.info(f"🗺️  Bbox filter ACTIVE: [{bbox[0]:.4f}, {bbox[1]:.4f}, {bbox[2]:.4f}, {bbox[3]:.4f}]")
            logger.info(f"   └─ Format: [west={bbox[0]:.4f}, south={bbox[1]:.4f}, east={bbox[2]:.4f}, north={bbox[3]:.4f}]")
            
            # Validate bbox format
            if len(bbox) != 4:
                logger.error(f"Invalid bbox length: {len(bbox)}, expected 4. Disabling bbox filter.")
                bbox = None
            elif not all(isinstance(x, (int, float)) for x in bbox):
                logger.error(f"Invalid bbox types: {[type(x).__name__ for x in bbox]}. Disabling bbox filter.")
                bbox = None
            elif bbox[0] > bbox[2] or bbox[1] > bbox[3]:
                logger.error(f"Invalid bbox coordinates: west > east or south > north. Bbox: {bbox}")
                bbox = None
        else:
            logger.info(f"🌍 Bbox filter DISABLED (global search)")
        
        items = []
        total_items_fetched = 0
        total_items_filtered_out = 0
        
        if not self._fetch_catalog_if_needed():
            logger.error("Cannot search: catalog not available")
            return items

        # Extract additional filters from kwargs
        imaging_mode_filter = kwargs.get('imaging_mode')
        asset_type_filter = kwargs.get('asset_type')

        # Get child collection links from root catalog
        root_links = self._catalog.get('links', [])
        child_links = [l for l in root_links if l.get('rel') == 'child' and l.get('href')]
        
        if not child_links:
            logger.warning("No child collection links found in ICEYE catalog")
            return items
        
        logger.info(f"Found {len(child_links)} organizational collections in catalog")
        
        # Navigate each collection
        for coll_idx, coll_link in enumerate(child_links):
            if len(items) >= limit:
                break
            
            coll_title = coll_link.get('title', 'Unknown')
            
            try:
                coll_url = urljoin(self.base_url, coll_link.get('href'))
                
                logger.debug(f"Fetching collection {coll_idx+1}/{len(child_links)}: {coll_title}")
                
                coll_data = self._http_get(coll_url, timeout=10)
                if not coll_data:
                    logger.warning(f"Failed to fetch collection {coll_title}")
                    continue
                
                coll_id = coll_data.get('id', 'unknown')
                
                # Check collection filter
                if collections and coll_id not in collections:
                    logger.debug(f"Skipping collection {coll_id} (not in filter)")
                    continue
                
                # Get item links from this collection
                coll_links = coll_data.get('links', [])
                item_links = [l for l in coll_links if l.get('rel') == 'item' and l.get('href')]
                
                logger.info(f"Collection '{coll_title}' ({coll_id}): {len(item_links)} total items available")
                
                # PERFORMANCE OPTIMIZATION: Limit items fetched per collection
                # Don't fetch more than needed even if collection has thousands of items
                max_items_to_fetch = min(len(item_links), limit - len(items))
                logger.info(f"Will fetch up to {max_items_to_fetch} items from this collection (already have {len(items)}/{limit})")
                
                # Fetch individual items
                items_added_from_collection = 0
                for item_idx, item_link in enumerate(item_links[:max_items_to_fetch]):  # Only iterate needed items
                    if len(items) >= limit:
                        logger.info(f"Reached limit of {limit} items, stopping search")
                        break
                    
                    try:
                        item_href = item_link.get('href')
                        
                        # Handle relative URLs
                        if not item_href.startswith('http'):
                            item_url = urljoin(coll_url, item_href)
                        else:
                            item_url = item_href
                        
                        logger.debug(f"Fetching item {item_idx+1}/{len(item_links)}: {item_url}")
                        
                        item_data = self._http_get(item_url, timeout=6)
                        if not item_data:
                            logger.debug(f"Failed to fetch item {item_idx+1}")
                            continue
                        
                        total_items_fetched += 1
                        
                        # Apply filters
                        if not self._item_matches_filters(
                            item_data, bbox, start_date, end_date, 
                            imaging_mode_filter, asset_type_filter
                        ):
                            total_items_filtered_out += 1
                            logger.debug(f"Item {item_data.get('id', 'unknown')} filtered out by search criteria")
                            continue
                        
                        # Convert to result format with enriched metadata
                        result = self._item_to_result(item_data, coll_id)
                        items.append(result)
                        items_added_from_collection += 1
                        
                        logger.debug(f"✓ Added item {item_data.get('id')} (total: {len(items)})")
                        
                    except Exception as e:
                        logger.debug(f"Error fetching item {item_idx+1}: {e}")
                        continue
                
                logger.info(f"Collection '{coll_title}': added {items_added_from_collection} items after filtering")
                
            except Exception as e:
                logger.warning(f"Error processing collection {coll_title}: {e}")
                continue
        
        logger.info(f"📊 ICEYE Search STATS:")
        logger.info(f"   Total items fetched: {total_items_fetched}")
        logger.info(f"   Items filtered out: {total_items_filtered_out}")
        logger.info(f"   Items passing filters: {len(items)}")
        logger.info(f"✅ Search completed: {len(items)} ICEYE SAR items found (from {len(child_links)} collections)")
        return items

    def _search_catalog_api(
        self,
        bbox: Optional[List[float]],
        start_date: Optional[str],
        end_date: Optional[str],
        collections: Optional[List[str]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        headers = {
            'Accept': 'application/json, application/problem+json',
            'Authorization': f'Bearer {self._api_access_token}',
        }

        params: Dict[str, Any] = {}
        if bbox and len(bbox) >= 4:
            params['bbox'] = ','.join(str(v) for v in bbox[:4])

        datetime_expr = self._build_datetime_expr(start_date, end_date)
        if datetime_expr:
            params['datetime'] = datetime_expr

        requested_collections = collections or self._api_collections
        if requested_collections:
            params['collections'] = ','.join(requested_collections)

        if self._api_contract_id:
            params['contractID'] = self._api_contract_id

        results: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        page_index = 0

        while len(results) < limit and page_index < 50:
            page_index += 1
            remaining = max(1, limit - len(results))
            page_params = dict(params)
            page_params['limit'] = str(min(100, remaining))
            if cursor:
                page_params['cursor'] = cursor

            payload = self._http_get_json(
                self._catalog_items_url(),
                timeout=20,
                headers=headers,
                params=page_params,
            )
            if not payload:
                break

            features = payload.get('features')
            if not isinstance(features, list):
                features = payload.get('items', [])
            if not isinstance(features, list):
                logger.warning('ICEYE Catalog API response has no features/items list')
                break

            for feature in features:
                if not isinstance(feature, dict):
                    continue
                if not self._item_matches_filters(feature, bbox, start_date, end_date):
                    continue
                results.append(self._item_to_result(feature, feature.get('collection')))
                if len(results) >= limit:
                    break

            cursor = payload.get('cursor')
            if not cursor:
                break

        logger.info(f"✅ ICEYE Catalog API search completed: {len(results)} item(s)")
        return results

    @staticmethod
    def _build_datetime_expr(start_date: Optional[str], end_date: Optional[str]) -> Optional[str]:
        if not start_date and not end_date:
            return None
        start = IceyeStacConnector._to_rfc3339(start_date) if start_date else '..'
        end = IceyeStacConnector._to_rfc3339(end_date, end_of_day=True) if end_date else '..'
        return f"{start}/{end}"

    @staticmethod
    def _to_rfc3339(value: str, end_of_day: bool = False) -> str:
        value = str(value).strip()
        if len(value) == 10 and value.count('-') == 2 and 'T' not in value:
            suffix = 'T23:59:59Z' if end_of_day else 'T00:00:00Z'
            return f"{value}{suffix}"
        if value.endswith('Z'):
            return value
        if '+' in value or value.endswith('00:00'):
            try:
                dt = datetime.fromisoformat(value)
                return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            except Exception:
                return value
        return f"{value}Z" if 'T' in value else value
    
    def _item_to_result(self, item: Dict[str, Any], collection_id: Optional[str] = None) -> Dict[str, Any]:
        """Convert STAC item (with assets) to enriched result dict.
        
        Extracts and categorizes ICEYE-specific metadata including:
        - Asset types (SLC, GRD, QLK, CSI, VID)
        - Imaging mode (STRIP, SPOT, SCAN, DWELL)
        - SAR-specific parameters (polarization, resolution, etc.)
        - COG URLs for direct QGIS loading
        
        Args:
            item: STAC Item GeoJSON with assets
            collection_id: Parent collection ID
            
        Returns:
            Result dict compatible with plugin format, enriched with ICEYE metadata
        """
        props = item.get('properties', {})
        assets = item.get('assets', {})
        
        # Extract ICEYE-specific metadata
        imaging_mode = props.get('sar:imaging_mode') or props.get('imaging_mode', 'Unknown')
        polarization = props.get('sar:polarizations') or props.get('polarization')
        resolution = props.get('gsd') or props.get('resolution')
        
        # Categorize assets by type
        asset_summary = self._categorize_assets(assets)
        
        # Get primary preview asset (QLK preferred, then GRD)
        preview_url = None
        for asset_type in ['qlk', 'quicklook', 'grd', 'ground_range_detected']:
            for asset_key, asset_data in assets.items():
                if asset_type in asset_key.lower():
                    preview_url = asset_data.get('href')
                    break
            if preview_url:
                break
        
        # Get acquisition datetime
        datetime_str = props.get('datetime', '')
        date_display = datetime_str.split('T')[0] if datetime_str else 'Unknown'
        
        result = {
            'id': item.get('id'),
            'title': props.get('title') or item.get('id'),
            'date': date_display,
            'datetime': datetime_str,
            'satellite': 'ICEYE SAR',
            'collection': collection_id or props.get('collection') or 'ICEYE',
            'bbox': item.get('bbox'),
            'geometry': item.get('geometry'),
            'assets': assets,
            'asset_summary': asset_summary,
            'properties': props,
            'stac_feature': item,
            'is_collection': False,
            
            # ICEYE-specific metadata
            'imaging_mode': imaging_mode,
            'polarization': polarization,
            'resolution': resolution,
            'preview_url': preview_url,
            'platform': 'ICEYE',
            'sensor_type': 'SAR',
            'license': 'CC-BY-4.0',
            
            # Cloud cover not applicable for SAR
            'cloud_cover': None
        }
        
        return result
    
    def _categorize_assets(self, assets: Dict[str, Any]) -> Dict[str, List[str]]:
        """Categorize ICEYE assets by type.
        
        Args:
            assets: Dict of STAC assets
            
        Returns:
            Dict mapping asset categories to asset keys
        """
        categorized = {
            'slc': [],
            'grd': [],
            'qlk': [],
            'csi': [],
            'vid': [],
            'metadata': [],
            'other': []
        }
        
        for asset_key, asset_data in assets.items():
            asset_key_lower = asset_key.lower()
            href = asset_data.get('href', '')
            
            # Categorize by key or href patterns
            if 'slc' in asset_key_lower or 'single_look' in asset_key_lower:
                categorized['slc'].append(asset_key)
            elif 'grd' in asset_key_lower or 'ground_range' in asset_key_lower:
                categorized['grd'].append(asset_key)
            elif 'qlk' in asset_key_lower or 'quicklook' in asset_key_lower or 'preview' in asset_key_lower:
                categorized['qlk'].append(asset_key)
            elif 'csi' in asset_key_lower or 'colorized' in asset_key_lower:
                categorized['csi'].append(asset_key)
            elif 'vid' in asset_key_lower or 'video' in asset_key_lower:
                categorized['vid'].append(asset_key)
            elif asset_key_lower.endswith('.json') or 'metadata' in asset_key_lower:
                categorized['metadata'].append(asset_key)
            else:
                categorized['other'].append(asset_key)
        
        return categorized

    def _item_matches_filters(
        self,
        item: Dict[str, Any],
        bbox: Optional[List[float]],
        start_date: Optional[str],
        end_date: Optional[str],
        imaging_mode: Optional[str] = None,
        asset_type: Optional[str] = None
    ) -> bool:
        """
        Check if item matches search filters.
        
        Args:
            item: STAC item
            bbox: Bounding box filter [west, south, east, north] in EPSG:4326
            start_date: Start date filter (ISO 8601)
            end_date: End date filter (ISO 8601)
            imaging_mode: Imaging mode filter (STRIP, SPOT, SCAN, DWELL)
            asset_type: Asset type filter (slc, grd, qlk, csi, vid)
            
        Returns:
            True if item matches all filters
        """
        item_id = item.get('id', 'unknown')
        props = item.get('properties', {})
        assets = item.get('assets', {})

        # Exclude synthetic aggregate/overview items that are not individual scenes.
        # ICEYE catalog contains an item like:
        #   000-iceye-sar-collection-footprints
        # with near-global bbox/geometry aggregating many scenes. Including it makes
        # bbox behavior look broken and causes table/map mismatch.
        item_id_lower = str(item_id).lower()
        if 'collection-footprints' in item_id_lower or item_id_lower.startswith('000-'):
            logger.debug(f"❌ EXCLUDING {item_id}: aggregate collection footprint/overview item")
            return False

        # Keep only actual scene items with usable assets.
        if not isinstance(assets, dict) or not assets:
            logger.debug(f"❌ EXCLUDING {item_id}: no usable assets")
            return False
        
        # Bbox filter (checks if item bbox overlaps filter bbox)
        if bbox:
            item_bbox = item.get('bbox')
            if not item_bbox or len(item_bbox) < 4:
                logger.debug(f"❌ EXCLUDING {item_id}: no valid bbox while bbox filter is active")
                return False
            
            if len(bbox) < 4:
                logger.warning(f"Filter bbox is invalid: {bbox} - ignoring bbox filter")
                return True
            
            # STAC bbox format: [west, south, east, north] (minX, minY, maxX, maxY)
            # Check for bbox intersection - if no overlap, exclude the item
            # No overlap occurs when:
            # - item is entirely west of filter (item_east < filter_west)
            # - item is entirely east of filter (item_west > filter_east)  
            # - item is entirely south of filter (item_north < filter_south)
            # - item is entirely north of filter (item_south > filter_north)
            item_west, item_south, item_east, item_north = item_bbox[0], item_bbox[1], item_bbox[2], item_bbox[3]
            filter_west, filter_south, filter_east, filter_north = bbox[0], bbox[1], bbox[2], bbox[3]
            
            no_overlap = (
                item_east < filter_west or    # item is west of filter
                item_west > filter_east or    # item is east of filter
                item_north < filter_south or  # item is south of filter
                item_south > filter_north     # item is north of filter
            )
            
            if no_overlap:
                logger.debug(f"❌ EXCLUDING {item_id}: bbox [{item_west:.2f}, {item_south:.2f}, {item_east:.2f}, {item_north:.2f}] "
                            f"does NOT overlap filter [{filter_west:.2f}, {filter_south:.2f}, {filter_east:.2f}, {filter_north:.2f}]")
                return False
            else:
                logger.debug(f"✅ INCLUDING {item_id}: bbox [{item_west:.2f}, {item_south:.2f}, {item_east:.2f}, {item_north:.2f}] "
                            f"OVERLAPS filter [{filter_west:.2f}, {filter_south:.2f}, {filter_east:.2f}, {filter_north:.2f}]")
        
        # Date filter
        if start_date or end_date:
            item_datetime = props.get('datetime')
            
            if item_datetime:
                try:
                    item_dt = self._parse_datetime_utc(item_datetime)
                    start_dt = self._parse_datetime_utc(start_date) if start_date else None
                    end_dt = self._parse_datetime_utc(end_date) if end_date else None

                    if start_dt and item_dt < start_dt:
                        return False

                    if end_dt:
                        if self._is_date_only(end_date):
                            if item_dt >= (end_dt + timedelta(days=1)):
                                return False
                        elif item_dt > end_dt:
                            return False
                except Exception:
                    if start_date and item_datetime < start_date:
                        return False
                    if end_date and item_datetime > end_date:
                        return False
        
        # Imaging mode filter
        if imaging_mode:
            item_mode = props.get('sar:imaging_mode') or props.get('imaging_mode', '')
            if imaging_mode.upper() not in item_mode.upper():
                return False
        
        # Asset type filter
        if asset_type:
            assets = item.get('assets', {})
            asset_type_lower = asset_type.lower()
            
            # Check if any asset matches the requested type
            has_asset_type = any(
                asset_type_lower in key.lower() 
                for key in assets.keys()
            )
            
            if not has_asset_type:
                return False
        
        return True

    @staticmethod
    def _is_date_only(value: Optional[str]) -> bool:
        value = (value or '').strip()
        return len(value) == 10 and value.count('-') == 2 and 'T' not in value

    @staticmethod
    def _parse_datetime_utc(value: str) -> datetime:
        raw = str(value).strip()
        if IceyeStacConnector._is_date_only(raw):
            return datetime.strptime(raw, '%Y-%m-%d').replace(tzinfo=timezone.utc)

        if raw.endswith('Z'):
            raw = f"{raw[:-1]}+00:00"

        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def download(self, item: Dict[str, Any], output_path: str) -> bool:
        """
        Download ICEYE item assets.
        
        Args:
            item: STAC item to download
            output_path: Local path to save files
            
        Returns:
            True if download successful
        """
        logger.warning("Download not yet implemented for ICEYE connector")
        # TODO: Implement download using QgsBlockingNetworkRequest
        return False

    def get_capabilities(self) -> Dict[str, bool]:
        """Return connector capabilities."""
        return self._capabilities.copy()

    def set_allow_network(self, allow: bool):
        """Enable/disable network requests (for testing)."""
        self._allow_network = allow
        logger.info(f"Network requests {'enabled' if allow else 'disabled'}")
