"""ICEYE commercial Catalog API connector."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..logger import get_logger
from .base import ConnectorBase

logger = get_logger("connectors.iceye")


class IceyeConnector(ConnectorBase):
    """Dedicated REST/API connector for ICEYE Catalog API v2."""

    DEFAULT_API_BASE = "https://api.iceye.com"
    SEARCH_PATH = "/api/catalog/v2/items"
    COLLECTIONS_PATH = "/api/catalog/v2/collections"

    timeout_auth: float = 10.0
    timeout_search: float = 60.0

    def __init__(self) -> None:
        super().__init__()
        self._api_base_url = self.DEFAULT_API_BASE
        self._access_token: Optional[str] = None
        self._contract_id: Optional[str] = None
        self._collections: Optional[List[str]] = None

    def authenticate(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        credentials = credentials or {}
        self._api_base_url = str(
            credentials.get("api_base_url") or self.DEFAULT_API_BASE
        ).strip().rstrip("/")
        self._access_token = str(credentials.get("access_token") or "").strip() or None
        self._contract_id = str(credentials.get("contract_id") or "").strip() or None
        self._collections = self._normalize_collections(credentials.get("collections"))

        if not self._access_token:
            logger.warning("ICEYE API authentication failed: missing access token")
            return False

        try:
            payload = self._get_json(
                self._build_url(self.SEARCH_PATH),
                params={"limit": 1},
                timeout=self.timeout_auth,
            )
            ok = isinstance(payload, dict)
            if ok:
                logger.info("ICEYE API authentication successful")
            else:
                logger.error("ICEYE API authentication failed: invalid response")
            return ok
        except Exception as exc:
            logger.error(f"ICEYE API authentication failed: {exc}")
            return False

    def get_collections(self) -> List[Dict[str, Any]]:
        if not self._access_token:
            return []

        # Prefer the dedicated collections endpoint when available.
        try:
            payload = self._get_json(
                self._build_url(self.COLLECTIONS_PATH),
                timeout=self.timeout_search,
            )
            collections = payload.get("collections", []) if isinstance(payload, dict) else []
            if isinstance(collections, list) and collections:
                out: List[Dict[str, Any]] = []
                for entry in collections:
                    if not isinstance(entry, dict):
                        continue
                    cid = str(entry.get("id") or "").strip()
                    if not cid:
                        continue
                    out.append(
                        {
                            "id": cid,
                            "title": entry.get("title") or cid,
                            "description": entry.get("description") or "",
                        }
                    )
                if out:
                    return out
        except Exception:
            logger.debug("ICEYE collections endpoint unavailable, using item-derived fallback")

        payload = self._get_json(
            self._build_url(self.SEARCH_PATH),
            params={"limit": 100},
            timeout=self.timeout_search,
        )
        seen: set[str] = set()
        out = []
        for feature in self._extract_features(payload):
            collection_id = str(feature.get("collection") or "").strip()
            if collection_id and collection_id not in seen:
                seen.add(collection_id)
                out.append({"id": collection_id, "title": collection_id})
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
        _ = max_cloud_cover  # SAR provider, intentionally unused.
        query = {
            "bbox": bbox,
            "start_date": start_date,
            "end_date": end_date,
            "collection": collection,
            "text_query": text_query,
            "limit": limit,
            "timeout": timeout,
        }
        query.update(kwargs)
        return self.search(query)

    def search(self, query: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        if not self._access_token:
            return [], "Missing ICEYE access token"

        query = query or {}
        params: Dict[str, Any] = {"limit": int(query.get("limit") or 100)}
        bbox = query.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            params["bbox"] = ",".join(str(v) for v in bbox)

        start_date = (query.get("start_date") or "").strip()
        end_date = (query.get("end_date") or "").strip()
        if start_date or end_date:
            params["datetime"] = f"{start_date or '..'}/{end_date or '..'}"

        collection = str(query.get("collection") or "").strip()
        if collection:
            params["collections"] = collection
        elif self._collections:
            params["collections"] = ",".join(self._collections)

        if self._contract_id:
            params["contractID"] = self._contract_id

        text_query = str(query.get("text_query") or "").strip()
        if text_query:
            params["q"] = text_query

        payload = self._get_json(
            self._build_url(self.SEARCH_PATH),
            params=params,
            timeout=float(query.get("timeout") or self.timeout_search),
        )
        features = [self._normalize_feature(f) for f in self._extract_features(payload)]
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

    def _get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 20.0,
    ) -> Dict[str, Any]:
        session = self.get_session()
        response = session.get(
            url,
            headers=self._headers(),
            params=params or {},
            timeout=timeout,
            verify=self._verify_ssl,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _normalize_collections(value: Any) -> Optional[List[str]]:
        if value is None:
            return None
        if isinstance(value, list):
            out = [str(v).strip() for v in value if str(v).strip()]
            return out or None
        text = str(value).strip()
        if not text:
            return None
        out = [p.strip() for p in text.split(",") if p.strip()]
        return out or None

    @staticmethod
    def _extract_features(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        for key in ("features", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [v for v in value if isinstance(v, dict)]
        return []

    @staticmethod
    def _extract_next_token(payload: Dict[str, Any]) -> Optional[str]:
        links = payload.get("links")
        if isinstance(links, list):
            for link in links:
                if not isinstance(link, dict):
                    continue
                if link.get("rel") == "next":
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


IceyeApiConnector = IceyeConnector

__all__ = ["IceyeConnector", "IceyeApiConnector"]
