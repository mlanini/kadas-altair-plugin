import logging
from ..logger import get_logger

logger = get_logger('connectors.base')


class ConnectorBase:
    """Abstract base for satellite data service connectors.

    Methods to implement:
    - authenticate(credentials)
    - search(query) -> list of results
    - get_tile_url(result, z, x, y) -> str

    Attributes:
    - timeout_auth: default timeout for authentication requests (seconds)
    - timeout_search: default timeout for search requests (seconds)
    """

    timeout_auth: float = 10.0
    timeout_search: float = 15.0

    def __init__(self):
        """Initialize connector with proxy support"""
        self._session = None
        self._proxies = None
        self._verify_ssl = True
        self._init_proxy()

    def _init_proxy(self):
        """Initialize proxy configuration (deprecated - use QgsNetworkAccessManager instead)
        
        Note: Modern connectors should use QgsNetworkAccessManager.instance() directly
        for SSL/proxy handling instead of requests library.
        """
        try:
            from ..utilities.proxy_handler import get_session, get_proxies_dict, get_verify_ssl
            self._session = get_session()
            self._proxies = get_proxies_dict()
            self._verify_ssl = get_verify_ssl()
            logger.info("Connector initialized with proxy configuration (legacy mode)")
        except Exception as e:
            logger.warning(f"Failed to initialize proxy for connector: {e}")
            logger.warning("Connector will use direct connection or QGIS network manager")
            self._session = None

    def get_session(self):
        """Get configured requests session with proxy support (deprecated)
        
        Note: This method is deprecated. Modern connectors should use
        QgsNetworkAccessManager.instance() for better SSL/proxy support.
        """
        if self._session is None:
            self._init_proxy()
        return self._session

    def authenticate(self, credentials: dict) -> bool:
        raise NotImplementedError()

    def search(self, query: str) -> list:
        raise NotImplementedError()

    def get_tile_url(self, result: dict, z: int, x: int, y: int) -> str:
        raise NotImplementedError()

