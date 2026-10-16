"""Candidate model and provider catalog reader without credential leakage."""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)


def sanitize_endpoint(url: Optional[str]) -> Optional[str]:
    """Strip authentication credentials, userinfo, and query parameters from endpoint URL."""
    if not url or not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        hostname = parts.hostname or ""
        netloc = f"{hostname}:{parts.port}" if parts.port else hostname
        path = parts.path.rstrip("/")
        if not parts.scheme and not netloc:
            return None
        return urlunsplit((parts.scheme, netloc, path, "", ""))
    except Exception:
        return None


def get_candidate_catalog(service: Any = None, runtime: Any = None) -> dict[str, Any]:
    """Read local model and provider candidate catalog without external calls or secret leakage.

    Zero-network and zero-RPC guarantee:
    - Never calls host RPC methods like model.options or model.list.
    - Never triggers custom provider probing or pricing prewarming.
    - Strictly reads local read-only config and service settings.
    - Hand-typing non-cached models is always supported.

    Returns:
        models: list of dicts with explicit allowlisted fields [{"model": str, "provider": Optional[str]}]
        providers: list of str names/slugs
        endpoint: sanitized endpoint string (no credentials) or None
    """
    candidate_models: list[dict[str, Optional[str]]] = []
    candidate_providers: set[str] = set()
    endpoint: Optional[str] = None

    # 1. Models and providers from service settings
    if service is not None:
        settings = getattr(service, "settings", {}) or {}
        for role in ("coordinator", "supervisor", "worker", "advisor"):
            m = settings.get(f"{role}_model")
            p = settings.get(f"{role}_provider")
            if m and isinstance(m, str) and m.strip():
                candidate_models.append({"model": m.strip(), "provider": p.strip() if p and isinstance(p, str) else None})
            if p and isinstance(p, str) and p.strip():
                candidate_providers.add(p.strip())

    # 2. Read host local configuration strictly read-only (zero network, no RPC)
    try:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly() or {}
        route = config.get("model") or {}
        default_prov = None
        if isinstance(route, dict):
            default_model = route.get("default") or route.get("name")
            default_prov = route.get("provider")
            if default_model and isinstance(default_model, str) and default_model.strip():
                candidate_models.append({
                    "model": default_model.strip(),
                    "provider": str(default_prov).strip() if default_prov else None,
                })
            if default_prov and isinstance(default_prov, str) and default_prov.strip():
                candidate_providers.add(default_prov.strip())
            if route.get("base_url"):
                endpoint = sanitize_endpoint(route.get("base_url"))

        raw_providers = config.get("providers", [])
        if isinstance(raw_providers, dict):
            for p_name in raw_providers:
                if isinstance(p_name, str) and p_name.strip():
                    candidate_providers.add(p_name.strip())
        elif isinstance(raw_providers, list):
            for p in raw_providers:
                if isinstance(p, dict):
                    name = str(p.get("id") or p.get("name") or "").strip()
                    if name:
                        candidate_providers.add(name)
                elif isinstance(p, str) and p.strip():
                    candidate_providers.add(p.strip())

        custom_providers = config.get("custom_providers", [])
        if isinstance(custom_providers, list):
            for cp in custom_providers:
                if isinstance(cp, dict):
                    name = str(cp.get("id") or cp.get("name") or "").strip()
                    if name:
                        candidate_providers.add(name)
                        for m in cp.get("models") or []:
                            if isinstance(m, str) and m.strip():
                                candidate_models.append({"model": m.strip(), "provider": name})
                            elif isinstance(m, dict) and m.get("id"):
                                candidate_models.append({"model": str(m["id"]).strip(), "provider": name})
                        if not endpoint and cp.get("base_url") and default_prov and name == default_prov:
                            endpoint = sanitize_endpoint(cp.get("base_url"))
    except Exception:
        pass

    # Deduplicate models preserving order
    seen: set[tuple[str, Optional[str]]] = set()
    deduped_models: list[dict[str, Optional[str]]] = []
    for item in candidate_models:
        m = item.get("model")
        if not m:
            continue
        key: tuple[str, Optional[str]] = (m, item.get("provider"))
        if key not in seen:
            seen.add(key)
            deduped_models.append(item)

    return {
        "models": deduped_models,
        "providers": sorted(candidate_providers),
        "endpoint": endpoint,
    }
