"""Connector Manager - Multi-Source Middleware Architecture

This module provides a unified interface for managing multiple data source connectors.
It decouples the plugin UI from specific connector implementations and provides
a standardized API for searching, filtering, and accessing imagery data.

Architecture:
- ConnectorManager: Central registry and dispatcher for all connectors
- Unified search interface across all sources
- Standardized result format (STAC-like items)
- Automatic connector selection and routing
- Connection pooling and caching
"""
import logging
from typing import Optional, List, Dict, Any, Tuple, Type
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from ..logger import get_logger

logger = get_logger('connectors.manager')


class ConnectorType(Enum):
    """Supported connector types"""
    AWS_STAC = "aws_stac"
    COPERNICUS = "copernicus"
    ONEATLAS = "oneatlas"
    PLANET = "planet"
    VANTOR = "vantor"
    ICEYE_STAC = "iceye_stac"
    UMBRA_STAC = "umbra_stac"
    CAPELLA_STAC = "capella_stac"
    GEE = "gee"
    NASA_EARTHDATA = "nasa_earthdata"


class ConnectorCapability(Enum):
    """Capabilities that connectors may support"""
    BBOX_SEARCH = "bbox_search"
    DATE_RANGE = "date_range"
    CLOUD_COVER = "cloud_cover"
    TEXT_SEARCH = "text_search"
    COLLECTIONS = "collections"
    PAGINATION = "pagination"
    COG_SUPPORT = "cog_support"  # Cloud Optimized GeoTIFF support
    AUTHENTICATION = "authentication"  # Requires authentication
    COMMERCIAL = "commercial"  # Commercial data source
    PREVIEW = "preview"
    DOWNLOAD = "download"
    STREAMING = "streaming"


