"""NASA EarthData connector

Provides access to NASA EarthData catalog via earthaccess library.

Architecture:
- Uses earthaccess Python library for authentication and search
- Searches via NASA CMR (Common Metadata Repository)
- Loads dataset catalog from opengeos/NASA-Earth-Data TSV
- Returns granules with COG support and download capabilities

Data source:
- NASA CMR API: https://cmr.earthdata.nasa.gov/
- Dataset Catalog: https://github.com/opengeos/NASA-Earth-Data/raw/main/nasa_earth_data.tsv
- Authentication: https://urs.earthdata.nasa.gov/

License: Requires free NASA Earthdata account
Attribution: © NASA

References:
- https://github.com/opengeos/qgis-nasa-earthdata-plugin
- https://github.com/nsidc/earthaccess
- https://earthdata.nasa.gov/
"""
import json
import logging
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from .base import ConnectorBase
from ..logger import get_logger

logger = get_logger('connectors.nasa_earthdata')

# Try to import earthaccess
try:
    import earthaccess
    EARTHACCESS_AVAILABLE = True
except ImportError:
    EARTHACCESS_AVAILABLE = False
    logger.warning("earthaccess library not installed")

# Try to import pandas for catalog loading
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logger.warning("pandas library not installed")


class NasaEarthdataConnector(ConnectorBase):
    """NASA EarthData connector
    
    Features:
    - Search NASA Earth science datasets via CMR API
    - Browse 9,000+ datasets (GEDI, MODIS, Landsat, Sentinel, etc.)
    - COG (Cloud Optimized GeoTIFF) support
    - Download capabilities with authentication
    - Client-side filtering for bbox, datetime, cloud cover
    - Requires free NASA Earthdata account
    """
    
    # NASA dataset catalog URL
    CATALOG_URL = 'https://github.com/opengeos/NASA-Earth-Data/raw/main/nasa_earth_data.tsv'
    
    # Cache settings
    catalog_cache_timeout: float = 604800.0  # 7 days in seconds
    
    def __init__(self, username: Optional[str] = None, password: Optional[str] = None):
        super().__init__()
        self.username = username
        self.password = password
        self.authenticated = False
        self._catalog_cache: Optional[Any] = None  # pandas DataFrame
        self._catalog_cache_time: float = 0
        self._catalog_names: List[str] = []
        
        # Cache directory
        self.cache_dir = Path(tempfile.gettempdir()) / "nasa_earthdata_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_cache_file = self.cache_dir / "nasa_earth_data.tsv"

    def _check_earthaccess_available(self) -> bool:
        """Check if earthaccess is available"""
        if not EARTHACCESS_AVAILABLE:
            logger.error("earthaccess library not installed. Install with: pip install earthaccess")
            return False
        return True

    def _check_pandas_available(self) -> bool:
        """Check if pandas is available"""
        if not PANDAS_AVAILABLE:
            logger.error("pandas library not installed. Install with: pip install pandas")
            return False
        return True

    def _load_catalog(self) -> Any:
        """Load and cache NASA EarthData catalog"""
        import time
        
        if not self._check_pandas_available():
            return None
        
        # Check cache
        if self._catalog_cache is not None:
            cache_age = time.time() - self._catalog_cache_time
            if cache_age < self.catalog_cache_timeout:
                logger.debug(f"Using cached catalog (age: {cache_age:.0f}s)")
                return self._catalog_cache
        
        # Check if file cache exists and is fresh
        use_file_cache = False
        if self.catalog_cache_file.exists():
            cache_age = time.time() - self.catalog_cache_file.stat().st_mtime
            if cache_age < self.catalog_cache_timeout:
                use_file_cache = True
                logger.debug(f"Loading catalog from file cache (age: {cache_age:.0f}s)")
        
        try:
            if use_file_cache:
                df = pd.read_csv(self.catalog_cache_file, sep='\t')
                logger.info(f"Loaded {len(df)} datasets from file cache")
            else:
                logger.info(f"Fetching NASA EarthData catalog from {self.CATALOG_URL}")
                df = pd.read_csv(self.CATALOG_URL, sep='\t')
                # Save to file cache
                df.to_csv(self.catalog_cache_file, sep='\t', index=False)
                logger.info(f"Loaded {len(df)} datasets from URL and cached")
            
            # Cache in memory
            self._catalog_cache = df
            self._catalog_cache_time = time.time()
            
            # Extract short names for collections
            if 'ShortName' in df.columns:
                self._catalog_names = df['ShortName'].tolist()
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to load NASA EarthData catalog: {e}")
            return None

    def authenticate(self, credentials: Optional[dict] = None, verify: bool = True) -> bool:
        """Initialize NASA EarthData authentication.
        
        Args:
            credentials: Dict with 'username' and 'password' keys
            verify: If True, attempt to authenticate with NASA
        """
        if not self._check_earthaccess_available():
            return False
        
        # Extract credentials if provided
        if credentials:
            self.username = credentials.get('username')
            self.password = credentials.get('password')
        
        if not verify:
            self.authenticated = True
            logger.debug('NASA EarthData: offline mode (skipped authentication)')
            return True
        
        try:
            import os
            
            # Set environment variables for earthaccess
            if self.username and self.password:
                os.environ['EARTHDATA_USERNAME'] = self.username
                os.environ['EARTHDATA_PASSWORD'] = self.password
            
            # Try to authenticate using environment variables
            logger.info('NASA EarthData: Authenticating...')
            auth = earthaccess.login(strategy="environment", persist=True)
            
            if auth.authenticated:
                self.authenticated = True
                logger.info('NASA EarthData: Authentication successful')
                return True
            else:
                logger.error('NASA EarthData: Authentication failed')
                self.authenticated = False
                return False
                
        except Exception as e:
            error_msg = str(e)
            if 'credential' in error_msg.lower():
                logger.error(
                    "NASA EarthData: Authentication required. Please provide valid credentials.\n"
                    "Register at: https://urs.earthdata.nasa.gov/"
                )
            else:
                logger.error(f'NASA EarthData: Failed to authenticate: {error_msg}')
            
            self.authenticated = False
            return False

    def is_authenticated(self) -> bool:
        """Check if connector is authenticated"""
        return self.authenticated

    def get_collections(self) -> List[Dict[str, Any]]:
        """Return list of NASA EarthData dataset categories.
        
        Returns:
            List of collection dicts with id, title, dataset_count
        """
        cols: List[Dict[str, Any]] = []
        
        # Load catalog
        df = self._load_catalog()
        if df is None or df.empty:
            logger.warning('NASA EarthData: catalog not loaded')
            return cols
        
        # Count datasets
        total_count = len(df)
        
        # Group by major categories (if available)
        if 'Category' in df.columns:
            categories = df['Category'].value_counts().to_dict()
            for category, count in categories.items():
                if pd.notna(category):
                    cols.append({
                        'id': str(category),
                        'title': str(category),
                        'dataset_count': count
                    })
        
        # Add "All Datasets" entry
        cols.insert(0, {
            'id': 'all',
            'title': 'All Datasets',
            'dataset_count': total_count
        })
        
        logger.info(f"NASA EarthData: Found {len(cols)} categories with {total_count} total datasets")
        return cols

    def search(self, bbox: Optional[List[float]] = None, start_date: str = "", end_date: str = "",
               max_cloud_cover: Optional[float] = None, collection: Optional[str] = None,
               limit: int = 50, **kwargs) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Search for granules in NASA EarthData via CMR.
        
        Args:
            bbox: Bounding box [minx, miny, maxx, maxy] in EPSG:4326
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            max_cloud_cover: Maximum cloud cover percentage (0-100)
            collection: Dataset ShortName (e.g., "HLSL30", "MOD13Q1")
            limit: Maximum number of results
            **kwargs: Additional parameters:
                - query: Text search in catalog
                - day_night_flag: "day", "night", or None
                - provider: Data provider filter
                - version: Dataset version filter
            
        Returns:
            Tuple of (results list, next_token)
        """
        logger.info(f"NASA EarthData.search() called with collection={collection}, bbox={bbox}, limit={limit}")
        
        if not self.authenticated:
            logger.error('NASA EarthData: not authenticated')
            return [], None
        
        if not self._check_earthaccess_available():
            return [], None
        
        # Extract filters
        query = kwargs.get('query', kwargs.get('text_query', '')).strip()
        day_night_flag = kwargs.get('day_night_flag')
        provider = kwargs.get('provider')
        version = kwargs.get('version')
        
        # If no collection specified but query provided, search catalog first
        if not collection and query:
            df = self._load_catalog()
            if df is not None:
                # Filter catalog by query
                mask = (
                    df['ShortName'].str.contains(query, case=False, na=False) |
                    df['EntryTitle'].str.contains(query, case=False, na=False)
                )
                filtered = df[mask]
                if not filtered.empty:
                    # Use first match
                    collection = filtered.iloc[0]['ShortName']
                    logger.info(f"Found dataset: {collection}")
        
        if not collection:
            logger.warning('NASA EarthData: no collection specified')
            return [], None
        
        try:
            # Build search parameters
            search_params = {
                'short_name': collection,
                'count': limit
            }
            
            # Bounding box
            if bbox:
                search_params['bounding_box'] = tuple(bbox)
            
            # Temporal range
            if start_date and end_date:
                search_params['temporal'] = (start_date, end_date)
            elif start_date:
                search_params['temporal'] = (start_date, datetime.now().strftime('%Y-%m-%d'))
            elif end_date:
                search_params['temporal'] = ('1970-01-01', end_date)
            
            # Cloud cover
            if max_cloud_cover is not None:
                search_params['cloud_cover'] = (0, max_cloud_cover)
            
            # Advanced filters
            if day_night_flag:
                search_params['day_night_flag'] = day_night_flag
            if provider:
                search_params['provider'] = provider
            if version:
                search_params['version'] = version
            
            logger.info(f"Searching NASA EarthData with params: {search_params}")
            
            # Execute search
            granules = earthaccess.search_data(**search_params)
            
            logger.info(f"NASA EarthData: Search completed, found {len(granules)} granules")
            
            # Convert to result format
            results = []
            for granule in granules:
                result = self._granule_to_result(granule)
                results.append(result)
            
            return results, None
            
        except Exception as e:
            logger.error(f"NASA EarthData search error: {e}")
            return [], None

    def _granule_to_result(self, granule: Any) -> Dict[str, Any]:
        """Convert earthaccess granule to result dict"""
        try:
            # Extract granule metadata
            granule_dict = dict(granule.items()) if hasattr(granule, 'items') else {}
            
            granule_id = granule_dict.get('producer_granule_id', granule_dict.get('title', ''))
            collection_id = granule_dict.get('short_name', '')
            
            # Extract temporal info
            time_start = granule_dict.get('time_start', '')
            time_end = granule_dict.get('time_end', '')
            
            # Extract spatial info
            bbox_list = granule_dict.get('boxes', [])
            bbox = None
            if bbox_list and len(bbox_list) > 0:
                # boxes format: [south, west, north, east]
                box = bbox_list[0].split()
                if len(box) == 4:
                    bbox = [float(box[1]), float(box[0]), float(box[3]), float(box[2])]  # [W, S, E, N]
            
            # Get data links
            data_links = []
            try:
                links = granule.data_links(access='external')
                data_links = [link for link in links if link.startswith('http')]
            except:
                pass
            
            # Check for COG files
            cog_links = [link for link in data_links if any(ext in link.lower() for ext in ['.tif', '.tiff'])]
            
            # Build assets
            assets = {}
            for i, link in enumerate(data_links):
                asset_key = f'data_{i}'
                assets[asset_key] = {
                    'href': link,
                    'type': 'application/octet-stream',
                    'title': link.split('/')[-1] if '/' in link else link
                }
            
            # Build result
            result = {
                'id': granule_id,
                'title': granule_id,
                'collection': collection_id,
                'bbox': bbox,
                'geometry': None,  # Would need polygon coordinates
                'properties': {
                    'datetime': time_start,
                    'start_datetime': time_start,
                    'end_datetime': time_end,
                    'platform': granule_dict.get('platform', ''),
                    'instrument': granule_dict.get('instrument', ''),
                    'cloud_cover': granule_dict.get('cloud_cover', None),
                    'provider': granule_dict.get('data_center', ''),
                    'version': granule_dict.get('version_id', ''),
                    'size_mb': granule_dict.get('granule_size', 0),
                    'data_links': data_links,
                    'cog_available': len(cog_links) > 0,
                },
                'assets': assets,
                'is_collection': False,
                'nasa_granule': granule,  # Store original granule
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error converting granule to result: {e}")
            return {
                'id': 'unknown',
                'title': 'Unknown',
                'collection': '',
                'bbox': None,
                'geometry': None,
                'properties': {},
                'assets': {},
                'is_collection': False,
            }

    def get_download_url(self, result: dict) -> Optional[str]:
        """Get authenticated download URL for a granule.
        
        Args:
            result: Search result dictionary
            
        Returns:
            Download URL string or None
        """
        if not self.authenticated or not self._check_earthaccess_available():
            return None
        
        try:
            # Get data links from properties
            data_links = result.get('properties', {}).get('data_links', [])
            if data_links:
                return data_links[0]
            
            # Fallback to assets
            assets = result.get('assets', {})
            if assets:
                first_asset = next(iter(assets.values()))
                return first_asset.get('href')
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting download URL: {e}")
            return None

    def download(self, result: dict, output_path: str) -> bool:
        """Download granule data with authentication.
        
        Args:
            result: Search result dictionary
            output_path: Output file path
            
        Returns:
            True if successful, False otherwise
        """
        if not self.authenticated or not self._check_earthaccess_available():
            return False
        
        try:
            # Get original granule object
            granule = result.get('nasa_granule')
            if not granule:
                logger.error("No granule object in result")
                return False
            
            # Use earthaccess to download
            logger.info(f"Downloading granule to {output_path}")
            files = earthaccess.download(granule, output_path)
            
            if files:
                logger.info(f"Downloaded {len(files)} file(s)")
                return True
            else:
                logger.error("Download failed - no files returned")
                return False
                
        except Exception as e:
            logger.error(f"Download error: {e}")
            return False
