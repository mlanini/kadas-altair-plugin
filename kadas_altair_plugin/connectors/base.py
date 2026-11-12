import logging
import os
from urllib.parse import urljoin, urlsplit

try:
    import requests
except Exception:
    requests = None

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
    timeout_search: float = 60.0
    _PREVIEW_ASSET_KEYS = ('thumbnail', 'quicklook', 'overview', 'preview', 'browse')
    _COG_ASSET_PRIORITY = (
        'visual', 'TCI', 'TCI_10m', 'B_TCI',
        'B04_10m', 'B04', 'B03_10m', 'B03',
        'data', 'analytic', 'cog', 'image',
    )
    _COG_MEDIA_TYPES = {
        'image/tiff',
        'image/geotiff',
        'image/jp2',
        'image/vnd.stac.geotiff; cloud-optimized=true',
        'image/x.geotiff',
    }

    def __init__(self):
        """Initialize connector network context."""
        self._logger = logger
        self._session = None
        self._proxies = None
        self._verify_ssl = True
        self._requests_session_error = None
        self._requests_session_warned = False
        self._init_proxy()

    def _create_requests_session(self):
        """Create a requests session with OpenSSL-safe fallbacks.

        Some KADAS/QGIS Python runtimes fail with:
        ``[CRYPTO] unknown error (_ssl.c:4047)``.
        In that case we retry once with conservative env toggles.
        """
        if requests is None:
            self._requests_session_error = 'requests unavailable'
            return None

        req_mod = requests

        def _new_session():
            s = req_mod.Session()
            s.trust_env = True
            return s

        try:
            session = _new_session()
            self._requests_session_error = None
            return session
        except Exception as exc:
            self._requests_session_error = str(exc)

            # OpenSSL fallback for known runtime-specific failures.
            # Keep original values to avoid mutating process env permanently.
            prior_legacy = os.environ.get('CRYPTOGRAPHY_OPENSSL_NO_LEGACY')
            prior_openssl_conf = os.environ.get('OPENSSL_CONF')
            try:
                os.environ.setdefault('CRYPTOGRAPHY_OPENSSL_NO_LEGACY', '1')
                if (
                    prior_openssl_conf
                    and not os.path.exists(prior_openssl_conf)
                ):
                    os.environ.pop('OPENSSL_CONF', None)

                session = _new_session()
                self._requests_session_error = None
                self._logger.info(
                    'Requests session recovered after OpenSSL fallback '
                    '(CRYPTOGRAPHY_OPENSSL_NO_LEGACY/OPENSSL_CONF).'
                )
                return session
            except Exception as retry_exc:
                self._requests_session_error = str(retry_exc)
                return None
            finally:
                if prior_legacy is None:
                    os.environ.pop('CRYPTOGRAPHY_OPENSSL_NO_LEGACY', None)
                else:
                    os.environ['CRYPTOGRAPHY_OPENSSL_NO_LEGACY'] = prior_legacy

                if prior_openssl_conf is None:
                    os.environ.pop('OPENSSL_CONF', None)
                else:
                    os.environ['OPENSSL_CONF'] = prior_openssl_conf

    def _init_proxy(self):
        """Initialize network defaults using KADAS/QGIS settings.

        This avoids the deprecated plugin-local proxy detector and keeps
        connector networking aligned with KADAS global proxy/cache behavior.
        """
        try:
            from qgis.core import QgsNetworkAccessManager
            QgsNetworkAccessManager.instance().setupDefaultProxyAndCache()
            self._logger.info(
                "Connector initialized with KADAS network defaults"
            )
        except Exception as e:
            fallback_logger = getattr(
                self, '_logger', logging.getLogger(__name__)
            )
            fallback_logger.debug(
                "QGIS network manager setup unavailable during "
                f"connector init: {e}"
            )

        try:
            from ..utilities.kadas_network_settings import apply_gdal_proxy_settings
            apply_gdal_proxy_settings()
        except Exception as e:
            self._logger.debug("GDAL proxy settings unavailable: %s", e)

        if requests is None:
            self._session = None
            return

        self._session = self._create_requests_session()
        if self._session is None and not self._requests_session_warned:
            fallback_logger = getattr(
                self, '_logger', logging.getLogger(__name__)
            )
            fallback_logger.warning(
                'Requests backend unavailable; connectors will use '
                'QGIS network '
                f'path where supported. Reason: {self._requests_session_error}'
            )
            self._requests_session_warned = True

    def get_session(self):
        """Get connector HTTP session for requests-backed connectors."""
        if self._session is None:
            self._init_proxy()
            if self._session is None and requests is not None:
                self._session = self._create_requests_session()
                if self._session is None and not self._requests_session_warned:
                    fallback_logger = getattr(
                        self, '_logger', logging.getLogger(__name__)
                    )
                    fallback_logger.warning(
                        'Requests session unavailable in get_session; '
                        f'reason: {self._requests_session_error}'
                    )
                    self._requests_session_warned = True
        return self._session

    def authenticate(self, credentials: dict) -> bool:
        raise NotImplementedError()

    def search(self, query: str) -> list:
        raise NotImplementedError()

    def search_unified(
        self,
        bbox=None,
        start_date=None,
        end_date=None,
        max_cloud_cover=None,
        collection=None,
        text_query=None,
        limit: int = 100
    ) -> tuple:
        """Normalized search entrypoint called by ConnectorManager.

        Default implementation forwards to ``search()`` using the standard
        keyword-argument signature shared by most connectors
        (bbox, start_date, end_date, max_cloud_cover, collection, limit).

        Connectors whose ``search()`` method expects a different signature
        (e.g. a single ``dict`` positional arg, or a custom parameter set)
        **must override this method** rather than changing ``search()``, so
        the ConnectorManager can always call a single consistent interface.

        Args:
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat] or None
            start_date: Start date ``YYYY-MM-DD`` or None
            end_date: End date ``YYYY-MM-DD`` or None
            max_cloud_cover: Maximum cloud cover percentage (0-100) or None
            collection: Collection / dataset identifier or None
            text_query: Free-text search string or None
            limit: Maximum number of results to return

        Returns:
            Tuple[List[Dict], Optional[str]]: ``(items, next_token_or_error)``
        """
        result = self.search(  # type: ignore[call-arg]
            bbox=bbox,
            start_date=start_date or "",
            end_date=end_date or "",
            max_cloud_cover=max_cloud_cover,
            collection=collection,
            limit=limit,
        )
        if isinstance(result, tuple):
            return result
        return result, None

    def get_tile_url(self, result: dict, z: int, x: int, y: int) -> str:
        raise NotImplementedError()

    def resolve_preview_url(self, item: dict) -> str:
        """Resolve a quicklook/preview URL from a STAC-like item.

        Connectors can override this to apply provider-specific logic.
        """
        assets = item.get('assets') if isinstance(item, dict) else {}
        assets = assets if isinstance(assets, dict) else {}

        for key in self._PREVIEW_ASSET_KEYS:
            asset = assets.get(key)
            href = self._asset_href(item, asset)
            if href:
                return href

        preview_roles = ('thumbnail', 'overview', 'preview', 'browse', 'quicklook')
        for _key, asset in assets.items():
            if not isinstance(asset, dict):
                continue
            roles = asset.get('roles') or []
            if isinstance(roles, str):
                roles = [roles]
            if any(role in roles for role in preview_roles):
                href = self._asset_href(item, asset)
                if href:
                    return href

        links = item.get('links') if isinstance(item, dict) else []
        if isinstance(links, list):
            for link in links:
                if not isinstance(link, dict):
                    continue
                if link.get('rel') in ('thumbnail', 'preview', 'quicklook') and link.get('href'):
                    return self._asset_href(item, link)

        properties = item.get('properties') if isinstance(item, dict) else {}
        if isinstance(properties, dict):
            quicklook_links = properties.get('quicklook_links')
            if isinstance(quicklook_links, list):
                for href in quicklook_links:
                    resolved = self._asset_href(item, href)
                    if resolved:
                        return resolved
            for key in (
                'thumbnail', 'thumbnail_url', 'thumbnail_href',
                'quicklook', 'quicklook_url', 'quicklook_href',
                'overview', 'overview_url', 'browse_url', 'preview_url',
            ):
                href = self._asset_href(item, properties.get(key))
                if href:
                    return href

        return ''

    def resolve_cog_url(self, item: dict) -> str:
        """Resolve a raster/COG URL from a STAC-like item.

        Connectors can override this to apply provider-specific logic.
        """
        assets = item.get('assets') if isinstance(item, dict) else {}
        assets = assets if isinstance(assets, dict) else {}

        # Honor well-known asset keys, but never mistake a browse image for data.
        for key in self._COG_ASSET_PRIORITY:
            asset = assets.get(key)
            if not asset:
                continue
            if self._is_preview_asset(key, asset):
                continue
            href = self._asset_href(item, asset)
            if href and self._is_raster_asset(href, asset, key):
                return href

        for key, asset in assets.items():
            if self._is_preview_asset(key, asset):
                continue
            href = self._asset_href(item, asset)
            if href and self._is_raster_asset(href, asset):
                return href

        return ''

    @staticmethod
    def _asset_href(item: dict, asset) -> str:
        if isinstance(asset, dict):
            href = str(asset.get('href') or '').strip()
        elif isinstance(asset, str):
            href = asset.strip()
        else:
            href = ''
        if not href:
            return ''

        parsed = urlsplit(href)
        if parsed.scheme or href.startswith('//'):
            return href

        links = item.get('links') if isinstance(item, dict) else []
        if isinstance(links, list):
            for link in links:
                if isinstance(link, dict) and link.get('rel') == 'self' and link.get('href'):
                    return urljoin(str(link['href']), href)
        return href

    @staticmethod
    def _is_preview_asset(key: str, asset) -> bool:
        preview_names = {'thumbnail', 'quicklook', 'preview', 'overview', 'browse'}
        if str(key).lower() in preview_names:
            return True
        if not isinstance(asset, dict):
            return False
        roles = asset.get('roles') or []
        if isinstance(roles, str):
            roles = [roles]
        return bool(preview_names.intersection(str(role).lower() for role in roles))

    def _is_raster_asset(self, href: str, asset, key: str = '') -> bool:
        path = urlsplit(href).path.lower()
        if path.endswith('.safe') or path.endswith('/'):
            return False
        media_type = str(asset.get('type') or '').lower() if isinstance(asset, dict) else ''
        if media_type:
            if any(media_type.startswith(media) for media in ('image/png', 'image/jpeg', 'image/gif', 'application/json')):
                return False
            if any(media_type.startswith(media) for media in self._COG_MEDIA_TYPES):
                return True
        elif key in self._COG_ASSET_PRIORITY:
            return True
        return path.endswith(('.tif', '.tiff', '.jp2', '.j2k', '.cog'))

    def get_asset_auth_headers(self, item: dict, href: str) -> dict:
        """Optional auth headers for direct asset access.

        Default implementation returns an empty header set.
        Connectors can override this when asset endpoints require custom auth.
        """
        _ = item
        _ = href
        return {}
