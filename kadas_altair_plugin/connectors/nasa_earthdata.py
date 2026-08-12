"""NASA EarthData connector.

Dependency-light implementation based on NASA URS Python guidance.
It authenticates with Earthdata Login credentials and queries NASA CMR directly.
"""

from __future__ import annotations

import csv
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest
    from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager

    QGIS_NETWORK_AVAILABLE = True
except Exception:
    QGIS_NETWORK_AVAILABLE = False

from .base import ConnectorBase
from ..logger import get_logger
from ..utilities.qgis_network import qgis_request_json

try:
    from ..secrets.secure_storage import get_secure_storage
except Exception:
    def get_secure_storage():
        return None

logger = get_logger("connectors.nasa_earthdata")


class NasaUrsSession(requests.Session):
    """Requests session preserving auth behavior for URS redirects."""

    AUTH_HOST = "urs.earthdata.nasa.gov"

    def __init__(self, username: str, password: str):
        super().__init__()
        self.auth = (username, password)

    def rebuild_auth(self, prepared_request, response):
        headers = prepared_request.headers
        if "Authorization" not in headers:
            return

        original_parsed = requests.utils.urlparse(response.request.url)
        redirect_parsed = requests.utils.urlparse(prepared_request.url)

        if (
            original_parsed.hostname != redirect_parsed.hostname
            and redirect_parsed.hostname != self.AUTH_HOST
            and original_parsed.hostname != self.AUTH_HOST
        ):
            del headers["Authorization"]


