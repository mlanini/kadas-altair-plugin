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
from pathlib import Path

# Configure OpenSSL to load legacy provider (for old crypto algorithms)
# This must happen BEFORE any SSL/crypto library imports
_openssl_conf_path = os.path.join(os.path.dirname(__file__), 'openssl.cnf')
if os.path.exists(_openssl_conf_path):
    # Set OpenSSL config only if not already set
    if not os.environ.get('OPENSSL_CONF'):
        os.environ['OPENSSL_CONF'] = _openssl_conf_path

# Configure cryptography to avoid fatal OpenSSL 3 startup failures.
# The fallback must be set before any requests/cryptography import happens.
if not os.environ.get('CRYPTOGRAPHY_OPENSSL_NO_LEGACY'):
    os.environ['CRYPTOGRAPHY_OPENSSL_NO_LEGACY'] = '1'

# Alternative: Try to configure OpenSSL programmatically
try:
    import ssl
    # For Python 3.10+ with OpenSSL 3.0
    if hasattr(ssl, 'OPENSSL_VERSION') and '3.0' in ssl.OPENSSL_VERSION:
        # Environment variable approach is preferred
        pass
except ImportError:
    pass  # SSL module not available in this Python

# ============================================================================
# Load Bundled Dependencies
# ============================================================================
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
    logger.warning(
        "Bundled dependencies not found - plugin may not work correctly"
    )


def classFactory(iface):
    """Load KadasAltair class from plugin.py"""
    from .plugin import KadasAltair
    return KadasAltair(iface)
