"""
Proxy Detection and Configuration for KADAS Altair Plugin

⚠️ DEPRECATED - This module is no longer used by the plugin ⚠️

The KADAS Altair plugin now relies on KADAS's built-in proxy handling,
which uses QgsNetworkAccessManager::instance()->setupDefaultProxyAndCache().

KADAS automatically handles:
- System proxy detection
- GDAL proxy configuration via environment variables
- SSL certificate handling

This module is kept for reference but is not initialized by the plugin.

Historical implementation was based on swisstopo topo-rapidmapping proxy_handler.py
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

# ============================================================================
# OpenSSL 3.0 Legacy Provider Support
# ============================================================================
# Configure OpenSSL legacy provider if needed (must be done early)
def _configure_openssl_legacy():
    """Enable OpenSSL 3.0 legacy provider for proxy/VPN environments"""
    try:
        import ssl
        if hasattr(ssl, 'OPENSSL_VERSION'):
            version = ssl.OPENSSL_VERSION
            logger.info(f"Detected OpenSSL version: {version}")
            
            # Check if OpenSSL 3.0+
            if '3.0' in version or '3.1' in version or '3.2' in version:
                # Try to enable legacy provider via environment
                if 'OPENSSL_CONF' not in os.environ:
                    plugin_dir = Path(__file__).parent.parent
                    openssl_conf = plugin_dir / "openssl.cnf"
                    if openssl_conf.exists():
                        os.environ['OPENSSL_CONF'] = str(openssl_conf)
                        logger.info(f"OpenSSL legacy provider configured: {openssl_conf}")
                    else:
                        logger.warning("OpenSSL 3.0 detected but openssl.cnf not found")
                        logger.warning("This may cause issues with proxy/VPN SSL inspection")
    except Exception as e:
        logger.debug(f"OpenSSL configuration skipped: {e}")

# Call at module import time
_configure_openssl_legacy()

try:
    import requests
    import urllib3
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Check if SSL module is available
HAS_SSL = True
try:
    import ssl
except ImportError:
    HAS_SSL = False

logger = logging.getLogger(__name__)

# ============================================================================
# GLOBAL PROXY CONFIGURATION
# ============================================================================
PROXY_CONFIG = {
    'enabled': False,
    'proxies': None,
    'session': None,
    'verify_ssl': True,
    'active_proxy': None,
    'initialized': False,
    'is_vpn': False
}

# Default proxy configuration
DEFAULT_PROXY_CONFIG = {
    'proxies': [
        {
            'name': 'Default',
            'url': 'http://proxy.admin.ch:8080',
            'enabled': True
        }
    ],
    'test_url': 'https://data.geo.admin.ch/browser/index.html',
    'timeout': 5,
    'disable_ssl_warnings': True
}

# Configuration file path (in plugin directory)
def get_config_path():
    """Get proxy configuration file path"""
    plugin_dir = Path(__file__).parent.parent
    secrets_dir = plugin_dir / "secrets"
    secrets_dir.mkdir(exist_ok=True)
    return secrets_dir / "proxy_config.json"


def load_proxy_config() -> Dict:
    """
    Load proxy configuration from JSON file.
    
    Returns:
        Dict: Proxy configuration or default config
    """
    config_path = get_config_path()
    
    if not config_path.exists():
        logger.info(f"  ℹ No proxy config found: {config_path}")
        logger.info(f"  ℹ Using default configuration")
        return DEFAULT_PROXY_CONFIG
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logger.info(f"  ✓ Proxy config loaded: {config_path}")
        return config
    except Exception as e:
        logger.warning(f"  ⚠ Error loading proxy config: {e}")
        logger.info(f"  ℹ Using default configuration")
        return DEFAULT_PROXY_CONFIG


def get_enabled_proxies(config: Dict) -> List[Dict]:
    """
    Filter enabled proxies from configuration.
    
    Args:
        config: Proxy configuration
        
    Returns:
        List of enabled proxies
    """
    proxies = config.get('proxies', [])
    enabled = [p for p in proxies if p.get('enabled', True)]
    return enabled


def test_connection(
    test_url: str,
    proxies: Optional[Dict] = None,
    verify_ssl: bool = True,
    timeout: int = 5
) -> bool:
    """
    Test a connection (direct or via proxy).
    
    Args:
        test_url: Test URL
        proxies: Proxy dictionary or None for direct connection
        verify_ssl: Enable SSL verification
        timeout: Timeout in seconds
        
    Returns:
        True if connection successful
    """
    if not HAS_REQUESTS:
        logger.warning("requests library not available")
        return False
        
    try:
        response = requests.get(
            test_url,
            proxies=proxies,
            verify=verify_ssl,
            timeout=timeout
        )
        return response.status_code == 200
    except Exception:
        return False


def detect_vpn_connection(proxies: Optional[Dict] = None, test_urls: List[str] = None) -> bool:
    """
    Try to detect if a VPN connection is active.
    
    Heuristic: If connection works with proxy but SSL verification
    must be disabled, VPN with SSL inspection is likely active.
    
    This tests multiple URLs - if ANY has SSL problems, it's VPN.
    
    Args:
        proxies: Proxy dictionary
        test_urls: URLs to test (default: data.geo.admin.ch + sys-data.int.bgdi.ch)
        
    Returns:
        True if VPN suspected
    """
    if test_urls is None:
        test_urls = [
            'https://data.geo.admin.ch/browser/index.html',
            'https://sys-data.int.bgdi.ch/api/stac/v0.9/'
        ]
    
    if proxies:
        # Test multiple URLs - if ANY has SSL problems, it's VPN
        for test_url in test_urls:
            # Test 1: With proxy and SSL verification
            works_with_ssl = test_connection(test_url, proxies=proxies, verify_ssl=True, timeout=3)
            
            # Test 2: With proxy without SSL verification
            works_without_ssl = test_connection(test_url, proxies=proxies, verify_ssl=False, timeout=3)
            
            # If it only works without SSL -> VPN with SSL-Inspection
            if works_without_ssl and not works_with_ssl:
                logger.info(f"  ℹ VPN connection with SSL inspection detected (tested with {test_url})")
                logger.info("  ℹ SSL-Handling will be adjusted")
                return True
    
    return False


def detect_proxy_requirement() -> Dict:
    """
    Automatically detect if a proxy is required.
    
    Tests in the following order:
    1. Direct connection
    2. All configured proxies (in order)
    
    Returns:
        Dict: Proxy configuration with keys:
              - enabled: Proxy enabled
              - proxies: Proxy dictionary for requests
              - session: Configured session
              - verify_ssl: SSL verification active
              - active_proxy: Name of active proxy
              - initialized: True (marked as initialized)
              - is_vpn: True if VPN detected
    
    Raises:
        ConnectionError: If no connection possible
    """
    if not HAS_REQUESTS:
        logger.warning("requests library not available, skipping proxy detection")
        # Return minimal config without session
        return {
            'enabled': False,
            'proxies': None,
            'session': None,
            'verify_ssl': True,
            'active_proxy': None,
            'initialized': True,
            'is_vpn': False
        }
    
    # Check SSL module availability
    if not HAS_SSL:
        logger.warning("⚠️  SSL module not available in Python environment")
        logger.warning("   This is common in embedded Python (e.g., KADAS/QGIS)")
        logger.warning("   Creating session with SSL verification DISABLED")
        session = requests.Session()
        session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return {
            'enabled': False,
            'proxies': None,
            'session': session,
            'verify_ssl': False,
            'active_proxy': None,
            'initialized': True,
            'is_vpn': False  # Can't detect VPN without SSL
        }
    
    logger.info("Testing internet connectivity...")
    
    config = load_proxy_config()
    test_url = config.get('test_url', DEFAULT_PROXY_CONFIG['test_url'])
    timeout = config.get('timeout', DEFAULT_PROXY_CONFIG['timeout'])
    disable_ssl_warnings = config.get('disable_ssl_warnings', True)
    
    if disable_ssl_warnings:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # Test 1: Direct connection
    logger.info(f"  [1/N] Testing direct connection to {test_url}...")
    if test_connection(test_url, proxies=None, verify_ssl=True, timeout=timeout):
        logger.info("  ✓ Direct internet connection available (no proxy needed)")
        session = requests.Session()
        session.verify = True
        return {
            'enabled': False,
            'proxies': None,
            'session': session,
            'verify_ssl': True,
            'active_proxy': None,
            'initialized': True,
            'is_vpn': False
        }
    else:
        logger.info("  ✗ Direct connection failed")
    
    # Test 2: All configured proxies
    enabled_proxies = get_enabled_proxies(config)
    
    if not enabled_proxies:
        logger.error("  ✗ No proxies configured or enabled")
        raise ConnectionError(
            "No internet connection possible.\n"
            f"Direct connection to {test_url} failed.\n"
            f"No proxies enabled in {get_config_path()}.\n"
            "Please check network settings or proxy config."
        )
    
    for idx, proxy_info in enumerate(enabled_proxies, 2):
        proxy_name = proxy_info.get('name', 'Unknown')
        proxy_url = proxy_info.get('url')
        
        if not proxy_url:
            logger.warning(f"  ⚠ Proxy '{proxy_name}': No URL configured")
            continue
        
        logger.info(f"  [{idx}/{len(enabled_proxies)+1}] Testing proxy '{proxy_name}': {proxy_url}")
        
        proxies = {
            "http": proxy_url,
            "https": proxy_url
        }
        
        # Test with SSL verification (for normal corporate networks without VPN)
        works_with_ssl = test_connection(test_url, proxies=proxies, verify_ssl=True, timeout=timeout)
        
        # Test without SSL verification (for VPN with SSL inspection)
        works_without_ssl = test_connection(test_url, proxies=proxies, verify_ssl=False, timeout=timeout)
        
        if works_with_ssl or works_without_ssl:
            # Detect if VPN is active (also test if first URL was SSL-ok)
            # Additionally test the STAC server URL
            is_vpn = detect_vpn_connection(proxies, test_urls=[
                test_url,
                'https://sys-data.int.bgdi.ch/api/stac/v0.9/'
            ])
            
            # If VPN detected OR SSL verification fails -> disable SSL
            use_ssl = works_with_ssl and not is_vpn
            
            if use_ssl:
                logger.info(f"  ✓ Connection via proxy '{proxy_name}' successful (with SSL verification)")
            else:
                logger.warning(f"  ⚠ Connection via proxy '{proxy_name}' successful (SSL verification disabled)")
                if is_vpn:
                    logger.warning("  ⚠ VPN connection detected - SSL handling will be adjusted")
            
            session = requests.Session()
            session.proxies.update(proxies)
            session.verify = use_ssl
            
            return {
                'enabled': True,
                'proxies': proxies,
                'session': session,
                'verify_ssl': use_ssl,
                'active_proxy': proxy_name,
                'initialized': True,
                'is_vpn': is_vpn
            }
        else:
            logger.info(f"  ✗ Proxy '{proxy_name}' failed")
    
    # All tests failed
    logger.error("  ✗ No internet connection possible")
    raise ConnectionError(
        "No internet connection possible.\n"
        f"Tried: Direct connection + {len(enabled_proxies)} proxy(s)\n"
        f"Test URL: {test_url}\n"
        f"Proxy config: {get_config_path()}\n"
        "Please check network settings."
    )


def initialize_proxy():
    """
    Initialize proxy configuration and store in PROXY_CONFIG.
    
    This function:
    1. Checks if already initialized (if yes, skips tests)
    2. Performs proxy tests
    3. Stores results in global PROXY_CONFIG
    
    Should be called at program startup.
    
    Raises:
        ConnectionError: If no internet connection possible
    """
    global PROXY_CONFIG
    
    # ========================================================================
    # CHECK IF ALREADY INITIALIZED
    # ========================================================================
    if PROXY_CONFIG.get('initialized', False):
        logger.info("ℹ️  Proxy already initialized, using stored settings")
        logger.info("=" * 70)
        if PROXY_CONFIG['enabled']:
            logger.info("Proxy configuration:")
            logger.info(f"  Active proxy: {PROXY_CONFIG['active_proxy']}")
            logger.info(f"  Proxy URL: {PROXY_CONFIG['proxies']['http']}")
            logger.info(f"  SSL verification: {'Disabled' if not PROXY_CONFIG['verify_ssl'] else 'Enabled'}")
            if PROXY_CONFIG.get('is_vpn'):
                logger.info(f"  VPN connection: Detected (SSL handling adjusted)")
        else:
            logger.info("No proxy configuration required")
        logger.info("=" * 70)
        return
    
    # ========================================================================
    # PERFORM PROXY TESTS (only on first call)
    # ========================================================================
    logger.info("Internet connectivity test in progress...")
    config = detect_proxy_requirement()
    PROXY_CONFIG.update(config)
    
    logger.info("=" * 70)
    if PROXY_CONFIG['enabled']:
        logger.info("Proxy configuration:")
        logger.info(f"  Active proxy: {PROXY_CONFIG['active_proxy']}")
        logger.info(f"  Proxy URL: {PROXY_CONFIG['proxies']['http']}")
        logger.info(f"  SSL verification: {'Disabled' if not PROXY_CONFIG['verify_ssl'] else 'Enabled'}")
        if PROXY_CONFIG.get('is_vpn'):
            logger.info(f"  VPN connection: Detected (SSL handling adjusted)")
    else:
        logger.info("No proxy configuration required")
    logger.info("=" * 70)


def get_session():
    """
    Return the configured requests Session.
    
    If proxy not yet initialized, initialize_proxy() will be called.
    If initialization fails, creates a fallback session with SSL disabled.
    
    Returns:
        requests.Session: Configured session (with or without proxy)
    """
    global PROXY_CONFIG
    
    if not HAS_REQUESTS:
        logger.warning("requests library not available")
        return None
    
    if not PROXY_CONFIG.get('initialized', False):
        logger.warning("⚠️  Proxy not yet initialized - initializing now...")
        try:
            initialize_proxy()
        except ConnectionError as e:
            logger.warning(f"⚠️  Proxy initialization failed: {e}")
            logger.warning("   Creating fallback session with SSL verification DISABLED")
            # Create fallback session when network is completely unavailable
            session = requests.Session()
            session.verify = False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            PROXY_CONFIG.update({
                'enabled': False,
                'proxies': None,
                'session': session,
                'verify_ssl': False,
                'active_proxy': None,
                'initialized': True,
                'is_vpn': False
            })
    
    if PROXY_CONFIG['session'] is None:
        # Last resort fallback - should never happen but be defensive
        logger.error("⚠️  Session is None, creating emergency fallback session")
        session = requests.Session()
        session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        PROXY_CONFIG['session'] = session
    
    return PROXY_CONFIG['session']


def get_proxy_config() -> Dict:
    """
    Return the current proxy configuration.
    
    If proxy not yet initialized, initialize_proxy() will be called.
    
    Returns:
        Dict: Proxy configuration
    """
    global PROXY_CONFIG
    
    if not PROXY_CONFIG.get('initialized', False):
        logger.warning("⚠️  Proxy not yet initialized - initializing now...")
        initialize_proxy()
    
    return PROXY_CONFIG.copy()


def is_proxy_enabled() -> bool:
    """
    Check if proxy is enabled.
    
    Returns:
        bool: True if proxy enabled
    """
    global PROXY_CONFIG
    
    if not PROXY_CONFIG.get('initialized', False):
        logger.warning("⚠️  Proxy not yet initialized - initializing now...")
        initialize_proxy()
    
    return PROXY_CONFIG['enabled']


def is_vpn_detected() -> bool:
    """
    Check if VPN connection was detected.
    
    Returns:
        bool: True if VPN detected
    """
    config = get_proxy_config()
    return config.get('is_vpn', False)


def get_proxies_dict() -> Optional[Dict]:
    """
    Return the proxies dictionary for requests.get/post.
    
    Useful for direct requests calls outside a session.
    
    Returns:
        Optional[Dict]: Proxies dictionary or None if no proxy
    """
    config = get_proxy_config()
    return config.get('proxies')


def get_verify_ssl() -> bool:
    """
    Return whether SSL verification is enabled.
    
    Returns:
        bool: True if SSL verification active
    """
    config = get_proxy_config()
    return config.get('verify_ssl', True)


def create_insecure_session():
    """
    Create a requests session with SSL verification completely disabled.
    
    This is a fallback for environments where:
    - SSL module is not available (embedded Python)
    - VPN with SSL inspection is active
    - Network tests fail but connectivity might still work
    
    Use this when you need to bypass all SSL checks and just try to connect.
    
    Returns:
        requests.Session: Session with SSL disabled and warnings suppressed
    """
    if not HAS_REQUESTS:
        logger.warning("requests library not available")
        return None
    
    logger.debug("Creating insecure session (SSL verification disabled)")
    session = requests.Session()
    session.verify = False
    
    # Suppress SSL warnings
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except:
        pass  # Ignore if urllib3 not available
    
    return session