class CatalogData:
    """Minimal catalog helper with backward-compatible methods."""

    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = rows or []

    def __len__(self) -> int:
        return len(self.rows)

    def __bool__(self) -> bool:
        return len(self.rows) > 0

    @staticmethod
    def _value(row: Dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    def get_short_names(self) -> List[str]:
        return [
            self._value(row, "ShortName", "short_name")
            for row in self.rows
            if self._value(row, "ShortName", "short_name")
        ]

    def get_dataset_items(self) -> List[Dict[str, Any]]:
        return [{"row": row} for row in self.rows]

    def get_category_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in self.rows:
            category = self._value(row, "Category")
            if category and category.lower() != "nan":
                counts[category] = counts.get(category, 0) + 1
        return counts

    def find_dataset(self, query: str) -> Optional[Dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return None

        for row in self.rows:
            short_name = self._value(row, "ShortName", "short_name")
            concept_id = self._value(row, "concept-id", "ConceptID", "concept_id")
            title = self._value(row, "EntryTitle", "title")
            provider = self._value(row, "provider-id", "Provider", "provider")
            haystack = " ".join([short_name, concept_id, title, provider]).lower()
            if q in haystack:
                return {
                    "row": row,
                    "short_name": short_name,
                    "concept_id": concept_id,
                    "title": title,
                    "provider": provider,
                }
        return None


class NasaEarthdataConnector(ConnectorBase):
    """Connector for NASA EarthData via URS authentication and CMR API."""

    CATALOG_URL = "https://github.com/opengeos/NASA-Earth-Data/raw/main/nasa_earth_data.tsv"
    CATALOG_FALLBACK_URLS = (
        "https://raw.githubusercontent.com/opengeos/NASA-Earth-Data/main/nasa_earth_data.tsv",
        "https://cdn.jsdelivr.net/gh/opengeos/NASA-Earth-Data@main/nasa_earth_data.tsv",
    )
    CMR_COLLECTIONS_URL = "https://cmr.earthdata.nasa.gov/search/collections.json"
    CMR_COLLECTIONS_FALLBACK_URL = "https://cmr.earthdata.nasa.gov/search/collections.umm_json"
    CMR_GRANULES_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
    CMR_GRANULES_FALLBACK_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
    AUTH_PROBE_TIMEOUT = 60

    catalog_cache_timeout: float = 604800.0

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
        self._session: Optional[requests.Session] = None
        self._auth_source = ""
        self._last_auth_error: Optional[Exception] = None
        self._last_auth_error_kind: str = ""

        self._catalog_cache: Optional[CatalogData] = None
        self._catalog_cache_time: float = 0.0

        self.cache_dir = Path(tempfile.gettempdir()) / "nasa_earthdata_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_cache_file = self.cache_dir / "nasa_earth_data.tsv"

    def _load_stored_credentials(self) -> None:
        try:
            storage = get_secure_storage()
            if storage:
                creds = storage.get_credentials("nasa_earthdata") or {}
                if not self.username:
                    self.username = creds.get("username") or self.username
                if not self.password:
                    self.password = creds.get("password") or self.password
                if not self.access_token:
                    self.access_token = (
                        creds.get("access_token")
                        or creds.get("token")
                        or self.access_token
                    )
        except Exception as exc:
            logger.debug(f"NASA credentials load failed: {exc}")

        self.username = self.username or os.environ.get("EARTHDATA_USERNAME")
        self.password = self.password or os.environ.get("EARTHDATA_PASSWORD")
        self.access_token = self.access_token or os.environ.get("EARTHDATA_TOKEN")

    def _classify_auth_error(self, exc: Exception) -> str:
        text = str(exc).lower()
        if "407" in text or "proxy" in text:
            return "proxy_auth_required"
        if "401" in text or "unauthorized" in text:
            return "invalid_credentials"
        if "403" in text or "forbidden" in text:
            return "access_denied"
        if "timed out" in text or "connection" in text or "network" in text:
            return "network_error"
        return "authentication_error"

    def get_last_auth_error_kind(self) -> str:
        return self._last_auth_error_kind

    def get_auth_failure_hint(self) -> str:
        kind = self._last_auth_error_kind
        if kind == "proxy_auth_required":
            return (
                "Proxy authentication failed (HTTP 407). "
                "Configure proxy credentials in KADAS Settings -> Network and retry."
            )
        if kind == "invalid_credentials":
            return "Invalid Earthdata Login username/password."
        if kind == "network_error":
            return (
                "Network/proxy timeout while contacting NASA CMR. "
                "Verify KADAS proxy settings and retry."
            )
        if self._last_auth_error is not None:
            return f"Authentication failed: {self._last_auth_error}"
        return "Authentication failed."

    def _apply_network_settings(self, session: requests.Session) -> requests.Session:
        """Apply connector proxy/SSL settings to a requests session."""
        try:
            session.trust_env = True
        except Exception:
            pass

        base_session = super().get_session()
        if base_session is not None:
            try:
                base_proxies = getattr(base_session, "proxies", None)
                if base_proxies:
                    session.proxies.update(base_proxies)
            except Exception:
                pass

            try:
                if hasattr(base_session, "verify"):
                    session.verify = base_session.verify
            except Exception:
                pass

        if getattr(self, "_proxies", None):
            try:
                session.proxies.update(self._proxies)
            except Exception:
                pass

        # Ensure HTTPS requests can still route through proxy when only one
        # scheme is populated by upstream configuration.
        try:
            if session.proxies.get("http") and not session.proxies.get("https"):
                session.proxies["https"] = session.proxies["http"]
            elif session.proxies.get("https") and not session.proxies.get("http"):
                session.proxies["http"] = session.proxies["https"]
        except Exception:
            pass

        try:
            session.verify = self._verify_ssl
        except Exception:
            pass

        return session

    def _cmr_urls(self) -> List[str]:
        """Return CMR endpoints with optional env overrides and built-in fallback."""
        urls: List[str] = []

        env_full = (os.environ.get("EARTHDATA_CMR_GRANULES_URL") or "").strip()
        if env_full:
            urls.append(env_full)

        env_base = (os.environ.get("EARTHDATA_CMR_BASE_URL") or "").strip().rstrip("/")
        if env_base:
            urls.append(f"{env_base}/search/granules.json")
            urls.append(f"{env_base}/search/granules.umm_json")

        urls.extend([self.CMR_GRANULES_URL, self.CMR_GRANULES_FALLBACK_URL])

        # Preserve order while deduplicating.
        seen = set()
        ordered: List[str] = []
        for url in urls:
            if url and url not in seen:
                ordered.append(url)
                seen.add(url)
        return ordered

    def _cmr_collection_urls(self) -> List[str]:
        """Return collection endpoints with optional env overrides and fallback."""
        urls: List[str] = []

        env_full = (os.environ.get("EARTHDATA_CMR_COLLECTIONS_URL") or "").strip()
        if env_full:
            urls.append(env_full)

        env_base = (os.environ.get("EARTHDATA_CMR_BASE_URL") or "").strip().rstrip("/")
        if env_base:
            urls.append(f"{env_base}/search/collections.json")
            urls.append(f"{env_base}/search/collections.umm_json")

        urls.extend([self.CMR_COLLECTIONS_URL, self.CMR_COLLECTIONS_FALLBACK_URL])

        seen = set()
        ordered: List[str] = []
        for url in urls:
            if url and url not in seen:
                ordered.append(url)
                seen.add(url)
        return ordered

    @staticmethod
    def _http_timeout(total_seconds: int) -> Tuple[int, int]:
        """Return (connect, read) timeout tuple tuned for corporate proxies."""
        connect = max(int(total_seconds), 10)
        read = max(connect * 2, 30)
        return (connect, read)

    @staticmethod
    def _normalize_temporal(start_date: str, end_date: str) -> str:
        """Return CMR temporal value with explicit UTC timestamps."""
        def _normalize_start(value: str) -> str:
            v = (value or "").strip()
            if not v:
                return "1970-01-01T00:00:00Z"
            if "T" in v:
                return v if v.endswith("Z") else f"{v}Z"
            return f"{v}T00:00:00Z"

        def _normalize_end(value: str) -> str:
            v = (value or "").strip()
            if not v:
                return time.strftime("%Y-%m-%dT23:59:59Z")
            if "T" in v:
                return v if v.endswith("Z") else f"{v}Z"
            return f"{v}T23:59:59Z"

        return f"{_normalize_start(start_date)},{_normalize_end(end_date)}"

    def _request_cmr(
        self,
        session: requests.Session,
        params: Dict[str, Any],
        base_timeout: int,
        max_attempts: int = 3,
        urls: Optional[List[str]] = None,
        request_name: str = "NASA CMR request",
    ) -> Dict[str, Any]:
        """Request CMR with retries and endpoint fallback."""
        last_exc: Optional[Exception] = None

        cmr_urls = urls or self._cmr_urls()
        headers: Dict[str, str] = {
            "Accept": "application/json",
        }

        auth_header = str(session.headers.get("Authorization") or "").strip()
        if auth_header:
            headers["Authorization"] = auth_header

        for idx, url in enumerate(cmr_urls):
            for attempt in range(1, max_attempts + 1):
                timeout_tuple = self._http_timeout(base_timeout + (attempt - 1) * 15)
                try:
                    logger.debug(
                        "%s %s attempt %s/%s timeout=%s",
                        request_name,
                        url,
                        attempt,
                        max_attempts,
                        timeout_tuple,
                    )
                    data, qgis_error, status = qgis_request_json(
                        method="GET",
                        url=url,
                        headers=headers,
                        params=params,
                        timeout=max(timeout_tuple),
                    )
                    # Only accept the QGIS result when it contains a real CMR
                    # "feed" key. An empty dict ({}) means QGIS NAM returned an
                    # empty body (common in background threads); fall through to
                    # session.get in that case.
                    if qgis_error is None and isinstance(data, dict) and "feed" in data:
                        return data

                    if qgis_error is None and isinstance(data, dict) and "feed" not in data:
                        logger.debug(
                            "%s QGIS response missing 'feed' key on %s, "
                            "falling back to requests",
                            request_name,
                            url,
                        )

                    if qgis_error is not None:
                        # Do not keep retrying a parameter-level 400 for minutes.
                        if status == 400 or "bad request" in str(qgis_error).lower():
                            raise RuntimeError(
                                f"{request_name} rejected request parameters: {qgis_error}"
                            )

                        logger.warning(
                            "%s via QGIS failed on %s "
                            "(attempt %s/%s, status=%s): %s",
                            request_name,
                            url,
                            attempt,
                            max_attempts,
                            status,
                            qgis_error,
                        )

                    resp = session.get(url, params=params, timeout=timeout_tuple)
                    resp.raise_for_status()
                    data = resp.json()
                    if isinstance(data, dict):
                        return data
                    raise RuntimeError("NASA CMR returned non-dict JSON payload")
                except Exception as exc:
                    last_exc = exc
                    kind = self._classify_auth_error(exc)
                    logger.warning(
                        "%s failed on %s (attempt %s/%s): %s",
                        request_name,
                        url,
                        attempt,
                        max_attempts,
                        exc,
                    )
                    if kind != "network_error":
                        raise
                    if attempt < max_attempts:
                        time.sleep(min(2 * attempt, 5))

            next_url = cmr_urls[idx + 1] if (idx + 1) < len(cmr_urls) else None
            if next_url:
                logger.warning(
                    "%s endpoint unreachable (%s), trying fallback endpoint: %s",
                    request_name,
                    url,
                    next_url,
                )

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("NASA CMR request failed without exception")

    def _probe_cmr(self, session: requests.Session, timeout_seconds: int) -> bool:
        """Probe CMR; return False on repeated network failures."""
        params = {"short_name": "MOD09GA", "page_size": 1}
        try:
            self._request_cmr(
                session=session,
                params=params,
                base_timeout=max(timeout_seconds, self.AUTH_PROBE_TIMEOUT),
                max_attempts=2,
            )
            return True
        except Exception as exc:
            if self._classify_auth_error(exc) != "network_error":
                raise
            logger.error(
                "NASA CMR probe failed after retries/fallback endpoints: %s",
                exc,
            )
            return False

    def _discover_collection_concept_ids(
        self,
        session: requests.Session,
        bbox: Optional[List[float]],
        start_date: str,
        end_date: str,
        query: str,
        limit: int,
        **kwargs,
    ) -> List[str]:
        """Resolve a broad bbox/date/query search to concrete collection concept ids."""
        params: Dict[str, Any] = {
            "page_size": max(1, min(int(limit), 20)),
            "has_granules": "true",
        }

        if query:
            params["keyword"] = query
            # When a keyword scopes the collection search, do NOT add bbox or
            # temporal: CMR collection metadata spatial/temporal indexing is
            # unreliable and these filters can silently drop valid collections.
            # Spatial/temporal filtering is applied later at the granule level.
        else:
            if bbox and len(bbox) >= 4:
                params["bounding_box"] = ",".join(str(v) for v in bbox[:4])
            if start_date or end_date:
                params["temporal"] = self._normalize_temporal(start_date, end_date)
        if kwargs.get("provider"):
            params["provider"] = kwargs["provider"]
        if kwargs.get("version"):
            params["version"] = kwargs["version"]

        data = self._request_cmr(
            session=session,
            params=params,
            base_timeout=min(int(self.timeout_search or 60), 20),
            max_attempts=2,
            urls=self._cmr_collection_urls(),
            request_name="NASA CMR collection discovery",
        )

        entries = data.get("feed", {}).get("entry", [])
        concept_ids: List[str] = []
        seen = set()
        for entry in entries:
            concept_id = str(entry.get("id") or "").strip()
            if not concept_id or concept_id in seen:
                continue
            seen.add(concept_id)
            concept_ids.append(concept_id)
        return concept_ids

    def authenticate(self, credentials: Optional[dict] = None, verify: bool = True) -> bool:
        self._last_auth_error = None
        self._last_auth_error_kind = ""

        if credentials:
            self.username = credentials.get("username") or self.username
            self.password = credentials.get("password") or self.password
            self.access_token = (
                credentials.get("access_token")
                or credentials.get("token")
                or self.access_token
            )

        self._load_stored_credentials()
        allow_deferred_validation = bool(
            (credentials or {}).get("allow_deferred_validation", True)
        )

        # Token-only mode (fallback for EARTHDATA_TOKEN setups).
        if (not self.username or not self.password) and self.access_token:
            try:
                session = requests.Session()
                session = self._apply_network_settings(session)
                session.headers.update(
                    {
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self.access_token}",
                    }
                )
                if verify:
                    probe_ok = self._probe_cmr(
                        session,
                        timeout_seconds=max(
                            self.AUTH_PROBE_TIMEOUT, int(self.timeout_auth)
                        ),
                    )
                    if not probe_ok and not allow_deferred_validation:
                        self._last_auth_error_kind = "network_error"
                        self._last_auth_error = requests.exceptions.ConnectTimeout(
                            "NASA CMR unreachable during authentication validation"
                        )
                        self.authenticated = False
                        self._session = None
                        logger.error(
                            "NASA EarthData token authentication rejected: CMR unreachable"
                        )
                        return False
                    if not probe_ok and allow_deferred_validation:
                        logger.warning(
                            "NASA CMR unreachable during auth probe; proceeding "
                            "with deferred validation"
                        )

                self._session = session
                self.authenticated = True
                self._auth_source = "token"
                logger.info("NASA EarthData authenticated via bearer token")
                return True
            except Exception as exc:
                self._last_auth_error = exc
                self._last_auth_error_kind = self._classify_auth_error(exc)
                self.authenticated = False
                self._session = None
                logger.error(
                    f"NASA EarthData token authentication failed ({self._last_auth_error_kind}): {exc}"
                )
                return False

        if not self.username or not self.password:
            self._last_auth_error_kind = "missing_credentials"
            self.authenticated = False
            return False

        try:
            session = NasaUrsSession(self.username, self.password)
            session = self._apply_network_settings(session)
            session.headers.update({"Accept": "application/json"})

            if verify:
                probe_ok = self._probe_cmr(
                    session,
                    timeout_seconds=max(
                        self.AUTH_PROBE_TIMEOUT, int(self.timeout_auth)
                    ),
                )
                if not probe_ok and not allow_deferred_validation:
                    self._last_auth_error_kind = "network_error"
                    self._last_auth_error = requests.exceptions.ConnectTimeout(
                        "NASA CMR unreachable during authentication validation"
                    )
                    self.authenticated = False
                    self._session = None
                    logger.error(
                        "NASA EarthData URS authentication rejected: CMR unreachable"
                    )
                    return False
                if not probe_ok and allow_deferred_validation:
                    logger.warning(
                        "NASA CMR unreachable during auth probe; proceeding "
                        "with deferred validation"
                    )

            self._session = session
            self.authenticated = True
            self._auth_source = "urs"
            logger.info("NASA EarthData authenticated via URS")
            return True

        except Exception as exc:
            self._last_auth_error = exc
            self._last_auth_error_kind = self._classify_auth_error(exc)
            self.authenticated = False
            self._session = None
            logger.error(
                f"NASA EarthData authentication failed ({self._last_auth_error_kind}): {exc}"
            )
            return False

    def is_authenticated(self) -> bool:
        return self.authenticated

    def get_session(self):
        return self._session or super().get_session()

    def get_auth_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _load_catalog_rows(self, use_cache: bool) -> List[Dict[str, Any]]:
        if use_cache and self.catalog_cache_file.exists():
            with open(self.catalog_cache_file, "r", encoding="utf-8") as fin:
                return list(csv.DictReader(fin, delimiter="\t"))

        text = self._download_catalog_tsv(timeout_seconds=45)
        if not text.strip():
            raise RuntimeError("NASA catalog download returned empty payload")
        self.catalog_cache_file.write_text(text, encoding="utf-8")
        return list(csv.DictReader(text.splitlines(), delimiter="\t"))

    def _catalog_urls(self) -> List[str]:
        env_url = str(os.environ.get("EARTHDATA_CATALOG_URL") or "").strip()
        urls: List[str] = []
        if env_url:
            urls.append(env_url)
        urls.append(self.CATALOG_URL)
        urls.extend(list(self.CATALOG_FALLBACK_URLS))

        seen = set()
        ordered: List[str] = []
        for url in urls:
            if url and url not in seen:
                ordered.append(url)
                seen.add(url)
        return ordered

    def _download_catalog_via_qgis(
        self,
        url: str,
        timeout_seconds: int,
    ) -> Optional[str]:
        if not QGIS_NETWORK_AVAILABLE:
            return None

        try:
            QgsNetworkAccessManager.instance().setupDefaultProxyAndCache()
            req = QNetworkRequest(QUrl(url))
            req.setRawHeader(
                b"Accept",
                b"text/tab-separated-values, text/plain, */*;q=0.8",
            )

            blocking = QgsBlockingNetworkRequest()
            err = blocking.get(req, forceRefresh=True)
            if err != QgsBlockingNetworkRequest.NoError:
                logger.warning(
                    "NASA catalog QGIS download failed on %s: %s",
                    url,
                    blocking.errorMessage(),
                )
                return None

            reply = blocking.reply()
            status_raw = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            status = int(status_raw) if status_raw is not None else None
            if status is not None and status >= 400:
                logger.warning(
                    "NASA catalog QGIS download HTTP %s on %s",
                    status,
                    url,
                )
                return None

            raw = reply.content().data().decode("utf-8", errors="replace")
            return raw if raw.strip() else None
        except Exception as exc:
            logger.warning("NASA catalog QGIS download exception on %s: %s", url, exc)
            return None

    def _download_catalog_tsv(
        self,
        timeout_seconds: int,
        max_attempts: int = 2,
    ) -> str:
        last_exc: Optional[Exception] = None

        for url in self._catalog_urls():
            for attempt in range(1, max_attempts + 1):
                timeout_tuple = self._http_timeout(timeout_seconds + (attempt - 1) * 10)
                try:
                    text = self._download_catalog_via_qgis(
                        url,
                        timeout_seconds=max(timeout_tuple),
                    )
                    if text:
                        logger.info("NASA catalog loaded via QGIS network from %s", url)
                        return text

                    session = self._session or self._apply_network_settings(requests.Session())
                    response = session.get(url, timeout=timeout_tuple)
                    response.raise_for_status()
                    text = response.text or ""
                    if text.strip():
                        logger.info("NASA catalog loaded via requests from %s", url)
                        return text
                    raise RuntimeError("Empty NASA catalog payload")
                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        "NASA catalog download failed on %s (attempt %s/%s): %s",
                        url,
                        attempt,
                        max_attempts,
                        exc,
                    )
                    if attempt < max_attempts:
                        time.sleep(min(2 * attempt, 5))

            logger.warning("NASA catalog source unreachable, trying next mirror: %s", url)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("NASA catalog download failed without exception")

    def _load_catalog(self) -> Optional[CatalogData]:
        if self._catalog_cache is not None:
            age = time.time() - self._catalog_cache_time
            if age < self.catalog_cache_timeout:
                return self._catalog_cache

        use_cache = False
        if self.catalog_cache_file.exists():
            age = time.time() - self.catalog_cache_file.stat().st_mtime
            use_cache = age < self.catalog_cache_timeout

        try:
            rows = self._load_catalog_rows(use_cache)
            catalog = CatalogData(rows)
            self._catalog_cache = catalog
            self._catalog_cache_time = time.time()
            return catalog
        except Exception as exc:
            # Last-resort fallback: allow stale cache if remote sources are unreachable.
            if self.catalog_cache_file.exists():
                try:
                    with open(self.catalog_cache_file, "r", encoding="utf-8") as fin:
                        rows = list(csv.DictReader(fin, delimiter="\t"))
                    if rows:
                        catalog = CatalogData(rows)
                        self._catalog_cache = catalog
                        self._catalog_cache_time = time.time()
                        logger.warning(
                            "NASA catalog remote load failed (%s); using stale local cache: %s",
                            exc,
                            self.catalog_cache_file,
                        )
                        return catalog
                except Exception as stale_exc:
                    logger.warning("NASA stale catalog cache read failed: %s", stale_exc)

            logger.error(f"NASA EarthData catalog load failed: {exc}")
            return None

    def get_collections(self) -> List[Dict[str, Any]]:
        catalog = self._load_catalog()
        if catalog is None or len(catalog) == 0:
            return []

        counts = catalog.get_category_counts()
        collections = [
            {
                "id": category,
                "title": category,
                "dataset_count": count,
            }
            for category, count in sorted(counts.items(), key=lambda kv: kv[0].lower())
        ]
        collections.insert(
            0,
            {
                "id": "all",
                "title": "All Datasets",
                "dataset_count": len(catalog),
            },
        )
        return collections

    @staticmethod
    def _normalize_cloud_cover(
        max_cloud_cover: Optional[float],
        kwargs: Dict[str, Any],
    ) -> Optional[Tuple[float, float]]:
        value = kwargs.get("cloud_cover", max_cloud_cover)
        if value is None:
            return None

        if isinstance(value, (list, tuple)) and len(value) == 2:
            return (float(value[0]), float(value[1]))

        max_v = float(value)
        if 0.0 <= max_v <= 1.0:
            max_v *= 100.0
        return (0.0, max_v)

    @staticmethod
    def _has_granule_scope(params: Dict[str, Any]) -> bool:
        """CMR granule search must target at least one collection subset."""
        scope_keys = (
            "concept_id",
            "collection_concept_id",
            "short_name",
            "provider",
            "entry_title",
            "entry_id",
            "echo_collection_id",
        )

        for key in scope_keys:
            value = params.get(key)
            if value is not None and str(value).strip():
                return True

        short_name = str(params.get("short_name") or "").strip()
        version = str(params.get("version") or "").strip()
        return bool(short_name and version)

    def search_unified(
        self,
        bbox=None,
        start_date=None,
        end_date=None,
        max_cloud_cover=None,
        collection=None,
        text_query=None,
        limit: int = 100,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> tuple:
        return self.search(
            bbox=bbox,
            start_date=start_date or "",
            end_date=end_date or "",
            max_cloud_cover=max_cloud_cover,
            collection=collection,
            text_query=text_query or "",
            limit=limit,
            timeout=timeout,
            **kwargs,
        )

    def search(
        self,
        bbox: Optional[List[float]] = None,
        start_date: str = "",
        end_date: str = "",
        max_cloud_cover: Optional[float] = None,
        collection: Optional[str] = None,
        limit: int = 50,
        text_query: str = "",
        timeout: Optional[float] = None,
        **kwargs,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        # Avoid startup/UI stalls on a pre-search auth probe; real CMR request
        # below is the effective connectivity check.
        if not self.authenticated and not self.authenticate(verify=False):
            logger.error("NASA EarthData: not authenticated")
            return [], None

        if not self._session:
            logger.error("NASA EarthData: no active session")
            return [], None

        query = str(kwargs.get("query", text_query or "")).strip()
        concept_id = None
        short_name = None
        collection_concept_ids: List[str] = []

        if collection:
            collection = str(collection).strip()
            if collection.startswith("C") and "-" in collection:
                concept_id = collection
            else:
                short_name = collection

        if not concept_id and not short_name and query:
            # Only consult the catalog when `collection` was explicitly provided
            # as a text name (not a CMR concept ID). Do NOT use catalog lookup
            # for keyword hints from search hints (text_query) because the TSV
            # ShortName column sometimes contains hashes/UUIDs that are not
            # valid CMR identifiers and cause 400 errors in granule searches.
            # Keyword-based searches always go through collection discovery.
            explicit_collection_text = (
                collection and not (collection.startswith("C") and "-" in collection)
            )
            if explicit_collection_text:
                catalog = self._load_catalog()
                if catalog:
                    match = catalog.find_dataset(query)
                    if match:
                        candidate_concept_id = match.get("concept_id") or None
                        candidate_short_name = match.get("short_name") or None
                        # Accept only well-formed CMR identifiers.
                        # CMR concept IDs look like "C12345678-PROVIDER"; short
                        # names are alphanumeric strings (no raw UUIDs/hashes).
                        if candidate_concept_id and re.match(
                            r'^C\d+-[A-Z0-9_]+$', candidate_concept_id
                        ):
                            concept_id = candidate_concept_id
                        if (
                            not concept_id
                            and candidate_short_name
                            and re.match(r'^[A-Za-z0-9_\-\.]{2,40}$', candidate_short_name)
                        ):
                            short_name = candidate_short_name

        if not concept_id and not short_name:
            has_bbox = bool(bbox and len(bbox) >= 4)
            has_temporal = bool(start_date or end_date)
            has_query = bool(query)

            # Allow broad CMR searches when at least one meaningful filter
            # exists, instead of failing hard due to missing collection.
            if not (has_bbox or has_temporal or has_query):
                logger.warning(
                    "NASA EarthData: no collection specified and no usable "
                    "filters (bbox/date/query)"
                )
                return [], None

            logger.info(
                "NASA EarthData: no collection specified, running broad "
                "collection discovery with available filters"
            )

            try:
                collection_concept_ids = self._discover_collection_concept_ids(
                    session=self._session,
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    query=query,
                    limit=limit,
                    **kwargs,
                )
            except Exception as exc:
                message = str(exc)
                if "rejected request parameters" in message.lower() or "bad request" in message.lower():
                    logger.warning(
                        "NASA EarthData collection discovery skipped due to rejected request parameters: %s",
                        exc,
                    )
                else:
                    logger.warning("NASA EarthData collection discovery failed: %s", exc)
                return [], None

            if not collection_concept_ids:
                logger.info(
                    "NASA EarthData collection discovery returned no matching datasets"
                )
                return [], None

        params: Dict[str, Any] = {}
        if short_name:
            params["short_name"] = short_name
        elif concept_id:
            collection_concept_ids = [concept_id]

        if not collection_concept_ids:
            collection_concept_ids = []

        if bbox and len(bbox) >= 4:
            params["bounding_box"] = ",".join(str(v) for v in bbox[:4])

        if start_date or end_date:
            params["temporal"] = self._normalize_temporal(start_date, end_date)

        cloud_cover = self._normalize_cloud_cover(max_cloud_cover, kwargs)
        if cloud_cover is not None and bool(kwargs.get("force_cloud_cover_param", False)):
            params["cloud_cover"] = f"{cloud_cover[0]},{cloud_cover[1]}"

        if kwargs.get("day_night_flag"):
            params["day_night_flag"] = kwargs["day_night_flag"]
        if kwargs.get("provider"):
            params["provider"] = kwargs["provider"]
        if kwargs.get("version"):
            params["version"] = kwargs["version"]
        if kwargs.get("granule_id"):
            params["granule_ur"] = str(kwargs["granule_id"])
        if kwargs.get("orbit_number") is not None:
            params["orbit_number"] = kwargs["orbit_number"]

        try:
            results: List[Dict[str, Any]] = []
            seen_result_ids = set()
            remaining = max(int(limit), 1)
            granule_scopes = collection_concept_ids or [None]
            made_granule_request = False

            for collection_concept_id in granule_scopes:
                request_params = dict(params)
                request_params["page_size"] = remaining
                if collection_concept_id:
                    request_params["collection_concept_id"] = collection_concept_id
                # Do NOT add keyword to granule search: CMR rejects unscoped
                # keyword-only granule queries with 400 Bad Request, and adding
                # keyword together with short_name/collection_concept_id also
                # causes errors. Collection scoping is handled above.

                if not self._has_granule_scope(request_params):
                    logger.info(
                        "NASA EarthData: skipping unscoped granule request; "
                        "collection/provider scope is required by CMR"
                    )
                    continue

                made_granule_request = True

                data = self._request_cmr(
                    session=self._session,
                    params=request_params,
                    base_timeout=min(int(timeout or self.timeout_search or 60), 20),
                    max_attempts=2,
                )
                entries = data.get("feed", {}).get("entry", [])

                for entry in entries:
                    result = self._granule_to_result(entry, len(results))
                    result_id = str(result.get("id") or "")
                    if result_id and result_id in seen_result_ids:
                        continue
                    if result_id:
                        seen_result_ids.add(result_id)
                    results.append(result)
                    remaining -= 1
                    if remaining <= 0:
                        break

                if remaining <= 0:
                    break

            if not made_granule_request:
                return [], None

            return results, None

        except Exception as exc:
            message = str(exc)
            if "rejected request parameters" in message.lower() or "bad request" in message.lower():
                logger.warning(
                    "NASA EarthData search skipped due to rejected request parameters: %s",
                    exc,
                )
            else:
                logger.warning("NASA EarthData search request failed: %s", exc)
            return [], None

    @staticmethod
    def _extract_bbox(entry: Dict[str, Any]) -> Optional[List[float]]:
        boxes = entry.get("boxes") or []
        if boxes:
            try:
                south, west, north, east = [float(v) for v in str(boxes[0]).split()]
                return [west, south, east, north]
            except Exception:
                pass

        points = entry.get("polygons") or []
        if points:
            try:
                values = [float(v) for v in str(points[0]).split()]
                lats = values[0::2]
                lons = values[1::2]
                return [min(lons), min(lats), max(lons), max(lats)]
            except Exception:
                pass

        return None

    @staticmethod
    def _extract_geometry(bbox: Optional[List[float]]) -> Optional[Dict[str, Any]]:
        if not bbox or len(bbox) != 4:
            return None
        west, south, east, north = bbox
        return {
            "type": "Polygon",
            "coordinates": [[
                [west, south], [east, south], [east, north], [west, north], [west, south]
            ]],
        }

    @staticmethod
    def _extract_links(entry: Dict[str, Any]) -> List[str]:
        links: List[str] = []
        for link in entry.get("links", []) or []:
            href = link.get("href")
            rel = link.get("rel", "")
            if not href:
                continue
            if "data#" in rel or "enclosure" in rel or "download" in rel:
                links.append(href)
        return links

    @staticmethod
    def _extract_quicklook_links(entry: Dict[str, Any]) -> List[str]:
        links: List[str] = []
        for link in entry.get("links", []) or []:
            if not isinstance(link, dict):
                continue
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            rel = str(link.get("rel") or "").lower()
            title = str(link.get("title") or "").lower()
            if any(k in rel for k in ("browse", "preview", "thumbnail")):
                links.append(href)
                continue
            if any(k in title for k in ("browse", "preview", "thumbnail", "quicklook")):
                links.append(href)

        deduped: List[str] = []
        seen = set()
        for href in links:
            if href in seen:
                continue
            seen.add(href)
            deduped.append(href)
        return deduped

    @staticmethod
    def _asset_media_type_from_href(href: str) -> str:
        href_l = str(href or "").lower()
        if href_l.endswith((".tif", ".tiff")):
            return "image/tiff; application=geotiff"
        if href_l.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        if href_l.endswith(".png"):
            return "image/png"
        if href_l.endswith((".jp2", ".j2k")):
            return "image/jp2"
        return "application/octet-stream"

    def _granule_to_result(self, entry: Dict[str, Any], result_idx: int) -> Dict[str, Any]:
        granule_id = entry.get("id") or entry.get("title") or f"granule-{result_idx+1}"
        collection_id = entry.get("collection_concept_id") or ""
        bbox = self._extract_bbox(entry)
        geometry = self._extract_geometry(bbox)
        links = self._extract_links(entry)
        quicklook_links = self._extract_quicklook_links(entry)
        dataset_id = str(entry.get("dataset_id") or "")
        short_name = str(entry.get("short_name") or "")
        granule_title = str(entry.get("title") or "")
        collection_title = str(entry.get("entry_title") or "")
        description = str(
            entry.get("summary")
            or entry.get("abstract")
            or entry.get("description")
            or ""
        )
        platform_name = short_name or dataset_id or granule_title
        title = granule_title or collection_title or platform_name or str(granule_id)

        assets: Dict[str, Any] = {}
        for i, href in enumerate(links):
            media_type = self._asset_media_type_from_href(href)
            assets[f"asset_{i+1}"] = {
                "href": href,
                "type": media_type,
                "title": os.path.basename(href.split("?")[0]) or href,
            }

        if quicklook_links:
            q_href = str(quicklook_links[0])
            assets.setdefault(
                "thumbnail",
                {
                    "href": q_href,
                    "type": self._asset_media_type_from_href(q_href),
                    "title": os.path.basename(q_href.split("?")[0]) or q_href,
                },
            )

        return {
            "type": "Feature",
            "id": granule_id,
            "collection": collection_id,
            "bbox": bbox,
            "geometry": geometry,
            "properties": {
                "datetime": entry.get("time_start", ""),
                "start_datetime": entry.get("time_start", ""),
                "end_datetime": entry.get("time_end", ""),
                "platform": platform_name,
                "mission": dataset_id or short_name,
                "dataset_id": dataset_id,
                "short_name": short_name,
                "entry_title": collection_title,
                "title": title,
                "description": description,
                "instrument": str(entry.get("instrument", "") or ""),
                "eo:cloud_cover": None,
                "cloud_cover": None,
                "provider": entry.get("data_center", ""),
                "version": entry.get("version_id", ""),
                "size_mb": 0,
                "data_links": links,
                "quicklook_links": quicklook_links,
                "citation_links": [],
                "cog_available": any(
                    str(h).lower().endswith((".tif", ".tiff", ".jp2", ".j2k"))
                    for h in links
                ),
                "auth_required": True,
                "auth_source": self._auth_source,
            },
            "assets": assets,
            "links": [],
            "is_collection": False,
        }

    def get_download_url(self, result: dict) -> Optional[str]:
        if not self.authenticated:
            return None

        links = result.get("properties", {}).get("data_links", [])
        for link in links:
            if str(link).lower().endswith((".tif", ".tiff", ".jp2", ".j2k")):
                return str(link)
        if links:
            return str(links[0])
        return None
