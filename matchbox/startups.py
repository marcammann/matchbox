from __future__ import annotations

import re
import logging

import httpx
from bs4 import BeautifulSoup

from . import config
from .search import Job

log = logging.getLogger(__name__)

HN_ALGOLIA = "https://hn.algolia.com/api/v1"


def _all_keywords() -> list[str]:
    return config.ROLE_KEYWORDS + config.STARTUP_ROLE_KEYWORDS


def _matches_startup_roles(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in _all_keywords())


def _extract_url(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(x in href for x in ["apply", "jobs", "careers", "lever.co", "greenhouse",
                                     "ashby", "workable", "breezy", "hire"]):
            return href
        if href.startswith("http") and "news.ycombinator" not in href:
            return href
    return ""


def _parse_hn_comment(comment: dict) -> Job | None:
    text = comment.get("comment_text", "")
    if not text or not _matches_startup_roles(text):
        return None

    soup = BeautifulSoup(text, "html.parser")
    plain = soup.get_text(separator="\n").strip()

    lines = plain.split("\n")
    first_line = lines[0] if lines else ""

    parts = [p.strip() for p in first_line.split("|")]
    company = parts[0] if len(parts) > 0 else ""
    title = ""
    location = ""

    keywords = _all_keywords()
    for part in parts[1:]:
        pl = part.lower()
        if any(kw in pl for kw in keywords):
            title = part
        elif any(loc in pl for loc in ["remote", "onsite", "hybrid", "sf", "nyc",
                                        "new york", "san francisco", "london", "berlin",
                                        "us ", "usa", "eu ", "worldwide"]):
            location = part
        elif not title:
            title = part
        elif not location:
            location = part

    if not title:
        title = first_line[:120]

    url = _extract_url(text)
    hn_url = f"https://news.ycombinator.com/item?id={comment.get('objectID', '')}"

    description = re.sub(r"\n{3,}", "\n\n", plain)[:5000]

    return Job(
        title=title or "Startup Role",
        company=company or "Unknown Startup",
        description=description,
        url=url or hn_url,
        source="hn_who_is_hiring",
        location=location,
        category="startup",
    )


def search_hn_who_is_hiring() -> list[Job]:
    with httpx.Client(timeout=30) as client:
        try:
            resp = client.get(
                f"{HN_ALGOLIA}/search_by_date",
                params={
                    "query": '"Ask HN: Who is hiring"',
                    "tags": "story,author_whoishiring",
                    "hitsPerPage": 1,
                },
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except Exception:
            log.warning("Failed to find HN Who is Hiring thread", exc_info=True)
            return []

        if not hits:
            log.warning("No HN Who is Hiring thread found")
            return []

        story = hits[0]
        story_id = story["objectID"]
        log.info("Found HN thread: %s (id=%s)", story.get("title"), story_id)

        jobs: list[Job] = []
        page = 0
        while True:
            try:
                resp = client.get(
                    f"{HN_ALGOLIA}/search",
                    params={
                        "tags": f"comment,story_{story_id}",
                        "numericFilters": f"parent_id={story_id}",
                        "hitsPerPage": 200,
                        "page": page,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                log.warning("Failed to fetch HN comments page %d", page, exc_info=True)
                break

            comments = data.get("hits", [])
            if not comments:
                break

            for comment in comments:
                job = _parse_hn_comment(comment)
                if job:
                    jobs.append(job)

            if page >= data.get("nbPages", 1) - 1:
                break
            page += 1

    log.info("HN Who is Hiring: found %d relevant roles from %s", len(jobs), story.get("title"))
    return jobs


def search_yc_jobs() -> list[Job]:
    jobs: list[Job] = []
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get("https://www.ycombinator.com/jobs", follow_redirects=True)
            resp.raise_for_status()
    except Exception:
        log.warning("Failed to fetch YC jobs page", exc_info=True)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    for link in soup.find_all("a", href=True):
        text = link.get_text(strip=True)
        if len(text) < 5 or len(text) > 200:
            continue
        if not _matches_startup_roles(text):
            continue

        href = link["href"]
        if href.startswith("/"):
            href = f"https://www.ycombinator.com{href}"
        if not href.startswith("http"):
            continue

        parent = link.find_parent(["div", "li", "article", "section"])
        context = parent.get_text(separator=" ", strip=True)[:500] if parent else text

        company = ""
        company_el = parent.find(class_=lambda c: c and ("company" in c.lower() or "org" in c.lower())) if parent else None
        if company_el:
            company = company_el.get_text(strip=True)
        if not company:
            for sibling_text in (context or "").split("|"):
                s = sibling_text.strip()
                if s and s != text and len(s) < 60:
                    company = s
                    break

        jobs.append(
            Job(
                title=text,
                company=company or "YC Startup",
                description=context,
                url=href,
                source="yc_jobs",
                location="",
                category="startup",
            )
        )

    log.info("YC Jobs: found %d leadership/founder roles", len(jobs))
    return jobs


def search_all_startups() -> list[Job]:
    hn_jobs = search_hn_who_is_hiring() if config.source_enabled("hn_who_is_hiring") else []
    yc_jobs = search_yc_jobs() if config.source_enabled("yc_jobs") else []
    total = hn_jobs + yc_jobs
    log.info("Startups total: %d jobs (%d HN, %d YC)", len(total), len(hn_jobs), len(yc_jobs))
    return total