class ConnectorManager:
    """Central manager for all data source connectors
    
    Provides:
    - Connector registration and discovery
    - Unified search interface
    - Result standardization
    - Connection management
    - Capability negotiation
    """
    
    def __init__(self):
        """Initialize connector manager"""
        self._connectors: Dict[str, Any] = {}
        self._active_connector: Optional[str] = None
        self._capabilities_cache: Dict[str, List[ConnectorCapability]] = {}
        
        logger.info("ConnectorManager initialized")
    
    def register_connector(
        self,
        connector_id: str,
        connector_instance: Any,
        display_name: str,
        description: str = "",
        capabilities: Optional[List[ConnectorCapability]] = None
    ) -> bool:
        """Register a connector
        
        Args:
            connector_id: Unique identifier for the connector
            connector_instance: Instance of the connector class
            display_name: Human-readable name for UI
            description: Connector description
            capabilities: List of supported capabilities
            
        Returns:
            bool: True if registration successful
        """
        try:
            self._connectors[connector_id] = {
                'instance': connector_instance,
                'display_name': display_name,
                'description': description,
                'capabilities': capabilities or [],
                'authenticated': False
            }
            
            logger.info(f"Registered connector: {connector_id} ({display_name})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register connector {connector_id}: {e}")
            return False
    
    def unregister_connector(self, connector_id: str) -> bool:
        """Unregister a connector
        
        Args:
            connector_id: Connector to unregister
            
        Returns:
            bool: True if unregistered
        """
        if connector_id in self._connectors:
            del self._connectors[connector_id]
            logger.info(f"Unregistered connector: {connector_id}")
            return True
        return False
    
    def get_available_connectors(self) -> List[Dict[str, Any]]:
        """Get list of all registered connectors
        
        Returns:
            List of connector info dicts with id, display_name, description, capabilities
        """
        connectors = []
        
        for connector_id, info in self._connectors.items():
            connectors.append({
                'id': connector_id,
                'display_name': info['display_name'],
                'description': info['description'],
                'capabilities': [c.value for c in info['capabilities']],
                'authenticated': info['authenticated']
            })
        
        return connectors
    
    def set_active_connector(self, connector_id: str) -> bool:
        """Set the active connector for searches
        
        Args:
            connector_id: Connector to activate
            
        Returns:
            bool: True if activated
        """
        if connector_id not in self._connectors:
            logger.error(f"Connector not found: {connector_id}")
            return False
        
        self._active_connector = connector_id
        logger.info(f"Active connector set to: {connector_id}")
        return True
    
    def get_active_connector(self) -> Optional[Dict[str, Any]]:
        """Get the currently active connector
        
        Returns:
            Dict with connector info or None
        """
        if not self._active_connector or self._active_connector not in self._connectors:
            return None
        
        info = self._connectors[self._active_connector]
        return {
            'id': self._active_connector,
            'display_name': info['display_name'],
            'instance': info['instance'],
            'capabilities': info['capabilities'],
            'authenticated': info['authenticated']
        }
    
    def authenticate_connector(
        self,
        connector_id: str,
        credentials: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> bool:
        """Authenticate a specific connector
        
        Args:
            connector_id: Connector to authenticate
            credentials: Authentication credentials (if needed)
            **kwargs: Additional connector-specific parameters
            
        Returns:
            bool: True if authentication successful
        """
        if connector_id not in self._connectors:
            logger.error(f"Connector not found: {connector_id}")
            return False
        
        try:
            connector_info = self._connectors[connector_id]
            instance = connector_info['instance']
            
            # Call connector's authenticate method
            if credentials:
                success = instance.authenticate(credentials=credentials, **kwargs)
            else:
                success = instance.authenticate(**kwargs)
            
            # Update authentication status
            connector_info['authenticated'] = success
            
            if success:
                logger.info(f"Connector authenticated: {connector_id}")
            else:
                logger.warning(f"Connector authentication failed: {connector_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error authenticating connector {connector_id}: {e}", exc_info=True)
            return False
    
    def search(
        self,
        bbox: Optional[List[float]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_cloud_cover: Optional[float] = None,
        collection: Optional[str] = None,
        text_query: Optional[str] = None,
        limit: int = 100,
        connector_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Unified search interface across all connectors
        
        Args:
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            max_cloud_cover: Maximum cloud cover percentage (0-100)
            collection: Collection/dataset ID
            text_query: Text search query
            limit: Maximum results to return
            connector_id: Specific connector to use (default: active connector)
            
        Returns:
            Tuple of (items, next_token)
            - items: List of standardized result items
            - next_token: Pagination token or error message
        """
        # Determine which connector to use
        target_connector = connector_id or self._active_connector
        
        if not target_connector or target_connector not in self._connectors:
            logger.error("No active connector or connector not found")
            return [], "No active connector"
        
        connector_info = self._connectors[target_connector]
        
        # Check authentication only if connector requires it
        capabilities = connector_info.get('capabilities', [])
        if ConnectorCapability.AUTHENTICATION in capabilities:
            if not connector_info['authenticated']:
                logger.warning(f"Connector not authenticated: {target_connector}")
                return [], "Connector not authenticated"
        
        instance = connector_info['instance']
        
        try:
            logger.info(f"Executing search on connector: {target_connector}")
            logger.debug(f"Search params: bbox={bbox}, dates={start_date} to {end_date}, "
                        f"cloud={max_cloud_cover}, collection={collection}, limit={limit}")
            
            # Call connector's search method
            # Different connectors may have different signatures
            items, token = self._execute_connector_search(
                instance=instance,
                bbox=bbox,
                start_date=start_date,
                end_date=end_date,
                max_cloud_cover=max_cloud_cover,
                collection=collection,
                text_query=text_query,
                limit=limit
            )
            
            logger.info(f"Raw search results from {target_connector}: {len(items)} items")
            if items:
                logger.debug(f"First item type: {type(items[0])}, keys: {list(items[0].keys())[:10]}")
            
            # Standardize results
            standardized_items = self._standardize_results(items, target_connector)
            
            logger.info(f"Search completed: {len(standardized_items)} items from {target_connector}")
            return standardized_items, token
            
        except Exception as e:
            logger.error(f"Search failed on connector {target_connector}: {e}", exc_info=True)
            return [], f"Search error: {str(e)}"
    
    def _execute_connector_search(
        self,
        instance: Any,
        bbox: Optional[List[float]],
        start_date: Optional[str],
        end_date: Optional[str],
        max_cloud_cover: Optional[float],
        collection: Optional[str],
        text_query: Optional[str],
        limit: int
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Execute search on a specific connector instance
        
        Handles different connector method signatures
        """
        # Detect connector type by class name
        connector_class = instance.__class__.__name__
        
        # ICEYE STAC signature: search(query, bbox, start_date, end_date, collections, limit, **kwargs)
        if connector_class == 'IceyeStacConnector':
            try:
                logger.debug(f"Using ICEYE signature for {connector_class}")
                collections_list = [collection] if collection else None
                results = instance.search(
                    query=text_query or "",
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    collections=collections_list,
                    limit=limit
                )
                return results, None
            except Exception as e:
                logger.error(f"ICEYE search failed: {e}", exc_info=True)
                return [], None
        
        # Umbra/Capella dict signature: search(query: dict)
        if connector_class in ['UmbraSTACConnector', 'CapellaSTACConnector']:
            try:
                logger.debug(f"Using dict signature for {connector_class}")
                query_dict = {
                    'limit': limit
                }
                if bbox:
                    query_dict['bbox'] = bbox
                if start_date and end_date:
                    query_dict['datetime'] = f"{start_date}/{end_date}"
                elif start_date:
                    query_dict['datetime'] = f"{start_date}/.."
                elif end_date:
                    query_dict['datetime'] = f"../{end_date}"
                
                # Capella-specific: map collection to product_type or instrument_mode
                if connector_class == 'CapellaSTACConnector' and collection:
                    # Try to detect if collection is a product_type or instrument_mode
                    if collection.upper() in ['GEO', 'GEC', 'SLC', 'SICD', 'SIDD', 'CPHD']:
                        query_dict['product_type'] = collection.upper()
                    else:
                        query_dict['instrument_mode'] = collection
                
                # Umbra-specific: map collection to year or month
                if connector_class == 'UmbraSTACConnector' and collection:
                    if len(collection) == 4 and collection.isdigit():
                        query_dict['year'] = collection
                    elif len(collection) == 7 and collection[4] == '-':
                        query_dict['month'] = collection
                
                results = instance.search(query_dict)
                return results, None
            except Exception as e:
                logger.error(f"{connector_class} search failed: {e}", exc_info=True)
                return [], None
        
        # Try standard search signature (AWS STAC)
        try:
            logger.debug(f"Trying standard search signature for {connector_class}")
            result = instance.search(
                bbox=bbox or [],
                start_date=start_date or "",
                end_date=end_date or "",
                max_cloud_cover=max_cloud_cover,
                collection=collection,
                limit=limit
            )
            logger.debug(f"Standard search returned type: {type(result)}")
            
            # Handle both tuple and list returns
            if isinstance(result, tuple) and len(result) == 2:
                logger.debug(f"Got tuple result: ({len(result[0])} items, {result[1]})")
                return result
            elif isinstance(result, list):
                logger.debug(f"Got list result: {len(result)} items, wrapping in tuple")
                return result, None
            else:
                logger.warning(f"Unexpected result type: {type(result)}")
                return result, None
        except TypeError as e:
            logger.debug(f"Standard signature failed: {e}")
            pass
        
        # Copernicus connector signature: search(query, **kwargs)
        if connector_class == 'CopernicusConnector':
            try:
                logger.debug(f"Using Copernicus signature for {connector_class}")
                results = instance.search(
                    query="",  # Copernicus doesn't use text query, only filters
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=int(max_cloud_cover) if max_cloud_cover else 100,
                    collection=collection or 'sentinel-2-l2a',  # Default to S2 L2A
                    limit=limit
                )
                logger.debug(f"Copernicus search returned: {len(results)} items")
                return results, None
            except Exception as e:
                logger.error(f"Copernicus search failed: {e}", exc_info=True)
                return [], None
        
        # Try alternative signatures (Planet, etc.)
        try:
            # Generic kwargs signature
            if bbox and start_date and end_date:
                results = instance.search(
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=int(max_cloud_cover) if max_cloud_cover else 100,
                    collection=collection
                )
                return results, None
        except (TypeError, AttributeError):
            pass
        
        # Try simple text query signature (legacy connectors)
        try:
            results = instance.search(query=text_query or "")
            return results, None
        except (TypeError, AttributeError):
            pass
        
        logger.warning(f"Could not match search signature for connector: {connector_class}")
        return [], None
    
    def _standardize_results(
        self,
        items: List[Dict[str, Any]],
        connector_id: str
    ) -> List[Dict[str, Any]]:
        """Standardize results from different connectors to common format
        
        Args:
            items: Raw items from connector
            connector_id: Source connector ID
            
        Returns:
            List of standardized items in STAC-like format
        """
        standardized = []
        
        for item in items:
            # Check if already in STAC format
            if 'type' in item and item['type'] == 'Feature':
                # Already STAC-like, just add source
                item['_source'] = connector_id
                
                # Ensure stac_feature contains links for URL resolution
                if 'stac_feature' in item and isinstance(item['stac_feature'], dict):
                    # Preserve original stac_feature links
                    stac_feature = item['stac_feature']
                    if 'links' not in item:
                        item['links'] = stac_feature.get('links', [])
                else:
                    # Create stac_feature from top-level fields
                    item['stac_feature'] = {
                        'links': item.get('links', []),
                        'assets': item.get('assets', {}),
                        'properties': item.get('properties', {})
                    }
                
                standardized.append(item)
                continue
            
            # Convert to STAC-like format
            stac_item = self._convert_to_stac_format(item, connector_id)
            if stac_item:
                standardized.append(stac_item)
        
        return standardized
    
    def _convert_to_stac_format(
        self,
        item: Dict[str, Any],
        connector_id: str
    ) -> Optional[Dict[str, Any]]:
        """Convert connector-specific item to STAC-like format
        
        Args:
            item: Raw item from connector
            connector_id: Source connector
            
        Returns:
            STAC-like item or None
        """
        try:
            # Extract common fields
            item_id = item.get('id', item.get('title', 'unknown'))
            bbox = item.get('bbox')
            geometry = item.get('geometry')
            
            # Build STAC item
            stac_item = {
                'type': 'Feature',
                'id': item_id,
                'geometry': geometry,
                'bbox': bbox,
                'properties': item.get('properties', {}),
                'assets': item.get('assets', {}),
                'links': item.get('links', []),  # Preserve STAC links for URL resolution
                '_source': connector_id,
                '_raw': item  # Keep original for debugging
            }
            
            # Add stac_feature for compatibility with Load COG URL resolution
            stac_item['stac_feature'] = {
                'links': item.get('links', []),
                'assets': item.get('assets', {}),
                'properties': item.get('properties', {})
            }
            
            return stac_item
            
        except Exception as e:
            logger.warning(f"Could not convert item to STAC format: {e}")
            return None
    
    def get_collections(
        self,
        connector_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get collections from a connector
        
        Args:
            connector_id: Connector to query (default: active)
            
        Returns:
            List of collections
        """
        target_connector = connector_id or self._active_connector
        
        if not target_connector or target_connector not in self._connectors:
            logger.error("No active connector")
            return []
        
        connector_info = self._connectors[target_connector]
        
        if not connector_info['authenticated']:
            logger.warning(f"Connector not authenticated: {target_connector}")
            return []
        
        instance = connector_info['instance']
        
        try:
            # Try to get collections
            if hasattr(instance, 'get_collections'):
                return instance.get_collections()
            else:
                logger.debug(f"Connector {target_connector} does not support collections")
                return []
        except Exception as e:
            logger.error(f"Error getting collections from {target_connector}: {e}")
            return []
    
    def has_capability(
        self,
        capability: ConnectorCapability,
        connector_id: Optional[str] = None
    ) -> bool:
        """Check if connector supports a capability
        
        Args:
            capability: Capability to check
            connector_id: Connector to check (default: active)
            
        Returns:
            bool: True if supported
        """
        target_connector = connector_id or self._active_connector
        
        if not target_connector or target_connector not in self._connectors:
            return False
        
        connector_info = self._connectors[target_connector]
        return capability in connector_info['capabilities']
    
    def get_all_collections(self, use_cache: bool = True) -> List[Dict[str, Any]]:
        """Get collections from ALL registered connectors (OPTIMIZED)
        
        This aggregates collections from every available connector,
        regardless of authentication status. Used for "All Sources" mode.
        
        PERFORMANCE OPTIMIZATIONS:
        - Parallel loading with ThreadPoolExecutor (5 workers)
        - In-memory caching with 5-minute TTL
        - Timeout protection (10s per connector)
        - Graceful error handling
        
        Args:
            use_cache: Whether to use cached collections (default: True)
        
        Returns:
            List[Dict[str, Any]]: Aggregated collections with source metadata
        """
        # Check cache first
        cache_key = '_all_collections_cache'
        cache_timestamp_key = '_all_collections_cache_timestamp'
        cache_ttl = 300  # 5 minutes
        
        if use_cache and hasattr(self, cache_key):
            timestamp = getattr(self, cache_timestamp_key, 0)
            if time.time() - timestamp < cache_ttl:
                cached = getattr(self, cache_key)
                logger.info(f"Using cached collections: {len(cached)} items")
                return cached
        
        all_collections = []
        logger.info("Fetching collections from all registered connectors (parallel mode)")
        
        def _fetch_connector_collections(connector_id: str, connector_info: Dict) -> Tuple[str, List[Dict], Optional[str]]:
            """Fetch collections from a single connector
            
            Returns:
                (connector_id, collections, error_message)
            """
            try:
                instance = connector_info['instance']
                display_name = connector_info['display_name']
                
                # Skip if connector doesn't support collections
                if not hasattr(instance, 'get_collections'):
                    logger.debug(f"Connector {connector_id} does not support collections")
                    return (connector_id, [], None)
                
                # Skip if not authenticated and requires auth
                if ConnectorCapability.AUTHENTICATION in connector_info.get('capabilities', []):
                    if not connector_info.get('authenticated', False):
                        logger.debug(f"Skipping {connector_id}: not authenticated")
                        return (connector_id, [], None)
                
                # Get collections with timing
                start_time = time.time()
                collections = instance.get_collections()
                elapsed = time.time() - start_time
                
                if collections:
                    # Add source metadata to each collection
                    enriched = []
                    for collection in collections:
                        enriched_collection = dict(collection)
                        enriched_collection['_source'] = connector_id
                        enriched_collection['_source_name'] = display_name
                        enriched.append(enriched_collection)
                    
                    logger.info(f"✓ Loaded {len(collections)} collections from {connector_id} ({elapsed:.2f}s)")
                    return (connector_id, enriched, None)
                else:
                    logger.debug(f"No collections from {connector_id}")
                    return (connector_id, [], None)
                
            except Exception as e:
                error_msg = f"Failed to get collections from {connector_id}: {e}"
                logger.warning(error_msg)
                return (connector_id, [], error_msg)
        
        # Parallel execution with ThreadPoolExecutor
        max_workers = 5  # Parallel requests
        timeout_per_connector = 10  # seconds
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_connector = {
                executor.submit(_fetch_connector_collections, conn_id, conn_info): conn_id
                for conn_id, conn_info in self._connectors.items()
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_connector, timeout=timeout_per_connector * len(self._connectors)):
                connector_id = future_to_connector[future]
                try:
                    conn_id, collections, error = future.result(timeout=timeout_per_connector)
                    if collections:
                        all_collections.extend(collections)
                except Exception as e:
                    logger.error(f"Exception fetching {connector_id}: {e}")
        
        logger.info(f"✓ Aggregated {len(all_collections)} collections from all sources")
        
        # Cache results
        setattr(self, cache_key, all_collections)
        setattr(self, cache_timestamp_key, time.time())
        
        return all_collections
    
    def clear_collections_cache(self):
        """Clear the collections cache
        
        Call this when:
        - User authenticates/de-authenticates a connector
        - User manually refreshes collections
        - Configuration changes that affect available collections
        """
        cache_key = '_all_collections_cache'
        cache_timestamp_key = '_all_collections_cache_timestamp'
        
        if hasattr(self, cache_key):
            delattr(self, cache_key)
        if hasattr(self, cache_timestamp_key):
            delattr(self, cache_timestamp_key)
        
        logger.info("Collections cache cleared")
    
    def search_all_sources(
        self,
        bbox: Optional[List[float]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_cloud_cover: Optional[float] = None,
        collection: Optional[str] = None,
        text_query: Optional[str] = None,
        limit: int = 100
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Search across ALL available connectors and aggregate results
        
        This is the "All Sources" search that queries every authenticated
        connector and merges the results.
        
        Args:
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            max_cloud_cover: Maximum cloud cover percentage (0-100)
            collection: Collection/dataset ID (with source prefix if from All Sources)
            text_query: Text search query
            limit: Maximum results PER CONNECTOR
            
        Returns:
            Tuple of (aggregated_items, status_message)
        """
        logger.info("Executing search across ALL sources")
        
        all_results = []
        connectors_searched = []
        connectors_failed = []
        
        # If collection is specified and has source prefix, search only that source
        target_connector = None
        if collection and '::' in collection:
            # Format: "connector_id::collection_id"
            parts = collection.split('::', 1)
            target_connector = parts[0]
            collection = parts[1]
            logger.info(f"Collection has source prefix: {target_connector}::{collection}")
        
        for connector_id, connector_info in self._connectors.items():
            # Skip if we have a target connector and this isn't it
            if target_connector and connector_id != target_connector:
                continue
            
            try:
                instance = connector_info['instance']
                display_name = connector_info['display_name']
                
                # Skip if requires auth and not authenticated
                if ConnectorCapability.AUTHENTICATION in connector_info.get('capabilities', []):
                    if not connector_info.get('authenticated', False):
                        logger.debug(f"Skipping {connector_id}: not authenticated")
                        continue
                
                # Execute search
                logger.info(f"Searching {connector_id}...")
                items, _ = self._execute_connector_search(
                    instance=instance,
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=max_cloud_cover,
                    collection=collection,
                    text_query=text_query,
                    limit=limit
                )
                
                if items:
                    # Standardize and add source metadata
                    standardized = self._standardize_results(items, connector_id)
                    for item in standardized:
                        item['_source'] = connector_id
                        item['_source_name'] = display_name
                    
                    all_results.extend(standardized)
                    connectors_searched.append(display_name)
                    logger.info(f"{connector_id}: {len(standardized)} results")
                else:
                    connectors_searched.append(display_name)
                    logger.debug(f"{connector_id}: 0 results")
                
            except Exception as e:
                logger.warning(f"Search failed on {connector_id}: {e}")
                connectors_failed.append(connector_info['display_name'])
                continue
        
        # Build status message
        status_parts = []
        if connectors_searched:
            status_parts.append(f"Searched: {', '.join(connectors_searched)}")
        if connectors_failed:
            status_parts.append(f"Failed: {', '.join(connectors_failed)}")
        
        status_message = " | ".join(status_parts) if status_parts else "No connectors searched"
        
        logger.info(f"All sources search completed: {len(all_results)} total results from {len(connectors_searched)} connectors")
        
        return all_results, status_message
