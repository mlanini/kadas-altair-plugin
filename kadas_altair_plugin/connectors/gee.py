"""Google Earth Engine connector

Provides access to Google Earth Engine datasets via Earth Engine API.

Architecture:
- Requires Google Cloud Project ID and authentication
- Uses earthengine-api Python library
- Searches official GEE catalog (from opengeos/Earth-Engine-Catalog)
- Returns tile URLs for visualization in QGIS

Data source:
- Official GEE Catalog: https://raw.githubusercontent.com/opengeos/Earth-Engine-Catalog/master/gee_catalog.json
- Community Catalog: https://raw.githubusercontent.com/samapriya/awesome-gee-community-datasets/master/community_datasets.json

License: Requires Google Earth Engine account
Attribution: © Google Earth Engine

References:
- https://github.com/opengeos/qgis-gee-data-catalogs-plugin
- https://developers.google.com/earth-engine
"""
import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.gee')

# Try to import Earth Engine
try:
    import ee
    EE_AVAILABLE = True
except ImportError:
    EE_AVAILABLE = False
    logger.warning("Google Earth Engine API (earthengine-api) not installed")


class GeeConnector(ConnectorBase):
    """Google Earth Engine connector
    
    Features:
    - Browse official and community GEE datasets
    - Search by keywords, category, data type
    - Client-side filtering for bbox, datetime
    - Tile service URL generation for QGIS visualization
    - Requires authentication and GCP Project ID
    """
    
    # Catalog URLs
    OFFICIAL_CATALOG_URL = 'https://raw.githubusercontent.com/opengeos/Earth-Engine-Catalog/master/gee_catalog.json'
    COMMUNITY_CATALOG_URL = 'https://raw.githubusercontent.com/samapriya/awesome-gee-community-datasets/master/community_datasets.json'
    
    # Cache timeout (seconds)
    catalog_cache_timeout: float = 3600.0  # 1 hour
    
    def __init__(self, project_id: Optional[str] = None):
        super().__init__()
        self.project_id = project_id
        self.authenticated = False
        self._catalog_cache: Optional[List[Dict[str, Any]]] = None
        self._catalog_cache_time: float = 0

    def _check_ee_available(self) -> bool:
        """Check if Earth Engine API is available"""
        if not EE_AVAILABLE:
            logger.error("Google Earth Engine API not installed. Install with: pip install earthengine-api")
            return False
        return True

    def _load_catalog(self) -> List[Dict[str, Any]]:
        """Load and cache GEE catalog data"""
        import time
        
        # Check cache
        if self._catalog_cache is not None:
            cache_age = time.time() - self._catalog_cache_time
            if cache_age < self.catalog_cache_timeout:
                logger.debug(f"Using cached catalog (age: {cache_age:.0f}s)")
                return self._catalog_cache
        
        datasets = []
        
        # Load official catalog
        try:
            logger.info(f"Fetching official GEE catalog from {self.OFFICIAL_CATALOG_URL}")
            with urlopen(self.OFFICIAL_CATALOG_URL, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                if isinstance(data, list):
                    for item in data:
                        item['source'] = 'official'
                    datasets.extend(data)
                    logger.info(f"Loaded {len(data)} datasets from official catalog")
        except Exception as e:
            logger.error(f"Failed to load official catalog: {e}")
        
        # Load community catalog
        try:
            logger.info(f"Fetching community GEE catalog from {self.COMMUNITY_CATALOG_URL}")
            with urlopen(self.COMMUNITY_CATALOG_URL, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                if isinstance(data, list):
                    for item in data:
                        item['source'] = 'community'
                    datasets.extend(data)
                    logger.info(f"Loaded {len(data)} datasets from community catalog")
        except Exception as e:
            logger.warning(f"Failed to load community catalog: {e}")
        
        # Cache the results
        self._catalog_cache = datasets
        self._catalog_cache_time = time.time()
        
        logger.info(f"Total datasets loaded: {len(datasets)}")
        return datasets

    def authenticate(self, credentials: Optional[dict] = None, verify: bool = True) -> bool:
        """Initialize Earth Engine connection.
        
        Args:
            credentials: Dict with optional 'project_id' key
            verify: If True, attempt to initialize EE
        """
        if not self._check_ee_available():
            return False
        
        # Extract project ID from credentials if provided
        if credentials and 'project_id' in credentials:
            self.project_id = credentials['project_id']
        
        if not verify:
            self.authenticated = True
            logger.debug('GEE: offline mode (skipped initialization)')
            return True
        
        try:
            # Check if already initialized
            try:
                ee.Number(1).getInfo()
                self.authenticated = True
                logger.info('GEE: Already initialized')
                return True
            except:
                pass
            
            # Initialize Earth Engine
            logger.info(f'GEE: Initializing Earth Engine (project: {self.project_id or "auto-detect"})...')
            
            if self.project_id:
                ee.Initialize(project=self.project_id)
            else:
                ee.Initialize()
            
            # Test the connection
            ee.Number(1).getInfo()
            
            self.authenticated = True
            logger.info('GEE: Earth Engine initialized successfully')
            return True
            
        except Exception as e:
            error_msg = str(e)
            if 'authentication' in error_msg.lower() or 'credential' in error_msg.lower():
                logger.error(
                    "GEE: Authentication required. Please run in Python Console:\n"
                    "  import ee\n"
                    "  ee.Authenticate()\n"
                    "Then set your Project ID in credentials."
                )
            else:
                logger.error(f'GEE: Failed to initialize Earth Engine: {error_msg}')
            
            self.authenticated = False
            return False

    def is_authenticated(self) -> bool:
        """Check if connector is authenticated"""
        return self.authenticated

    def get_collections(self) -> List[Dict[str, Any]]:
        """Return list of dataset categories.
        
        Returns:
            List of collection dicts with id, title, asset_count
        """
        cols: List[Dict[str, Any]] = []
        
        if not self.authenticated:
            logger.warning('GEE: not authenticated, cannot get collections')
            return cols
        
        # Load catalog
        datasets = self._load_catalog()
        
        # Group by category
        categories = {}
        for dataset in datasets:
            category = dataset.get('category', 'Other')
            if category not in categories:
                categories[category] = []
            categories[category].append(dataset)
        
        # Create collection entries
        for category, cat_datasets in sorted(categories.items()):
            cols.append({
                'id': category,
                'title': category,
                'asset_count': len(cat_datasets)
            })
        
        logger.info(f"GEE: Found {len(cols)} categories")
        return cols

    def search(self, bbox: Optional[List[float]] = None, start_date: str = "", end_date: str = "",
               max_cloud_cover: Optional[float] = None, collection: Optional[str] = None,
               limit: int = 1000, **kwargs) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Search for datasets in GEE catalog.
        
        Args:
            bbox: Bounding box [minx, miny, maxx, maxy] in EPSG:4326 (not used for catalog search)
            start_date: Start date (YYYY-MM-DD) (not used for catalog search)
            end_date: End date (YYYY-MM-DD) (not used for catalog search)
            max_cloud_cover: Maximum cloud cover (not used for catalog search)
            collection: Category filter (e.g., "Satellite Imagery", "Climate")
            limit: Maximum number of results
            **kwargs: Additional parameters (query text, data_type filter)
            
        Returns:
            Tuple of (results list, next_token)
        """
        logger.info(f"GEE.search() called with collection={collection}, limit={limit}, kwargs={kwargs}")
        
        if not self.authenticated:
            logger.error('GEE: not authenticated')
            return [], None
        
        # Load catalog
        datasets = self._load_catalog()
        
        # Extract filters from kwargs
        query = kwargs.get('query', kwargs.get('text_query', '')).lower().strip()
        data_type = kwargs.get('data_type', None)
        
        results = []
        
        for dataset in datasets:
            if len(results) >= limit:
                break
            
            # Filter by category
            if collection and dataset.get('category') != collection:
                continue
            
            # Filter by data type
            if data_type and dataset.get('type') != data_type:
                continue
            
            # Filter by query text
            if query:
                searchable_text = ' '.join([
                    str(dataset.get('name', '')),
                    str(dataset.get('title', '')),
                    str(dataset.get('description', '')),
                    str(dataset.get('id', '')),
                    ' '.join(dataset.get('keywords', []) if isinstance(dataset.get('keywords'), list) else [])
                ]).lower()
                
                if query not in searchable_text:
                    continue
            
            # Convert to result format
            result = self._dataset_to_result(dataset)
            results.append(result)
        
        logger.info(f"GEE: Search completed, found {len(results)} datasets")
        return results, None

    def _dataset_to_result(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        """Convert catalog dataset to result dict"""
        asset_id = dataset.get('id', '')
        
        result = {
            'id': asset_id,
            'title': dataset.get('name', dataset.get('title', asset_id)),
            'collection': dataset.get('category', 'Other'),
            'bbox': None,  # GEE datasets typically don't have bbox in catalog
            'geometry': None,
            'properties': {
                'asset_id': asset_id,
                'type': dataset.get('type', 'Unknown'),
                'description': dataset.get('description', ''),
                'provider': dataset.get('provider', 'Unknown'),
                'source': dataset.get('source', 'unknown'),
                'start_date': dataset.get('start_date', ''),
                'end_date': dataset.get('end_date', ''),
                'keywords': dataset.get('keywords', []),
                'thumbnail': dataset.get('thumbnail', ''),
            },
            'assets': {},
            'is_collection': False,
            'gee_dataset': dataset,  # Store original dataset
        }
        
        return result

    def get_tile_url(self, result: dict, z: int, x: int, y: int) -> str:
        """Get tile URL for a result using Earth Engine tile service.
        
        Args:
            result: Search result dictionary
            z: Zoom level
            x: Tile x coordinate
            y: Tile y coordinate
            
        Returns:
            Tile URL string
        """
        if not self.authenticated or not self._check_ee_available():
            return ''
        
        try:
            asset_id = result.get('properties', {}).get('asset_id') or result.get('id')
            if not asset_id:
                return ''
            
            # Get dataset type
            dataset_type = result.get('properties', {}).get('type', 'Image')
            
            # Load EE object
            if dataset_type == 'ImageCollection':
                ee_object = ee.ImageCollection(asset_id).mosaic()
            elif dataset_type == 'FeatureCollection':
                ee_object = ee.FeatureCollection(asset_id)
            else:
                ee_object = ee.Image(asset_id)
            
            # Get visualization parameters
            vis_params = result.get('gee_dataset', {}).get('vis_params', {})
            
            # Generate tile URL
            map_id = ee_object.getMapId(vis_params)
            tile_url = map_id['tile_fetcher'].url_format
            
            return tile_url
            
        except Exception as e:
            logger.error(f"Failed to get tile URL for {result.get('id')}: {e}")
            return ''
