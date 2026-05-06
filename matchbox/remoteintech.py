from __future__ import annotations

import io
import json
import logging
import tarfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import httpx
import yaml

from . import config

log = logging.getLogger(__name__)

TARBALL_URL = "https://github.com/remoteintech/remote-jobs/archive/refs/heads/main.tar.gz"
CACHE_PATH = config.DATA_DIR / ".remoteintech_cache.json"
TTL_HOURS = 24


@dataclass
class RemoteCompany:
    name: str
    slug: str
    website: str = ""
    careers_url: str = ""
    region: str = ""
    remote_policy: str = ""
    company_size: str = ""
    technologies: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------
_cache: list[RemoteCompany] | None = None
_cache_time: datetime | None = None


def _cache_is_fresh() -> bool:
    if _cache is None or _cache_time is None:
        return False
    age = (datetime.now(timezone.utc) - _cache_time).total_seconds()
    return age < TTL_HOURS * 3600


# ---------------------------------------------------------------------------
# Disk cache (cold-start)
# ---------------------------------------------------------------------------
def _load_disk_cache() -> list[RemoteCompany] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        data = json.loads(CACHE_PATH.read_text())
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age >= TTL_HOURS * 3600:
            log.debug("Disk cache expired (%.1f h old)", age / 3600)
            return None
        companies = [RemoteCompany(**item) for item in data["companies"]]
        log.info("Loaded %d companies from disk cache", len(companies))
        return companies
    except Exception:
        log.warning("Failed to read disk cache", exc_info=True)
        return None


def _save_disk_cache(companies: list[RemoteCompany]) -> None:
    try:
        payload = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "companies": [asdict(c) for c in companies],
        }
        CACHE_PATH.write_text(json.dumps(payload, indent=2))
        log.debug("Wrote %d companies to disk cache", len(companies))
    except Exception:
        log.warning("Failed to write disk cache", exc_info=True)


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------
def _parse_frontmatter(content: str) -> RemoteCompany | None:
    content = content.strip()
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None
    fm_text = content[3:end].strip()
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None

    name = fm.get("title") or fm.get("name") or ""
    slug = fm.get("slug") or ""
    if not name and not slug:
        return None

    technologies = fm.get("technologies") or []
    if isinstance(technologies, str):
        technologies = [t.strip() for t in technologies.split(",") if t.strip()]

    return RemoteCompany(
        name=str(name),
        slug=str(slug),
        website=str(fm.get("website") or ""),
        careers_url=str(fm.get("careers_url") or fm.get("careers") or ""),
        region=str(fm.get("region") or ""),
        remote_policy=str(fm.get("remote_policy") or ""),
        company_size=str(fm.get("company_size") or ""),
        technologies=[str(t) for t in technologies],
    )


# ---------------------------------------------------------------------------
# Tarball fetch + parse
# ---------------------------------------------------------------------------
def _fetch_and_parse() -> list[RemoteCompany]:
    log.info("Downloading Remote In Tech company list from GitHub...")
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get(TARBALL_URL)
        resp.raise_for_status()

    companies: list[RemoteCompany] = []
    buf = io.BytesIO(resp.content)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            if not member.name.endswith(".md"):
                continue
            # Only files under the companies directory
            parts = member.name.split("/")
            if "companies" not in parts:
                continue

            f = tar.extractfile(member)
            if f is None:
                continue
            content = f.read().decode("utf-8", errors="replace")
            company = _parse_frontmatter(content)
            if company:
                companies.append(company)

    log.info("Parsed %d companies from Remote In Tech", len(companies))
    return companies


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_companies() -> list[RemoteCompany]:
    global _cache, _cache_time

    if _cache_is_fresh():
        return _cache  # type: ignore[return-value]

    # Try disk cache on cold start
    disk = _load_disk_cache()
    if disk is not None:
        _cache = disk
        _cache_time = datetime.now(timezone.utc)
        return _cache

    # Fetch fresh data
    try:
        companies = _fetch_and_parse()
    except Exception:
        log.error("Failed to fetch Remote In Tech data", exc_info=True)
        if _cache is not None:
            log.warning("Returning stale in-memory cache")
            return _cache
        return []

    _cache = companies
    _cache_time = datetime.now(timezone.utc)
    _save_disk_cache(companies)
    return _cache
