from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import httpx

from . import config

log = logging.getLogger(__name__)


@dataclass
class Job:
    title: str
    company: str
    description: str
    url: str
    source: str
    location: str = ""
    category: str | None = None
    salary: str | None = None
    posted_date: str | None = None
    _dedup_key: str = field(init=False, repr=False)

    def __post_init__(self):
        self._dedup_key = f"{self.company.lower().strip()}|{self.title.lower().strip()}"

    def short_description(self, max_chars: int = 500) -> str:
        text = self.description.replace("\n", " ").strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rsplit(" ", 1)[0] + "..."


def _fetch_remotive(query: str, client: httpx.Client) -> list[tuple[int, Job]]:
    try:
        resp = client.get(
            "https://remotive.com/api/remote-jobs",
            params={"search": query, "limit": 20},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.warning("Remotive search failed for %r", query, exc_info=True)
        return []

    results = []
    for item in data.get("jobs", []):
        results.append((
            item["id"],
            Job(
                title=item["title"],
                company=item["company_name"],
                description=item.get("description", ""),
                url=item["url"],
                source="remotive",
                location=item.get("candidate_required_location", ""),
                category=item.get("category"),
                salary=item.get("salary"),
                posted_date=item.get("publication_date"),
            ),
        ))
    return results


def search_remotive(queries: list[str] | None = None) -> list[Job]:
    queries = queries or config.SEARCH_QUERIES
    jobs: list[Job] = []
    seen_ids: set[int] = set()

    with httpx.Client(timeout=30) as client:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(_fetch_remotive, q, client): q for q in queries}
            for future in as_completed(futures):
                for item_id, job in future.result():
                    if item_id not in seen_ids:
                        seen_ids.add(item_id)
                        jobs.append(job)

    log.info("Remotive: found %d jobs", len(jobs))
    return jobs


def _fetch_jsearch(query: str, client: httpx.Client, headers: dict, is_remote: bool) -> list[tuple[str, Job]]:
    try:
        params: dict[str, str] = {
            "query": f"{query} remote" if is_remote else f"{query} {config.LOCATION}",
            "page": "1",
            "num_pages": "1",
        }
        if is_remote:
            params["remote_jobs_only"] = "true"
        resp = client.get(
            "https://jsearch.p.rapidapi.com/search",
            headers=headers,
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.warning("JSearch failed for %r", query, exc_info=True)
        return []

    results = []
    for item in data.get("data", []) or []:
        job_id = item.get("job_id", "")
        salary = None
        if item.get("job_min_salary") and item.get("job_max_salary"):
            salary = f"${item['job_min_salary']:,.0f}–${item['job_max_salary']:,.0f}"

        location_parts = filter(None, [item.get("job_city"), item.get("job_state"), item.get("job_country")])
        results.append((
            job_id,
            Job(
                title=item.get("job_title", ""),
                company=item.get("employer_name", ""),
                description=item.get("job_description", ""),
                url=item.get("job_apply_link", ""),
                source="jsearch",
                location=", ".join(location_parts),
                salary=salary,
                posted_date=item.get("job_posted_at_datetime_utc"),
            ),
        ))
    return results


def search_jsearch(queries: list[str] | None = None) -> list[Job]:
    if not config.RAPIDAPI_KEY:
        log.info("RAPIDAPI_KEY not set — skipping JSearch")
        return []

    queries = queries or config.SEARCH_QUERIES
    jobs: list[Job] = []
    seen_ids: set[str] = set()

    headers = {
        "X-RapidAPI-Key": config.RAPIDAPI_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    is_remote = config.LOCATION.lower().strip() == "remote"

    with httpx.Client(timeout=30) as client:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(_fetch_jsearch, q, client, headers, is_remote): q for q in queries}
            for future in as_completed(futures):
                for job_id, job in future.result():
                    if job_id not in seen_ids:
                        seen_ids.add(job_id)
                        jobs.append(job)

    log.info("JSearch: found %d jobs", len(jobs))
    return jobs


def deduplicate(jobs: list[Job]) -> list[Job]:
    seen: dict[str, Job] = {}
    for job in jobs:
        key = job._dedup_key
        if key in seen:
            existing = seen[key]
            if len(job.description) > len(existing.description):
                seen[key] = job
        else:
            seen[key] = job
    deduped = list(seen.values())
    log.info("Deduplicated %d -> %d jobs", len(jobs), len(deduped))
    return deduped


def search_all(queries: list[str] | None = None) -> list[Job]:
    from .careers import search_all_career_sources
    from .startups import search_all_startups

    all_jobs: list[Job] = []
    if config.source_enabled("remotive"):
        all_jobs.extend(search_remotive(queries))
    if config.source_enabled("jsearch"):
        all_jobs.extend(search_jsearch(queries))
    all_jobs.extend(search_all_career_sources())
    all_jobs.extend(search_all_startups())
    return deduplicate(all_jobs)
