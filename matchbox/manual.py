from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from . import config
from .match import MatchedJob
from .search import Job

log = logging.getLogger(__name__)


def _manual_file():
    return config.DATA_DIR / "manual_jobs.txt"


def _done_file():
    return config.DATA_DIR / ".manual_jobs_done.txt"


def _fetch_job_page(url: str, client: httpx.Client) -> tuple[str, str, str]:
    resp = client.get(url, follow_redirects=True)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)

    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = title or og_title["content"]

    page_title = soup.find("title")
    if page_title:
        title = title or page_title.get_text(strip=True)

    company = ""
    og_site = soup.find("meta", property="og:site_name")
    if og_site and og_site.get("content"):
        company = og_site["content"]

    if not company and " at " in title:
        company = title.split(" at ", 1)[1].strip()
    if not company and " - " in title:
        company = title.split(" - ", 1)[1].strip()
    if not company and " | " in title:
        company = title.split(" | ", 1)[1].strip()

    main = soup.find("main") or soup.find("article") or soup.find(role="main") or soup.body
    description = main.get_text(separator="\n", strip=True) if main else ""
    description = re.sub(r"\n{3,}", "\n\n", description)[:5000]

    return title, company, description


def load_manual_jobs() -> list[MatchedJob]:
    manual_file = _manual_file()
    if not manual_file.exists():
        return []

    done_file = _done_file()
    done_urls: set[str] = set()
    if done_file.exists():
        done_urls = {line.strip() for line in done_file.read_text().splitlines() if line.strip()}

    urls = [line.strip() for line in manual_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")]

    new_urls = [u for u in urls if u not in done_urls]
    if not new_urls:
        return []

    log.info("Processing %d manual job URLs", len(new_urls))
    matches: list[MatchedJob] = []

    with httpx.Client(timeout=20, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for url in new_urls:
            try:
                title, company, description = _fetch_job_page(url, client)
                log.info("Fetched manual job: %s at %s", title or "(no title)", company or "(unknown)")
            except Exception:
                log.warning("Failed to fetch manual job: %s", url, exc_info=True)
                title, company, description = "", "", ""

            job = Job(
                title=title or "Unknown Role",
                company=company or "Unknown Company",
                description=description,
                url=url,
                source="manual",
            )
            matches.append(MatchedJob(job=job, score=100, reason="Manually added"))

    return matches


def mark_manual_done(matches: list[MatchedJob]) -> None:
    if not matches:
        return
    urls = [m.job.url for m in matches if m.job.source == "manual"]
    if not urls:
        return
    done_file = _done_file()
    with done_file.open("a") as f:
        for url in urls:
            f.write(url + "\n")
    log.info("Marked %d manual jobs as done", len(urls))
