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
import os
import csv
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from urllib.request import urlopen
from .base import ConnectorBase
from ..logger import get_logger

try:
    from ..secrets.secure_storage import get_secure_storage
except ImportError:
    def get_secure_storage():
        return None

logger = get_logger('connectors.nasa_earthdata')

# Try to import earthaccess
try:
    import earthaccess
    EARTHACCESS_AVAILABLE = True
except ImportError:
    EARTHACCESS_AVAILABLE = False
    logger.debug("earthaccess library not installed")

# Try to import pandas for catalog loading
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logger.debug("pandas library not installed")


class NasaEarthdataConnector(ConnectorBase):
    """NASA EarthData connector
    
    Features:
    - Search NASA Earth science datasets via CMR API
    - Browse 9,000+ datasets (GEDI, MODIS, Landsat, Sentinel, etc.)
    - COG (Cloud Optimized GeoTIFF) support
    - Download capabilities with authentication
    - Supports EDL username/password or existing Bearer token
    - Client-side filtering for bbox, datetime, cloud cover
    - Requires free NASA Earthdata account
    """
    
    # NASA dataset catalog URL
    CATALOG_URL = 'https://github.com/opengeos/NASA-Earth-Data/raw/main/nasa_earth_data.tsv'
    
    # Cache settings
    catalog_cache_timeout: float = 604800.0  # 7 days in seconds
    
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        access_token: Optional[str] = None,
    ):
        super().__init__()
        self.username = username
        self.password = password
        self.access_token = access_token
        self.authenticated = False
        self._auth = None
        self._auth_source = ""
        self._catalog_cache: Optional[Any] = None  # pandas DataFrame
        self._catalog_cache_time: float = 0
        self._catalog_names: List[str] = []
        
        # Cache directory
        self.cache_dir = Path(tempfile.gettempdir()) / "nasa_earthdata_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_cache_file = self.cache_dir / "nasa_earth_data.tsv"

    def _load_stored_credentials(self) -> None:
        """Load NASA credentials from secure storage and environment.

        Priority:
        1. Explicit constructor/authenticate() values already set on self
        2. Secure storage values saved by the settings panel
        3. Environment variables (EARTHDATA_TOKEN, USERNAME/PASSWORD)
        4. .netrc is handled directly by earthaccess during login
        """
        try:
            secure_storage = get_secure_storage()
            if secure_storage:
                creds = secure_storage.get_credentials('nasa_earthdata') or {}
                if not self.username:
                    self.username = creds.get('username') or self.username
                if not self.password:
                    self.password = creds.get('password') or self.password
                if not self.access_token:
                    self.access_token = (
                        creds.get('access_token')
                        or creds.get('token')
                        or self.access_token
                    )
        except Exception as e:
            logger.debug(f"NASA EarthData: could not load secure storage credentials: {e}")

        self.access_token = self.access_token or os.environ.get('EARTHDATA_TOKEN')
        self.username = self.username or os.environ.get('EARTHDATA_USERNAME')
        self.password = self.password or os.environ.get('EARTHDATA_PASSWORD')

    def _update_credentials(self, credentials: Optional[dict] = None) -> None:
        """Apply explicit credentials and merge with stored sources."""
        if credentials:
            self.username = credentials.get('username') or self.username
            self.password = credentials.get('password') or self.password
            self.access_token = (
                credentials.get('access_token')
                or credentials.get('token')
                or self.access_token
            )

        self._load_stored_credentials()

    def _prime_environment(self) -> None:
        """Populate environment variables for earthaccess.

        earthaccess supports:
        - EARTHDATA_USERNAME + EARTHDATA_PASSWORD
        - EARTHDATA_TOKEN (existing EDL bearer token)
        """
        if self.access_token:
            os.environ['EARTHDATA_TOKEN'] = self.access_token

        if self.username and self.password:
            os.environ['EARTHDATA_USERNAME'] = self.username
            os.environ['EARTHDATA_PASSWORD'] = self.password

    def _login_with_earthaccess(self):
        """Authenticate with earthaccess using the best available strategy."""
        self._prime_environment()

        attempts = []
        if self.access_token:
            attempts.append(("environment", "token"))
        if self.username and self.password:
            attempts.append(("environment", "username/password"))

        # Fallbacks handled by earthaccess itself
        attempts.extend([
            ("netrc", ".netrc"),
            ("environment", "environment"),
        ])

        last_error = None
        for strategy, label in attempts:
            try:
                logger.info(f"NASA EarthData: Authenticating via {label} ({strategy})")
                auth = earthaccess.login(strategy=strategy, persist=False)
                if getattr(auth, 'authenticated', False):
                    self._auth_source = label
                    return auth
            except Exception as e:
                last_error = e
                logger.debug(f"NASA EarthData: auth attempt via {label} failed: {e}")

        if last_error:
            raise last_error
        raise Exception("No valid Earthdata authentication method available")

    def _check_earthaccess_available(self) -> bool:
        """Check if earthaccess is available"""
        if not EARTHACCESS_AVAILABLE:
            logger.warning("earthaccess library not installed. Install with: pip install earthaccess")
            return False
        return True

    def _check_pandas_available(self) -> bool:
        """Check if pandas is available"""
        if not PANDAS_AVAILABLE:
            logger.info("pandas library not installed. Falling back to CSV parser")
            return False
        return True

    def _load_catalog_csv_rows(self, from_cache: bool) -> List[Dict[str, Any]]:
        """Load NASA TSV catalog using stdlib CSV (no pandas required)."""
        rows: List[Dict[str, Any]] = []

        if from_cache and self.catalog_cache_file.exists():
            with open(self.catalog_cache_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                rows = list(reader)
            logger.info(f"Loaded {len(rows)} datasets from file cache (csv fallback)")
            return rows

        logger.info(f"Fetching NASA EarthData catalog from {self.CATALOG_URL} (csv fallback)")
        with urlopen(self.CATALOG_URL, timeout=30) as resp:  # nosec B310
            text = resp.read().decode('utf-8')

        self.catalog_cache_file.write_text(text, encoding='utf-8')
        reader = csv.DictReader(text.splitlines(), delimiter='\t')
        rows = list(reader)
        logger.info(f"Loaded {len(rows)} datasets from URL and cached (csv fallback)")
        return rows

    def _catalog_find_first_shortname(self, catalog: Any, query: str) -> Optional[str]:
        """Find the first matching ShortName by text query across catalog formats."""
        if not query:
            return None

        q = query.lower()

        # pandas DataFrame path
        if PANDAS_AVAILABLE and hasattr(catalog, 'columns'):
            try:
                mask = (
                    catalog['ShortName'].str.contains(query, case=False, na=False)
                    | catalog['EntryTitle'].str.contains(query, case=False, na=False)
                )
                filtered = catalog[mask]
                if not filtered.empty:
                    return filtered.iloc[0]['ShortName']
            except Exception:
                return None

        # csv rows path
        if isinstance(catalog, list):
            for row in catalog:
                short_name = str(row.get('ShortName', '') or '')
                entry_title = str(row.get('EntryTitle', '') or '')
                if q in short_name.lower() or q in entry_title.lower():
                    return short_name or None

        return None

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
        """Forward unified manager params, including `text_query`, to `search()`."""
        return self.search(
            bbox=bbox,
            start_date=start_date or "",
            end_date=end_date or "",
            max_cloud_cover=max_cloud_cover,
            collection=collection,
            limit=limit,
            text_query=text_query or "",
            query=text_query or "",
        )

    def _load_catalog(self) -> Any:
        """Load and cache NASA EarthData catalog"""
        import time
        
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
            if PANDAS_AVAILABLE:
                if use_file_cache:
                    df = pd.read_csv(self.catalog_cache_file, sep='\t')
                    logger.info(f"Loaded {len(df)} datasets from file cache")
                else:
                    logger.info(f"Fetching NASA EarthData catalog from {self.CATALOG_URL}")
                    df = pd.read_csv(self.CATALOG_URL, sep='\t')
                    # Save to file cache
                    df.to_csv(self.catalog_cache_file, sep='\t', index=False)
                    logger.info(f"Loaded {len(df)} datasets from URL and cached")

                catalog_obj: Any = df
            else:
                catalog_obj = self._load_catalog_csv_rows(from_cache=use_file_cache)
            
            # Cache in memory
            self._catalog_cache = catalog_obj
            self._catalog_cache_time = time.time()
            
            # Extract short names for collections
            if PANDAS_AVAILABLE and hasattr(catalog_obj, 'columns'):
                if 'ShortName' in catalog_obj.columns:
                    self._catalog_names = catalog_obj['ShortName'].tolist()
            elif isinstance(catalog_obj, list):
                self._catalog_names = [
                    str(r.get('ShortName', '')).strip()
                    for r in catalog_obj
                    if str(r.get('ShortName', '')).strip()
                ]
            
            return catalog_obj
            
        except Exception as e:
            logger.error(f"Failed to load NASA EarthData catalog: {e}")
            return None

    def authenticate(self, credentials: Optional[dict] = None, verify: bool = True) -> bool:
        """Initialize NASA EarthData authentication.
        
        Args:
            credentials: Dict with `username`/`password` and/or `access_token`
            verify: If True, attempt to authenticate with NASA
        """
        if not self._check_earthaccess_available():
            return False

        self._update_credentials(credentials)
        
        if not verify:
            self.authenticated = bool(
                self.access_token
                or (self.username and self.password)
                or os.environ.get('EARTHDATA_TOKEN')
                or os.environ.get('EARTHDATA_USERNAME')
            )
            logger.debug('NASA EarthData: skipped live verification')
            return True
        
        try:
            auth = self._login_with_earthaccess()
            
            if getattr(auth, 'authenticated', False):
                self._auth = auth
                self.authenticated = True
                logger.info(f'NASA EarthData: Authentication successful via {self._auth_source}')
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
            
            self._auth = None
            self.authenticated = False
            return False

    def is_authenticated(self) -> bool:
        """Check if connector is authenticated"""
        return self.authenticated

    def get_session(self):
        """Return the authenticated earthaccess session when available."""
        if self._auth and hasattr(self._auth, 'get_session'):
            try:
                return self._auth.get_session()
            except Exception as e:
                logger.debug(f"NASA EarthData: could not get authenticated session: {e}")
        return super().get_session()

    def get_auth_headers(self) -> Dict[str, str]:
        """Return request headers for authenticated downloads/streaming."""
        headers: Dict[str, str] = {}

        session = self.get_session()
        if session is not None:
            try:
                headers.update(dict(getattr(session, 'headers', {}) or {}))
            except Exception:
                pass

        if 'Authorization' not in headers and self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'

        return headers

    def get_collections(self) -> List[Dict[str, Any]]:
        """Return list of NASA EarthData dataset categories.
        
        Returns:
            List of collection dicts with id, title, dataset_count
        """
        cols: List[Dict[str, Any]] = []
        
        # Load catalog
        catalog = self._load_catalog()
        if catalog is None:
            logger.warning('NASA EarthData: catalog not loaded')
            return cols

        # pandas DataFrame path
        if PANDAS_AVAILABLE and hasattr(catalog, 'empty'):
            if catalog.empty:
                logger.warning('NASA EarthData: catalog not loaded')
                return cols

            total_count = len(catalog)
            if 'Category' in catalog.columns:
                categories = catalog['Category'].value_counts().to_dict()
                for category, count in categories.items():
                    if pd.notna(category):
                        cols.append({
                            'id': str(category),
                            'title': str(category),
                            'dataset_count': count
                        })
        else:
            # csv rows path
            if not isinstance(catalog, list) or not catalog:
                logger.warning('NASA EarthData: catalog not loaded')
                return cols

            total_count = len(catalog)
            categories_count: Dict[str, int] = {}
            for row in catalog:
                category = str(row.get('Category', '') or '').strip()
                if not category:
                    continue
                categories_count[category] = categories_count.get(category, 0) + 1
            for category, count in categories_count.items():
                cols.append({
                    'id': category,
                    'title': category,
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
            logger.info('NASA EarthData: attempting lazy authentication before search')
            if not self.authenticate(verify=True):
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
            catalog = self._load_catalog()
            if catalog is not None:
                collection_match = self._catalog_find_first_shortname(catalog, query)
                if collection_match:
                    collection = collection_match
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
                href_lower = link.lower()
                asset_type = 'application/octet-stream'
                if href_lower.endswith(('.tif', '.tiff')):
                    asset_type = 'image/tiff; application=geotiff'
                assets[asset_key] = {
                    'href': link,
                    'type': asset_type,
                    'title': link.split('/')[-1] if '/' in link else link
                }

            # Prefer an explicit `visual` asset when a TIFF/COG is available,
            # so the generic preview path can behave like the other STAC connectors.
            if cog_links:
                assets['visual'] = {
                    'href': cog_links[0],
                    'type': 'image/tiff; application=geotiff',
                    'roles': ['visual'],
                    'title': cog_links[0].split('/')[-1] if '/' in cog_links[0] else cog_links[0],
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
                    'auth_required': True,
                    'auth_source': self._auth_source,
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
            for link in data_links:
                if link.lower().endswith(('.tif', '.tiff')):
                    return link
            if data_links:
                return data_links[0]
            
            # Fallback to assets
            assets = result.get('assets', {})
            if 'visual' in assets:
                return assets['visual'].get('href')
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
