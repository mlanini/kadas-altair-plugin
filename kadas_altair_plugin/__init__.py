"""
KADAS Altair EO Data Plugin - Minimal Production Version
"""

# ============================================================================
# OpenSSL 3.0 Legacy Provider Configuration
# ============================================================================
# Enable OpenSSL legacy provider for proxy/VPN environments
# This is required for KADAS Albireo 2 with OpenSSL 3.0
import os
import sys

# Configure OpenSSL to load legacy provider (for old crypto algorithms)
# This must happen BEFORE any SSL/crypto library imports
_openssl_conf = os.environ.get('OPENSSL_CONF')
if not _openssl_conf:
    # Try to enable legacy provider via environment variable
    # This works for OpenSSL 3.0+ in environments with proxy/VPN SSL inspection
    os.environ['OPENSSL_CONF'] = os.path.join(os.path.dirname(__file__), 'openssl.cnf')

# Alternative: Try to configure OpenSSL programmatically
try:
    import ssl
    # For Python 3.10+ with OpenSSL 3.0
    if hasattr(ssl, 'OPENSSL_VERSION') and '3.0' in ssl.OPENSSL_VERSION:
        # Enable legacy algorithms support
        # Note: This requires OpenSSL to be built with legacy provider
        pass  # Environment variable approach is preferred
except ImportError:
    pass  # SSL module not available in this Python

# ============================================================================
# Load Bundled Dependencies
# ============================================================================
from pathlib import Path

_lib_dir = Path(__file__).parent / "lib"
if _lib_dir.exists():
    # Insert at the beginning to prioritize bundled dependencies
    sys.path.insert(0, str(_lib_dir))
    import logging
    logger = logging.getLogger('kadas_altair')
    logger.info(f"Loaded bundled dependencies from: {_lib_dir}")
else:
    # Production package must have lib/ directory
    import logging
    logger = logging.getLogger('kadas_altair')
    logger.warning("Bundled dependencies not found - plugin may not work correctly")

def classFactory(iface):
    """Load KadasAltair class from plugin.py"""
    from .plugin import KadasAltair
    return KadasAltair(iface)
