"""Umbra Canopy REST/STAC API connector."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..logger import get_logger
from ..utilities.qgis_network import qgis_request_json
from .base import ConnectorBase

logger = get_logger("connectors.umbra")


class UmbraConnector(ConnectorBase):
    """Dedicated Umbra commercial API client."""

    DEFAULT_API_BASE = "https://api.canopy.umbra.space"
    LANDING_PATH = "/v2/stac/"
    COLLECTIONS_PATH = "/v2/stac/collections"
    SEARCH_PATH = "/v2/stac/search"
    AUTH_TOKEN_URL = "https://auth.canopy.umbra.space/oauth/token"

    timeout_auth: float = 10.0
    timeout_search: float = 60.0

    def __init__(self) -> None:
        super().__init__()
        self._api_base_url = self.DEFAULT_API_BASE
        self._access_token: Optional[str] = None
        self._client_id: Optional[str] = None
        self._client_secret: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

    def authenticate(
        self,
        credentials: Optional[Dict[str, Any]] = None,
    ) -> bool:
        credentials = credentials or {}
        self._api_base_url = str(
            credentials.get("api_base_url") or self.DEFAULT_API_BASE
        ).strip().rstrip("/")
        self._access_token = (
            str(credentials.get("access_token") or "").strip() or None
        )
        self._client_id = (
            str(credentials.get("client_id") or "").strip() or None
        )
        self._client_secret = (
            str(credentials.get("client_secret") or "").strip() or None
        )

        if not self._access_token and self._client_id and self._client_secret:
            self._access_token = self._request_token(
                self._client_id,
                self._client_secret,
            )

        if not self._access_token:
            logger.warning(
                "Umbra API authentication failed: missing access token"
            )
            return False

        try:
            payload = self._get_json(
                self._build_url(self.LANDING_PATH),
                timeout=self.timeout_auth,
            )
            ok = isinstance(payload, dict)
            if ok:
                logger.info("Umbra API authentication successful")
            return ok
        except Exception as exc:
            logger.error(f"Umbra API authentication failed: {exc}")
            return False

    def get_collections(self) -> List[Dict[str, Any]]:
        if not self._ensure_token():
            return []
        payload = self._get_json(
            self._build_url(self.COLLECTIONS_PATH),
            timeout=self.timeout_search,
        )
        collections = (
            payload.get("collections", [])
            if isinstance(payload, dict)
            else []
        )
        out: List[Dict[str, Any]] = []
        if isinstance(collections, list):
            for collection in collections:
                if not isinstance(collection, dict):
                    continue
                cid = str(collection.get("id") or "").strip()
                if not cid:
                    continue
                out.append(
                    {
                        "id": cid,
                        "title": collection.get("title") or cid,
                        "description": collection.get("description") or "",
                    }
                )
        return out

    def search_unified(
        self,
        bbox: Optional[List[float]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_cloud_cover: Optional[float] = None,
        collection: Optional[str] = None,
        text_query: Optional[str] = None,
        limit: int = 100,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        query = {
            "bbox": bbox,
            "start_date": start_date,
            "end_date": end_date,
            "max_cloud_cover": max_cloud_cover,
            "collection": collection,
            "text_query": text_query,
            "limit": limit,
            "timeout": timeout,
        }
        query.update(kwargs)
        return self.search(query)

    def search(
        self,
        query: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        if not self._ensure_token():
            return [], "Missing Umbra token"

        query = query or {}
        body: Dict[str, Any] = {"limit": int(query.get("limit") or 100)}
        bbox = query.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            body["bbox"] = [float(v) for v in bbox]

        start_date = str(query.get("start_date") or "").strip()
        end_date = str(query.get("end_date") or "").strip()
        if start_date or end_date:
            body["datetime"] = f"{start_date or '..'}/{end_date or '..'}"

        collection = str(query.get("collection") or "").strip()
        if collection:
            body["collections"] = [collection]

        text_query = str(query.get("text_query") or "").strip()
        if text_query:
            body["query"] = {
                "platform": {"ilike": f"%{text_query}%"},
            }

        payload = self._post_json(
            self._build_url(self.SEARCH_PATH),
            json_body=body,
            timeout=float(query.get("timeout") or self.timeout_search),
        )
        features = [
            self._normalize_feature(f)
            for f in self._extract_features(payload)
        ]
        next_token = self._extract_next_token(payload)
        return [f for f in features if f], next_token

    def download(self, item: Dict[str, Any], output_path: str) -> bool:
        _ = output_path
        assets = item.get("assets") or {}
        for key in ("analytic", "image", "data", "cog", "visual"):
            href = (assets.get(key) or {}).get("href")
            if href:
                return True
        return False

    def _request_token(
        self,
        client_id: str,
        client_secret: str,
    ) -> Optional[str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "audience": self._api_base_url.rstrip("/"),
            "grant_type": "client_credentials",
        }

        token_data, qgis_error, status = qgis_request_json(
            method="POST",
            url=self.AUTH_TOKEN_URL,
            headers=headers,
            payload=payload,
            timeout=self.timeout_auth,
        )
        if qgis_error is None and isinstance(token_data, dict):
            token = str(token_data.get("access_token") or "").strip()
            expires_in = int(token_data.get("expires_in") or 0)
            if token and expires_in > 0:
                self._token_expiry = datetime.utcnow() + timedelta(
                    seconds=max(60, expires_in - 120)
                )
            return token or None

        if qgis_error:
            logger.warning(
                "Umbra token request via QGIS failed (status=%s), "
                "falling back to requests: %s",
                status,
                qgis_error,
            )

        session = self.get_session()
        response = session.post(
            self.AUTH_TOKEN_URL,
            headers=headers,
            json=payload,
            timeout=self.timeout_auth,
            verify=self._verify_ssl,
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        token = str(payload.get("access_token") or "").strip()
        expires_in = int(payload.get("expires_in") or 0)
        if token and expires_in > 0:
            self._token_expiry = datetime.utcnow() + timedelta(
                seconds=max(60, expires_in - 120)
            )
        return token or None

    def _ensure_token(self) -> bool:
        token_valid = (
            self._token_expiry is None
            or datetime.utcnow() < self._token_expiry
        )
        if self._access_token and token_valid:
            return True
        if self._client_id and self._client_secret:
            self._access_token = self._request_token(
                self._client_id,
                self._client_secret,
            )
            return bool(self._access_token)
        return bool(self._access_token)

    def _build_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._api_base_url}{path}"

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json, application/geo+json",
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": "KADAS-Altair-Plugin/1.0",
        }

    def _get_json(self, url: str, timeout: float) -> Dict[str, Any]:
        data, qgis_error, status = qgis_request_json(
            method="GET",
            url=url,
            headers=self._headers(),
            timeout=timeout,
        )
        if qgis_error is None and isinstance(data, dict):
            return data

        if qgis_error:
            logger.warning(
                "Umbra GET via QGIS failed (status=%s), "
                "falling back to requests: %s",
                status,
                qgis_error,
            )

        session = self.get_session()
        response = session.get(
            url,
            headers=self._headers(),
            timeout=timeout,
            verify=self._verify_ssl,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    def _post_json(
        self,
        url: str,
        json_body: Dict[str, Any],
        timeout: float,
    ) -> Dict[str, Any]:
        data, qgis_error, status = qgis_request_json(
            method="POST",
            url=url,
            headers=self._headers(),
            payload=json_body,
            timeout=timeout,
        )
        if qgis_error is None and isinstance(data, dict):
            return data

        if qgis_error:
            logger.warning(
                "Umbra POST via QGIS failed (status=%s), "
                "falling back to requests: %s",
                status,
                qgis_error,
            )

        session = self.get_session()
        response = session.post(
            url,
            headers=self._headers(),
            json=json_body,
            timeout=timeout,
            verify=self._verify_ssl,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _extract_features(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        value = payload.get("features")
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
        return []

    @staticmethod
    def _extract_next_token(payload: Dict[str, Any]) -> Optional[str]:
        links = payload.get("links")
        if isinstance(links, list):
            for link in links:
                if isinstance(link, dict) and link.get("rel") == "next":
                    href = str(link.get("href") or "").strip()
                    if href:
                        return href
        token = payload.get("next") or payload.get("nextToken")
        return str(token).strip() or None

    @staticmethod
    def _normalize_feature(feature: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(feature)
        if out.get("type") != "Feature":
            out["type"] = "Feature"
        out.setdefault("id", str(out.get("id") or "unknown"))
        out.setdefault("properties", {})
        out.setdefault("assets", {})
        return out


UmbraApiConnector = UmbraConnector

__all__ = ["UmbraConnector", "UmbraApiConnector"]
