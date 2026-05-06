from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from bs4 import BeautifulSoup

from . import config
from .search import Job

log = logging.getLogger(__name__)


def _matches_role_keywords(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in config.ROLE_KEYWORDS)


def _fetch_greenhouse_board(board: dict, client: httpx.Client) -> list[Job]:
    try:
        resp = client.get(
            f"https://boards-api.greenhouse.io/v1/boards/{board['board_token']}/jobs",
            params={"content": "true"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.warning("Greenhouse failed for %s", board["company"], exc_info=True)
        return []

    jobs = []
    for item in data.get("jobs", []):
        title = item.get("title", "")
        if not _matches_role_keywords(title):
            continue

        location = ""
        locs = item.get("location", {})
        if isinstance(locs, dict):
            location = locs.get("name", "")

        content = item.get("content", "")
        if content:
            content = BeautifulSoup(content, "html.parser").get_text(separator="\n")

        jobs.append(
            Job(
                title=title,
                company=board["company"],
                description=content,
                url=item.get("absolute_url", ""),
                source="greenhouse",
                location=location,
                category=board.get("category"),
                posted_date=item.get("updated_at"),
            )
        )
    return jobs


def search_greenhouse_boards() -> list[Job]:
    jobs: list[Job] = []
    with httpx.Client(timeout=20) as client:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_fetch_greenhouse_board, b, client) for b in config.GREENHOUSE_BOARDS]
            for future in as_completed(futures):
                jobs.extend(future.result())
    log.info("Greenhouse: found %d leadership roles across %d boards", len(jobs), len(config.GREENHOUSE_BOARDS))
    return jobs


def _fetch_lever_board(board: dict, client: httpx.Client) -> list[Job]:
    try:
        resp = client.get(
            f"https://api.lever.co/v0/postings/{board['board_token']}",
            params={"mode": "json"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.warning("Lever failed for %s", board["company"], exc_info=True)
        return []

    jobs = []
    for item in data:
        title = item.get("text", "")
        if not _matches_role_keywords(title):
            continue

        location = ""
        cats = item.get("categories", {})
        if isinstance(cats, dict):
            location = cats.get("location", "")

        desc_parts = []
        for lst in item.get("lists", []):
            desc_parts.append(lst.get("text", ""))
            for li in lst.get("content", "").split("<li>"):
                clean = BeautifulSoup(li, "html.parser").get_text().strip()
                if clean:
                    desc_parts.append(f"- {clean}")

        description = item.get("descriptionPlain", "") or "\n".join(desc_parts)

        jobs.append(
            Job(
                title=title,
                company=board["company"],
                description=description,
                url=item.get("hostedUrl", ""),
                source="lever",
                location=location,
                category=board.get("category"),
                posted_date=None,
            )
        )
    return jobs


def search_lever_boards() -> list[Job]:
    jobs: list[Job] = []
    with httpx.Client(timeout=20) as client:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_fetch_lever_board, b, client) for b in config.LEVER_BOARDS]
            for future in as_completed(futures):
                jobs.extend(future.result())
    log.info("Lever: found %d leadership roles across %d boards", len(jobs), len(config.LEVER_BOARDS))
    return jobs


def _scrape_career_page(company: str, url: str, category: str, client: httpx.Client) -> list[Job]:
    try:
        resp = client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            log.debug("Career page %s returned %d", company, resp.status_code)
            return []
    except Exception:
        log.debug("Career page fetch failed for %s", company, exc_info=True)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    jobs: list[Job] = []

    for link in soup.find_all("a", href=True):
        text = link.get_text(strip=True)
        if len(text) < 5 or len(text) > 200:
            continue
        if not _matches_role_keywords(text):
            continue

        href = link["href"]
        if href.startswith("/"):
            from urllib.parse import urljoin
            href = urljoin(url, href)

        if not href.startswith("http"):
            continue

        parent = link.find_parent(["div", "li", "article", "section"])
        context = parent.get_text(separator=" ", strip=True)[:500] if parent else text

        jobs.append(
            Job(
                title=text,
                company=company,
                description=context,
                url=href,
                source="career_page",
                location="",
                category=category,
            )
        )

    return jobs


def search_career_pages() -> list[Job]:
    greenhouse_companies = {b["company"] for b in config.GREENHOUSE_BOARDS}
    lever_companies = {b["company"] for b in config.LEVER_BOARDS}
    skip = greenhouse_companies | lever_companies
    pages = [p for p in config.CAREER_PAGES if p["company"] not in skip]

    jobs: list[Job] = []
    with httpx.Client(timeout=20, headers={"User-Agent": "Mozilla/5.0"}) as client:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [
                pool.submit(_scrape_career_page, p["company"], p["url"], p.get("category", ""), client)
                for p in pages
            ]
            for future in as_completed(futures):
                jobs.extend(future.result())

    log.info("Career pages: found %d leadership roles across %d pages", len(jobs), len(pages))
    return jobs


def search_all_career_sources() -> list[Job]:
    greenhouse = search_greenhouse_boards() if config.source_enabled("greenhouse") else []
    lever = search_lever_boards() if config.source_enabled("lever") else []
    pages = search_career_pages() if config.source_enabled("career_pages") else []
    total = greenhouse + lever + pages
    log.info("All career sources: %d total (%d greenhouse, %d lever, %d pages)",
             len(total), len(greenhouse), len(lever), len(pages))
    return total
