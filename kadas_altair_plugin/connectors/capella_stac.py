"""
Capella Space SAR Open Data STAC Connector
Provides access to Capella's high-resolution Synthetic Aperture Radar imagery

STAC Catalog: https://capella-open-data.s3.us-west-2.amazonaws.com/stac/catalog.json
Documentation: https://support.capellaspace.com
Interactive Map: https://felt.com/map/Capella-Space-Open-Data-bB24xsH3SuiUlpMdDbVRaA
License: CC BY 4.0
"""

import logging
import json
from typing import List, Dict, Optional
from datetime import datetime

from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.capella_stac')

try:
    from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager
    from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
    from qgis.PyQt.QtNetwork import QNetworkRequest
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False
    logger.warning("QGIS not available - Capella connector will use fallback HTTP")


class CapellaSTACConnector(ConnectorBase):
    """
    Connector for Capella Space SAR Open Data via STAC API
    
    Capella Space provides high-resolution SAR imagery from a constellation 
    of small satellites. ~1000 images organized by:
    - Product Type (SLC, GEO, GEC, SICD, SIDD, CPHD)
    - Instrument Mode (Spotlight, Stripmap, Sliding Spotlight)
    - Use Case
    - Capital cities
    - Datetime
    
    Architecture:
    - Root catalog: https://capella-open-data.s3.us-west-2.amazonaws.com/stac/catalog.json
    - Multiple organizational hierarchies (by product, mode, use case, etc.)
    - No authentication required (public open data)
    - STAC 1.0.0 compliant
    - COG format available
    """
    
    timeout_auth: float = 5.0      # Not used (no auth required)
    timeout_catalog: float = 30.0  # Root catalog load
    timeout_search: float = 60.0   # Full hierarchy traversal
    timeout_item: float = 15.0     # Individual item fetch
    
    # Capella STAC endpoints
    CATALOG_URL = 'https://capella-open-data.s3.us-west-2.amazonaws.com/stac/catalog.json'
    CATALOG_BASE = 'https://capella-open-data.s3.us-west-2.amazonaws.com/stac'
    
    # Organization types
    ORG_PRODUCT_TYPE = 'capella-open-data-by-product-type'
    ORG_INSTRUMENT_MODE = 'capella-open-data-by-instrument-mode'
    ORG_USE_CASE = 'capella-open-data-by-use-case'
    ORG_CAPITAL = 'capella-open-data-by-capital'
    ORG_DATETIME = 'capella-open-data-by-datetime'
    ORG_IEEE_CONTEST = 'capella-open-data-ieee-data-contest'
    
    def __init__(self):
        """Initialize Capella STAC connector"""
        super().__init__()
        self._catalog = None
        self._collections = {}
        self._items_cache = {}
        logger.info("Initialized Capella Space SAR Open Data STAC connector")
    
    def authenticate(self, credentials: dict) -> bool:
        """
        No authentication required for Capella Open Data
        
        Args:
            credentials: Ignored (public data)
            
        Returns:
            bool: Always True
        """
        logger.info("Capella Open Data - no authentication required")
        return True
    
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
            logger.info(f"Loading Capella STAC catalog from {self.CATALOG_URL}")
            
            if QGIS_AVAILABLE:
                catalog_data = self._fetch_qgis(self.CATALOG_URL, timeout)
            else:
                catalog_data = self._fetch_fallback(self.CATALOG_URL, timeout)
            
            if not catalog_data:
                logger.error("Failed to fetch Capella catalog")
                return False
            
            self._catalog = json.loads(catalog_data)
            logger.info(f"Loaded Capella catalog: {self._catalog.get('title', 'Unknown')}")
            logger.info(f"STAC version: {self._catalog.get('stac_version', 'Unknown')}")
            logger.info(f"Description: {self._catalog.get('description', '')[:100]}...")
            
            return True
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Capella catalog JSON: {e}")
            return False
        except Exception as e:
            logger.error(f"Error loading Capella catalog: {e}")
            return False
    
    def get_collections(self, organization: Optional[str] = None) -> List[Dict]:
        """
        Get available collections from catalog
        
        Args:
            organization: Filter by organization type:
                - 'product_type': By Product Type (GEO, GEC, SLC, etc.)
                - 'instrument_mode': By Instrument Mode (Spotlight, Stripmap, etc.)
                - 'use_case': By Use Case
                - 'capital': By Capital cities
                - 'datetime': By Datetime
                - 'ieee_contest': IEEE Data Contest 2026
                - None: All root collections
        
        Returns:
            List of collection info dicts with id, title, href, asset_count
        """
        if not self._catalog:
            if not self.load_catalog():
                logger.error("Failed to load catalog for collections")
                return []
        
        collections = []
        
        # Map organization names to catalog IDs
        org_map = {
            'product_type': self.ORG_PRODUCT_TYPE,
            'instrument_mode': self.ORG_INSTRUMENT_MODE,
            'use_case': self.ORG_USE_CASE,
            'capital': self.ORG_CAPITAL,
            'datetime': self.ORG_DATETIME,
            'ieee_contest': self.ORG_IEEE_CONTEST
        }
        
        # Extract child links
        for link in self._catalog.get('links', []):
            if link.get('rel') == 'child':
                href = link.get('href', '')
                title = link.get('title', 'Unknown')
                
                # Filter by organization if specified
                if organization:
                    target_org = org_map.get(organization)
                    if target_org and target_org not in href:
                        continue
                
                # Resolve relative URLs
                full_href = f"{self.CATALOG_BASE}/{href}" if href.startswith('./') else href
                
                # Fetch catalog to count subcollections/items
                asset_count = 0
                try:
                    if QGIS_AVAILABLE:
                        cat_data = self._fetch_qgis(full_href, self.timeout_item)
                    else:
                        cat_data = self._fetch_fallback(full_href, self.timeout_item)
                    
                    if cat_data:
                        cat = json.loads(cat_data)
                        # Count child collections or items
                        child_count = len([l for l in cat.get('links', []) if l.get('rel') in ['child', 'item']])
                        asset_count = child_count
                except Exception as e:
                    logger.warning(f"Error fetching catalog {full_href}: {e}")
                    asset_count = 0
                
                collections.append({
                    'id': title.lower().replace(' ', '_'),
                    'title': title,
                    'href': full_href,
                    'asset_count': asset_count,
                    'type': 'catalog' if href.endswith('catalog.json') else 'collection'
                })
        
        logger.info(f"Found {len(collections)} collections (org filter: {organization})")
        return collections
        return collections
    
    def get_subcollections(self, catalog_href: str, timeout: Optional[float] = None) -> List[Dict]:
        """
        Get subcollections from a catalog
        
        Args:
            catalog_href: URL to catalog
            timeout: Request timeout
            
        Returns:
            List of subcollection dicts
        """
        if timeout is None:
            timeout = self.timeout_item
        
        try:
            if QGIS_AVAILABLE:
                cat_data = self._fetch_qgis(catalog_href, timeout)
            else:
                cat_data = self._fetch_fallback(catalog_href, timeout)
            
            if not cat_data:
                return []
            
            catalog = json.loads(cat_data)
            subcollections = []
            
            for link in catalog.get('links', []):
                if link.get('rel') in ['child', 'item']:
                    href_relative = link.get('href', '')
                    # Convert relative to absolute URL
                    if href_relative.startswith('./'):
                        base_url = catalog_href.rsplit('/', 1)[0]
                        href_absolute = f"{base_url}/{href_relative[2:]}"
                    else:
                        href_absolute = href_relative
                    
                    subcollections.append({
                        'id': link.get('title', 'Unknown'),
                        'title': link.get('title', 'Unknown'),
                        'href': href_absolute,
                        'type': 'item' if link.get('rel') == 'item' else 'catalog'
                    })
            
            return subcollections
            
        except Exception as e:
            logger.error(f"Error loading subcollections from {catalog_href}: {e}")
            return []
    
    def search(self, query: dict) -> List[Dict]:
        """
        Search Capella STAC catalog
        
        Args:
            query: Search parameters dict with optional keys:
                - bbox: [west, south, east, north]
                - datetime: ISO 8601 date range
                - product_type: Filter by product (e.g., "GEO", "GEC", "SLC")
                - instrument_mode: Filter by mode (e.g., "spotlight", "stripmap")
                - use_case: Filter by use case
                - capital: Filter by capital city
                - limit: Max results (default: 10000 - effectively unlimited)
        
        Returns:
            List of STAC items matching query
        """
        if not self._catalog:
            if not self.load_catalog():
                logger.error("Failed to load catalog for search")
                return []
        
        limit = query.get('limit', 10000)
        bbox = query.get('bbox')
        product_type = query.get('product_type')
        instrument_mode = query.get('instrument_mode')
        
        results = []
        
        # Determine which organization to search
        if product_type:
            org = 'product_type'
        elif instrument_mode:
            org = 'instrument_mode'
        else:
            org = None  # Search all
        
        collections = self.get_collections(organization=org)
        
        logger.info(f"Searching {len(collections)} collections...")
        
        for collection in collections:
            if len(results) >= limit:
                break
            
            # Recursively fetch items from this collection
            items = self._fetch_collection_items(collection['href'])
            
            # Filter by bbox if specified
            if bbox and items:
                items = self._filter_by_bbox(items, bbox)
            
            results.extend(items[:limit - len(results)])
        
        logger.info(f"Search completed: {len(results)} items found")
        return results
    
    def _fetch_collection_items(self, collection_href: str, max_depth: int = 3) -> List[Dict]:
        """
        Recursively fetch STAC items from a collection catalog
        
        Args:
            collection_href: URL to collection/catalog
            max_depth: Maximum recursion depth
            
        Returns:
            List of STAC items
        """
        if max_depth <= 0:
            return []
        
        try:
            if QGIS_AVAILABLE:
                catalog_data = self._fetch_qgis(collection_href, self.timeout_item)
            else:
                catalog_data = self._fetch_fallback(collection_href, self.timeout_item)
            
            if not catalog_data:
                return []
            
            catalog = json.loads(catalog_data)
            items = []
            
            # Check if this is a collection with features
            if catalog.get('type') == 'Collection':
                # This is a STAC collection - look for items
                for link in catalog.get('links', []):
                    if link.get('rel') == 'item':
                        item_href = link.get('href', '')
                        if item_href.startswith('./'):
                            base_url = collection_href.rsplit('/', 1)[0]
                            item_href = f"{base_url}/{item_href[2:]}"
                        
                        item = self._fetch_item(item_href)
                        if item:
                            items.append(item)
            else:
                # This is a catalog - recurse into children
                for link in catalog.get('links', []):
                    if link.get('rel') == 'child':
                        child_href = link.get('href', '')
                        if child_href.startswith('./'):
                            base_url = collection_href.rsplit('/', 1)[0]
                            child_href = f"{base_url}/{child_href[2:]}"
                        
                        child_items = self._fetch_collection_items(child_href, max_depth - 1)
                        items.extend(child_items)
                    elif link.get('rel') == 'item':
                        item_href = link.get('href', '')
                        if item_href.startswith('./'):
                            base_url = collection_href.rsplit('/', 1)[0]
                            item_href = f"{base_url}/{item_href[2:]}"
                        
                        item = self._fetch_item(item_href)
                        if item:
                            items.append(item)
            
            logger.debug(f"Fetched {len(items)} items from {collection_href}")
            return items
            
        except Exception as e:
            logger.error(f"Error fetching items from {collection_href}: {e}")
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
        
        for item in items:
            item_bbox = item.get('bbox')
            if not item_bbox or len(item_bbox) < 4:
                continue
            
            # Check if bboxes intersect
            item_west, item_south, item_east, item_north = item_bbox[:4]
            
            if not (item_east < west or item_west > east or 
                    item_north < south or item_south > north):
                filtered.append(item)
        
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
        Capella provides GeoTIFF/COG assets, not tiled services
        
        Returns empty string as Capella uses COG/GeoTIFF assets
        """
        return ""
    
    def get_asset_urls(self, item: Dict) -> Dict[str, Dict]:
        """
        Extract asset URLs from STAC item
        
        Capella provides multiple product types:
        - GEO: Geocoded Terrain Corrected (best for visualization)
        - GEC: Geocoded Ellipsoid Corrected
        - SLC: Single Look Complex
        - SICD: Sensor Independent Complex Data
        - SIDD: Sensor Independent Derived Data
        - CPHD: Compensated Phase History Data
        
        Args:
            item: STAC item dict
            
        Returns:
            Dict of asset_key -> asset info dict
        """
        assets = {}
        
        for asset_key, asset_info in item.get('assets', {}).items():
            href = asset_info.get('href', '')
            asset_type = asset_info.get('type', '')
            title = asset_info.get('title', asset_key)
            roles = asset_info.get('roles', [])
            
            # Determine priority based on product type
            priority = 3
            if 'GEO' in asset_key.upper() or 'image/tiff' in asset_type:
                priority = 1  # GEO is best for visualization
            elif 'GEC' in asset_key.upper():
                priority = 2
            elif any(fmt in asset_key.upper() for fmt in ['SICD', 'SIDD', 'CPHD', 'SLC']):
                priority = 3
            
            assets[asset_key] = {
                'href': href,
                'type': asset_type,
                'title': title,
                'roles': roles,
                'priority': priority
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
        for asset_key in ['thumbnail', 'preview', 'overview', 'browse']:
            asset = item.get('assets', {}).get(asset_key)
            if asset:
                return asset.get('href')
        
        # Look for assets with 'thumbnail' or 'overview' role
        for asset_key, asset_info in item.get('assets', {}).items():
            roles = asset_info.get('roles', [])
            if 'thumbnail' in roles or 'overview' in roles:
                return asset_info.get('href')
        
        return None
    
    def get_product_info(self, item: Dict) -> Dict[str, str]:
        """
        Extract Capella-specific product information
        
        Args:
            item: STAC item dict
            
        Returns:
            Dict with product metadata
        """
        props = item.get('properties', {})
        
        return {
            'product_type': props.get('sar:product_type', 'Unknown'),
            'instrument_mode': props.get('sar:instrument_mode', 'Unknown'),
            'frequency_band': props.get('sar:frequency_band', 'Unknown'),
            'polarizations': ', '.join(props.get('sar:polarizations', [])),
            'resolution': props.get('sar:resolution_range', 'Unknown'),
            'looks_range': str(props.get('sar:looks_range', 'Unknown')),
            'looks_azimuth': str(props.get('sar:looks_azimuth', 'Unknown')),
            'observation_direction': props.get('sar:observation_direction', 'Unknown'),
            'platform': props.get('platform', 'Unknown'),
            'constellation': props.get('constellation', 'Capella')
        }
