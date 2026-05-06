from __future__ import annotations

import logging
import tempfile
import threading
from datetime import date
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from starlette.staticfiles import StaticFiles

from . import config
from .db import (
    delete_application,
    get_application,
    get_existing_dedup_keys,
    get_job,
    get_jobs_grouped,
    init_db,
    save_application,
    save_manual_job,
    save_matched_jobs,
    update_job_status,
)
from .careers import search_ashby_boards, search_career_pages, search_greenhouse_boards, search_lever_boards
from .match import match_jobs
from .pdf import markdown_to_pdf
from .search import deduplicate, search_jsearch, search_remotive
from .startups import search_hn_who_is_hiring, search_yc_jobs
from .tailor import _humanize

log = logging.getLogger(__name__)


def _get_llm() -> ChatAnthropic:
    return ChatAnthropic(model=config.MODEL, api_key=config.ANTHROPIC_API_KEY, max_tokens=4096)


class CompanyDiscovery(BaseModel):
    source: Literal["greenhouse", "lever", "ashby", "career_page"]
    board_token: str = Field(description="Board token for greenhouse/lever/ashby, empty string otherwise")
    url: str = Field(description="Careers page URL")
    confidence: Literal["high", "medium", "low"]


class JobExtraction(BaseModel):
    title: str
    company: str
    description: str = Field(description="2-4 paragraph summary of the role")
    location: str


class ProfileGeneration(BaseModel):
    profile: str
    target_roles: str
    search_queries: list[str]


app = FastAPI(title="Job Search Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_search_state = {
    "status": "idle",
    "message": "",
    "progress": 0,
    "jobs_found": 0,
    "matches": 0,
    "errors": [],
}
_search_lock = threading.Lock()


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except Exception:
            return await super().get_response("index.html", scope)


@app.on_event("startup")
def startup():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    init_db()


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return ""
    return "*" * (len(key) - 4) + key[-4:]


# --- Config ---

@app.get("/api/config")
def get_config_endpoint():
    cfg = config.get_raw_config()
    safe = dict(cfg)

    api_keys = dict(safe.get("api_keys", {}))
    safe["api_keys"] = {
        "anthropic": _mask_key(api_keys.get("anthropic", "")),
        "rapidapi": _mask_key(api_keys.get("rapidapi", "")),
    }
    if not api_keys.get("anthropic") and config.ANTHROPIC_API_KEY:
        safe["api_keys"]["anthropic_env"] = True
    if not api_keys.get("rapidapi") and config.RAPIDAPI_KEY:
        safe["api_keys"]["rapidapi_env"] = True

    prompts = safe.get("prompts", {})
    safe["prompts"] = {
        "matching": prompts.get("matching", "") or config._DEFAULT_MATCHING,
        "resume_tailoring": prompts.get("resume_tailoring", "") or config._DEFAULT_RESUME,
        "cover_letter": prompts.get("cover_letter", "") or config._DEFAULT_COVER_LETTER,
        "humanize": prompts.get("humanize", "") or config._DEFAULT_HUMANIZE,
    }

    return safe


@app.put("/api/config")
async def update_config_endpoint(request: Request):
    body = await request.json()
    current = config.get_raw_config()

    if "api_keys" in body:
        new_keys = body.pop("api_keys")
        current_keys = dict(current.get("api_keys", {}))
        for key_name in ["anthropic", "rapidapi"]:
            val = new_keys.get(key_name, "")
            if val and not val.startswith("*"):
                current_keys[key_name] = val
        current["api_keys"] = current_keys

    current.update(body)
    config.save_config(current)
    return {"status": "ok"}


# --- Company Discovery ---

def _try_greenhouse(token: str, expected_company: str | None = None) -> bool:
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
            if resp.status_code != 200:
                return False
            data = resp.json()
            if len(data.get("jobs", [])) == 0:
                return False
            if expected_company:
                board = client.get(f"https://boards-api.greenhouse.io/v1/boards/{token}")
                if board.status_code == 200:
                    board_name = board.json().get("name", "").lower()
                    if expected_company.lower() not in board_name and board_name not in expected_company.lower():
                        log.info("Greenhouse token %r belongs to %r, not %r", token, board_name, expected_company)
                        return False
            return True
    except Exception:
        pass
    return False


def _try_lever(token: str, expected_company: str | None = None) -> bool:
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"})
            if resp.status_code != 200:
                return False
            data = resp.json()
            return isinstance(data, list) and len(data) > 0
    except Exception:
        pass
    return False


def _try_ashby(token: str, expected_company: str | None = None) -> bool:
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
            if resp.status_code != 200:
                return False
            data = resp.json()
            return len(data.get("jobs", [])) > 0
    except Exception:
        pass
    return False


def _try_remoteintech(company: str) -> str | None:
    """Look up a company on remoteintech.company and return its careers URL if found."""
    slug = company.lower().strip().replace(" ", "-").replace(".", "").replace(",", "")
    url = f"https://raw.githubusercontent.com/remoteintech/remote-jobs/main/src/companies/{slug}.md"
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return None
            for line in resp.text.splitlines():
                if line.strip().startswith("careers_url:"):
                    careers = line.split(":", 1)[1].strip()
                    if careers.startswith("http"):
                        return careers
    except Exception:
        pass
    return None


def _token_variants(company: str) -> list[str]:
    name = company.lower().strip()
    slug = name.replace(" ", "").replace(".", "").replace(",", "")
    hyphenated = name.replace(" ", "-").replace(".", "").replace(",", "")
    underscored = name.replace(" ", "_").replace(".", "").replace(",", "")
    seen = set()
    variants = []
    for v in [slug, hyphenated, underscored, name.split()[0].lower() if name.split() else slug]:
        if v not in seen:
            seen.add(v)
            variants.append(v)
    return variants


def _extract_ats_from_url(url: str) -> tuple[str | None, str | None, str | None]:
    """Detect Greenhouse/Lever board tokens from a URL. Returns (ats, token, company_guess)."""
    import re
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or ""

    # boards.greenhouse.io/TOKEN or job-boards.greenhouse.io/TOKEN
    if "greenhouse.io" in host:
        m = re.match(r"^/([a-zA-Z0-9_-]+)", parsed.path)
        if m:
            return "greenhouse", m.group(1), m.group(1).replace("-", " ").title()

    # jobs.lever.co/TOKEN
    if "lever.co" in host:
        m = re.match(r"^/([a-zA-Z0-9_-]+)", parsed.path)
        if m:
            return "lever", m.group(1), m.group(1).replace("-", " ").title()

    # jobs.ashbyhq.com/TOKEN
    if "ashbyhq.com" in host:
        m = re.match(r"^/([a-zA-Z0-9_-]+)", parsed.path)
        if m:
            return "ashby", m.group(1), m.group(1).replace("-", " ").title()

    return None, None, None


def _company_name_from_url(url: str) -> str:
    """Best-effort company name from a careers page URL."""
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    host = host.removeprefix("www.").removeprefix("jobs.").removeprefix("careers.")
    name = host.split(".")[0] if host else "Unknown"
    return name.replace("-", " ").title()


@app.post("/api/companies/discover")
async def discover_company(request: Request):
    body = await request.json()
    company = (body.get("company") or "").strip()
    if not company:
        raise HTTPException(400, "Company name or URL is required")

    config.reload_config()

    existing_companies = set()
    for b in config.GREENHOUSE_BOARDS:
        existing_companies.add(b["company"].lower())
    for b in config.LEVER_BOARDS:
        existing_companies.add(b["company"].lower())
    for b in config.ASHBY_BOARDS:
        existing_companies.add(b["company"].lower())
    for p in config.CAREER_PAGES:
        existing_companies.add(p["company"].lower())
    existing_urls = {p["url"].rstrip("/").lower() for p in config.CAREER_PAGES}

    is_url = company.startswith("http://") or company.startswith("https://")

    if is_url:
        if company.rstrip("/").lower() in existing_urls:
            return {"status": "exists", "message": "This URL is already configured."}

        ats, token, name_guess = _extract_ats_from_url(company)

        if ats == "greenhouse" and token and _try_greenhouse(token):
            board_name = name_guess or token
            try:
                with httpx.Client(timeout=10) as c:
                    r = c.get(f"https://boards-api.greenhouse.io/v1/boards/{token}")
                    if r.status_code == 200:
                        board_name = r.json().get("name", board_name)
            except Exception:
                pass
            if board_name.lower() in existing_companies:
                return {"status": "exists", "message": f"{board_name} is already configured."}
            cfg = config.get_raw_config()
            cfg.setdefault("greenhouse_boards", []).append({
                "company": board_name, "board_token": token, "category": "",
            })
            config.save_config(cfg)
            return {
                "status": "added", "source": "greenhouse", "board_token": token,
                "message": f"Found {board_name} on Greenhouse (token: {token}).",
            }

        if ats == "lever" and token and _try_lever(token):
            lever_name = name_guess or token
            if lever_name.lower() in existing_companies:
                return {"status": "exists", "message": f"{lever_name} is already configured."}
            cfg = config.get_raw_config()
            cfg.setdefault("lever_boards", []).append({
                "company": lever_name, "board_token": token, "category": "",
            })
            config.save_config(cfg)
            return {
                "status": "added", "source": "lever", "board_token": token,
                "message": f"Found {lever_name} on Lever (token: {token}).",
            }

        if ats == "ashby" and token and _try_ashby(token):
            ashby_name = name_guess or token
            if ashby_name.lower() in existing_companies:
                return {"status": "exists", "message": f"{ashby_name} is already configured."}
            cfg = config.get_raw_config()
            cfg.setdefault("ashby_boards", []).append({
                "company": ashby_name, "board_token": token, "category": "",
            })
            config.save_config(cfg)
            return {
                "status": "added", "source": "ashby", "board_token": token,
                "message": f"Found {ashby_name} on Ashby (token: {token}).",
            }

        page_company = _company_name_from_url(company)
        if page_company.lower() in existing_companies:
            return {"status": "exists", "message": f"{page_company} is already configured."}
        cfg = config.get_raw_config()
        cfg.setdefault("career_pages", []).append({
            "company": page_company, "url": company, "category": "",
        })
        config.save_config(cfg)
        return {
            "status": "added", "source": "career_page", "url": company,
            "message": f"Added {page_company} careers page. Note: JS-rendered pages may have limited results.",
        }

    if company.lower() in existing_companies:
        return {"status": "exists", "message": f"{company} is already configured."}

    tokens = _token_variants(company)

    for token in tokens:
        if _try_greenhouse(token, company):
            cfg = config.get_raw_config()
            cfg.setdefault("greenhouse_boards", []).append({
                "company": company,
                "board_token": token,
                "category": "",
            })
            config.save_config(cfg)
            return {
                "status": "added",
                "source": "greenhouse",
                "board_token": token,
                "message": f"Found {company} on Greenhouse (token: {token}).",
            }

    for token in tokens:
        if _try_lever(token, company):
            cfg = config.get_raw_config()
            cfg.setdefault("lever_boards", []).append({
                "company": company,
                "board_token": token,
                "category": "",
            })
            config.save_config(cfg)
            return {
                "status": "added",
                "source": "lever",
                "board_token": token,
                "message": f"Found {company} on Lever (token: {token}).",
            }

    for token in tokens:
        if _try_ashby(token, company):
            cfg = config.get_raw_config()
            cfg.setdefault("ashby_boards", []).append({
                "company": company,
                "board_token": token,
                "category": "",
            })
            config.save_config(cfg)
            return {
                "status": "added",
                "source": "ashby",
                "board_token": token,
                "message": f"Found {company} on Ashby (token: {token}).",
            }

    careers_url = _try_remoteintech(company) if config.LOCATION.lower().strip() == "remote" else None
    if careers_url:
        ats, ats_token, _ = _extract_ats_from_url(careers_url)
        if ats == "greenhouse" and ats_token and _try_greenhouse(ats_token, company):
            cfg = config.get_raw_config()
            cfg.setdefault("greenhouse_boards", []).append({
                "company": company, "board_token": ats_token, "category": "",
            })
            config.save_config(cfg)
            return {
                "status": "added", "source": "greenhouse", "board_token": ats_token,
                "message": f"Found {company} on Greenhouse via Remote In Tech (token: {ats_token}).",
            }
        if ats == "lever" and ats_token and _try_lever(ats_token, company):
            cfg = config.get_raw_config()
            cfg.setdefault("lever_boards", []).append({
                "company": company, "board_token": ats_token, "category": "",
            })
            config.save_config(cfg)
            return {
                "status": "added", "source": "lever", "board_token": ats_token,
                "message": f"Found {company} on Lever via Remote In Tech (token: {ats_token}).",
            }
        if ats == "ashby" and ats_token and _try_ashby(ats_token, company):
            cfg = config.get_raw_config()
            cfg.setdefault("ashby_boards", []).append({
                "company": company, "board_token": ats_token, "category": "",
            })
            config.save_config(cfg)
            return {
                "status": "added", "source": "ashby", "board_token": ats_token,
                "message": f"Found {company} on Ashby via Remote In Tech (token: {ats_token}).",
            }
        cfg = config.get_raw_config()
        cfg.setdefault("career_pages", []).append({
            "company": company, "url": careers_url, "category": "",
        })
        config.save_config(cfg)
        return {
            "status": "added", "source": "career_page", "url": careers_url,
            "message": f"Added {company} careers page via Remote In Tech: {careers_url}",
        }

    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(400, "Anthropic API key needed to discover career pages")

    try:
        llm = _get_llm().with_structured_output(CompanyDiscovery)
        result: CompanyDiscovery = llm.invoke([HumanMessage(content=(
            f"I need to find where {company} lists its job openings.\n\n"
            "Check these possibilities in order:\n"
            "1. Greenhouse job board — the board token is usually in URLs like "
            "boards.greenhouse.io/COMPANY or boards-api.greenhouse.io/v1/boards/COMPANY/jobs. "
            "Common tokens: company name lowercase, with hyphens, abbreviations, or parent company name.\n"
            "2. Lever job board — tokens appear in URLs like jobs.lever.co/COMPANY. "
            "Similar naming conventions.\n"
            "3. Ashby job board — tokens appear in URLs like jobs.ashbyhq.com/COMPANY.\n"
            "4. Workday or other ATS — provide the careers/jobs listing URL.\n"
            "5. Direct careers page on their website.\n\n"
            "IMPORTANT: Only suggest Greenhouse, Lever, or Ashby if you are confident the company "
            "actually uses that platform. Many large companies use their own ATS (Workday, "
            "iCIMS, Taleo, etc.) — for those, return the careers page URL instead."
        ))])
    except Exception:
        log.warning("Company discovery failed for %s", company, exc_info=True)
        raise HTTPException(500, "Failed to discover job listings source")

    source = result.source
    token = result.board_token
    url = result.url
    confidence = result.confidence

    if source == "greenhouse" and token:
        if _try_greenhouse(token, company):
            cfg = config.get_raw_config()
            cfg.setdefault("greenhouse_boards", []).append({
                "company": company,
                "board_token": token,
                "category": "",
            })
            config.save_config(cfg)
            return {
                "status": "added",
                "source": "greenhouse",
                "board_token": token,
                "message": f"Found {company} on Greenhouse (token: {token}).",
            }

    if source == "lever" and token:
        if _try_lever(token, company):
            cfg = config.get_raw_config()
            cfg.setdefault("lever_boards", []).append({
                "company": company,
                "board_token": token,
                "category": "",
            })
            config.save_config(cfg)
            return {
                "status": "added",
                "source": "lever",
                "board_token": token,
                "message": f"Found {company} on Lever (token: {token}).",
            }

    if source == "ashby" and token:
        if _try_ashby(token, company):
            cfg = config.get_raw_config()
            cfg.setdefault("ashby_boards", []).append({
                "company": company,
                "board_token": token,
                "category": "",
            })
            config.save_config(cfg)
            return {
                "status": "added",
                "source": "ashby",
                "board_token": token,
                "message": f"Found {company} on Ashby (token: {token}).",
            }

    if url:
        cfg = config.get_raw_config()
        cfg.setdefault("career_pages", []).append({
            "company": company,
            "url": url,
            "category": "",
        })
        config.save_config(cfg)
        return {
            "status": "added",
            "source": "career_page",
            "url": url,
            "confidence": confidence,
            "message": f"Added {company} careers page: {url} (confidence: {confidence}).",
        }

    raise HTTPException(404, f"Could not find job listings for {company}")


# --- Remote In Tech ---

class TechMatch(BaseModel):
    matched_technologies: list[str]


@app.get("/api/remoteintech/companies")
def list_remote_companies():
    from .remoteintech import get_companies
    companies = get_companies()
    techs = sorted({t for c in companies for t in c.technologies})
    return {
        "companies": [
            {
                "name": c.name, "slug": c.slug, "website": c.website,
                "careers_url": c.careers_url, "region": c.region,
                "remote_policy": c.remote_policy, "company_size": c.company_size,
                "technologies": c.technologies,
            }
            for c in companies
        ],
        "available_technologies": techs,
    }


@app.post("/api/remoteintech/match-technologies")
def match_technologies():
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(400, "Anthropic API key required")

    from .remoteintech import get_companies
    companies = get_companies()
    all_techs = sorted({t for c in companies for t in c.technologies})

    resume = ""
    if config.RESUME_PATH.exists():
        resume = config.RESUME_PATH.read_text()
    profile = config.PROFILE or ""

    if not resume and not profile:
        raise HTTPException(400, "No resume or profile configured")

    llm = _get_llm().with_structured_output(TechMatch)
    result: TechMatch = llm.invoke([HumanMessage(content=(
        f"Given this candidate's background, select ALL technology tags they have experience with.\n\n"
        f"## Available tags\n{', '.join(all_techs)}\n\n"
        f"## Candidate profile\n{profile}\n\n"
        f"## Resume\n{resume[:3000]}\n\n"
        "Return every tag where the candidate has meaningful experience."
    ))])
    return {"matched_technologies": result.matched_technologies}


@app.post("/api/remoteintech/add-companies")
async def add_remote_companies(request: Request):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    body = await request.json()
    companies_to_add = body.get("companies", [])
    if not companies_to_add:
        raise HTTPException(400, "No companies provided")

    config.reload_config()
    existing = set()
    for b in config.GREENHOUSE_BOARDS:
        existing.add(b["company"].lower())
    for b in config.LEVER_BOARDS:
        existing.add(b["company"].lower())
    for p in config.CAREER_PAGES:
        existing.add(p["company"].lower())

    def _add_one(comp: dict) -> dict:
        name = comp["name"]
        careers_url = comp.get("careers_url", "")

        if name.lower() in existing:
            return {"name": name, "status": "exists", "message": f"{name} already configured."}

        if careers_url:
            ats, token, _ = _extract_ats_from_url(careers_url)
            if ats == "greenhouse" and token and _try_greenhouse(token, name):
                return {"name": name, "status": "added", "source": "greenhouse",
                        "board_token": token, "message": f"Greenhouse ({token})"}
            if ats == "lever" and token and _try_lever(token, name):
                return {"name": name, "status": "added", "source": "lever",
                        "board_token": token, "message": f"Lever ({token})"}
            if ats == "ashby" and token and _try_ashby(token, name):
                return {"name": name, "status": "added", "source": "ashby",
                        "board_token": token, "message": f"Ashby ({token})"}
            return {"name": name, "status": "added", "source": "career_page",
                    "url": careers_url, "message": f"Career page"}

        return {"name": name, "status": "skipped", "message": "No careers URL available."}

    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_add_one, c): c for c in companies_to_add}
        for future in as_completed(futures):
            results.append(future.result())

    cfg = config.get_raw_config()
    for r in results:
        if r["status"] != "added":
            continue
        name = r["name"]
        if r["source"] == "greenhouse":
            cfg.setdefault("greenhouse_boards", []).append({
                "company": name, "board_token": r["board_token"], "category": "",
            })
        elif r["source"] == "lever":
            cfg.setdefault("lever_boards", []).append({
                "company": name, "board_token": r["board_token"], "category": "",
            })
        elif r["source"] == "ashby":
            cfg.setdefault("ashby_boards", []).append({
                "company": name, "board_token": r["board_token"], "category": "",
            })
        elif r["source"] == "career_page":
            cfg.setdefault("career_pages", []).append({
                "company": name, "url": r["url"], "category": "",
            })
    config.save_config(cfg)

    added_count = sum(1 for r in results if r["status"] == "added")
    return {"results": results, "added": added_count}


# --- Resume ---

@app.get("/api/resume")
def get_resume():
    if config.RESUME_PATH.exists():
        return {"content": config.RESUME_PATH.read_text(), "path": str(config.RESUME_PATH)}
    return {"content": "", "path": str(config.RESUME_PATH)}


@app.post("/api/resume")
async def upload_resume(file: UploadFile):
    content = await file.read()
    text = content.decode("utf-8")
    config.RESUME_PATH.write_text(text)
    return {"status": "ok", "size": len(text)}


@app.put("/api/resume")
async def update_resume(request: Request):
    body = await request.json()
    content = body.get("content", "")
    config.RESUME_PATH.write_text(content)
    return {"status": "ok", "size": len(content)}


# --- Search ---

class _SearchWarningCollector(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.warnings: list[str] = []

    def emit(self, record: logging.LogRecord):
        self.warnings.append(record.getMessage())


def _run_search():
    collector = _SearchWarningCollector()
    logging.getLogger("matchbox").addHandler(collector)
    try:
        _search_state.update(status="running", message="Loading config...", progress=2, jobs_found=0, matches=0, errors=[])
        config.reload_config()

        all_jobs = []
        sources_plan = []
        s = config.SOURCES

        if s.get("remotive", True):
            sources_plan.append(("Remotive", f"{len(config.SEARCH_QUERIES)} queries", lambda: search_remotive()))
        if s.get("jsearch", True):
            sources_plan.append(("JSearch", f"{len(config.SEARCH_QUERIES)} queries", lambda: search_jsearch()))
        if s.get("greenhouse", True):
            sources_plan.append(("Greenhouse", f"{len(config.GREENHOUSE_BOARDS)} boards", lambda: search_greenhouse_boards()))
        if s.get("lever", True):
            sources_plan.append(("Lever", f"{len(config.LEVER_BOARDS)} boards", lambda: search_lever_boards()))
        if s.get("ashby", True):
            sources_plan.append(("Ashby", f"{len(config.ASHBY_BOARDS)} boards", lambda: search_ashby_boards()))
        if s.get("career_pages", True):
            n = len([p for p in config.CAREER_PAGES
                     if p["company"] not in {b["company"] for b in config.GREENHOUSE_BOARDS}
                        and p["company"] not in {b["company"] for b in config.LEVER_BOARDS}])
            sources_plan.append(("Career pages", f"{n} sites", lambda: search_career_pages()))
        if s.get("hn_who_is_hiring", True):
            sources_plan.append(("HN Who is Hiring", "", lambda: search_hn_who_is_hiring()))
        if s.get("yc_jobs", True):
            sources_plan.append(("YC Jobs", "", lambda: search_yc_jobs()))

        if not sources_plan:
            _search_state.update(status="done", message="No sources enabled.", progress=100)
            return

        total = len(sources_plan)
        for i, (name, detail, fn) in enumerate(sources_plan):
            label = f"{name} ({detail})" if detail else name
            _search_state.update(
                message=f"Searching {label}... ({i + 1}/{total})",
                progress=5 + int(55 * i / total),
            )
            try:
                all_jobs.extend(fn())
            except Exception:
                log.warning("%s: source failed entirely", name, exc_info=True)

        jobs = deduplicate(all_jobs)
        _search_state["jobs_found"] = len(jobs)
        _search_state.update(message=f"Found {len(jobs)} jobs. Filtering...", progress=65)

        existing_keys = get_existing_dedup_keys()
        new_jobs = [j for j in jobs if j._dedup_key not in existing_keys]

        matched_count = 0
        if new_jobs:
            _search_state.update(message=f"Scoring {len(new_jobs)} new jobs...", progress=70)
            scored = match_jobs(new_jobs)
            matched_count = sum(1 for m in scored if m.score >= config.MATCH_THRESHOLD)
            _search_state["matches"] = matched_count
            _search_state.update(message=f"Saving {len(scored)} scored jobs...", progress=90)
            save_matched_jobs(scored)
        else:
            _search_state.update(message="No new jobs to score.", progress=90)

        _search_state["errors"] = collector.warnings
        msg = f"Done: {len(jobs)} total, {len(new_jobs)} new, {matched_count} matches."
        if collector.warnings:
            msg += f" ({len(collector.warnings)} warning{'s' if len(collector.warnings) > 1 else ''})"
        _search_state.update(status="done", message=msg, progress=100)
    except Exception as e:
        log.error("Search failed", exc_info=True)
        _search_state["errors"] = collector.warnings
        _search_state.update(status="error", message=str(e))
    finally:
        logging.getLogger("matchbox").removeHandler(collector)


@app.post("/api/search")
def start_search():
    config.reload_config()
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(400, "Anthropic API key not configured. Add it in Settings first.")
    if _search_state["status"] == "running":
        raise HTTPException(400, "Search already running")

    with _search_lock:
        _search_state.update(status="starting", message="Initializing...", progress=0)
        thread = threading.Thread(target=_run_search, daemon=True)
        thread.start()

    return {"status": "started"}


@app.get("/api/search/status")
def search_status():
    return dict(_search_state)


# --- Jobs ---

@app.get("/api/jobs")
def list_jobs():
    config.reload_config()
    return {
        "threshold": config.MATCH_THRESHOLD,
        "groups": get_jobs_grouped(),
    }


@app.get("/api/jobs/{job_id}")
def get_job_detail(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    app_data = get_application(job_id)
    job["application"] = app_data
    return job


@app.patch("/api/jobs/{job_id}")
async def patch_job(job_id: int, request: Request):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    body = await request.json()
    status = body.get("status")
    if status not in ("open", "applied", "dismissed"):
        raise HTTPException(400, "Status must be open, applied, or dismissed")

    update_job_status(job_id, status)
    return {"status": "ok"}


# --- Manual Job Addition ---

def _fetch_page(url: str) -> str:
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            return resp.text
    except Exception:
        raise HTTPException(400, "Could not fetch the URL")


def _extract_from_structured_data(html: str) -> JobExtraction | None:
    import json as _json
    import re
    from bs4 import BeautifulSoup

    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            data = _json.loads(m.group(1))
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type") == "JobPosting"), None)
            if not data or data.get("@type") != "JobPosting":
                continue
            desc_html = data.get("description", "")
            desc_text = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n", strip=True) if desc_html else ""
            location = ""
            loc_data = data.get("jobLocation")
            if isinstance(loc_data, dict):
                addr = loc_data.get("address", {})
                parts = [addr.get("addressLocality", ""), addr.get("addressRegion", ""), addr.get("addressCountry", "")]
                location = ", ".join(p for p in parts if p and p.upper() != "UNAVAILABLE")
            elif isinstance(loc_data, str):
                location = loc_data
            company = ""
            org = data.get("hiringOrganization")
            if isinstance(org, dict):
                company = org.get("name", "")
            elif isinstance(org, str):
                company = org
            return JobExtraction(
                title=data.get("title", ""),
                company=company,
                description=desc_text[:4000],
                location=location or data.get("jobLocationType", ""),
            )
        except Exception:
            continue
    return None


def _extract_from_url(url: str) -> JobExtraction:
    html = _fetch_page(url)

    structured = _extract_from_structured_data(html)
    if structured and structured.title and structured.company:
        return structured

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html[:15000], "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text_content = soup.get_text(separator="\n", strip=True)[:8000]

    if not text_content.strip():
        og_title = soup.find("meta", property="og:title")
        og_desc = soup.find("meta", property="og:description")
        if og_title:
            text_content = f"Title: {og_title.get('content', '')}\n"
        if og_desc:
            text_content += f"Description: {og_desc.get('content', '')}\n"

    try:
        llm = _get_llm().with_structured_output(JobExtraction)
        return llm.invoke([HumanMessage(content=(
            f"Extract job posting details from this page content.\n\nURL: {url}\n\n## Page content\n{text_content}"
        ))])
    except Exception:
        log.warning("AI extraction failed for %s", url, exc_info=True)
        raise HTTPException(500, "Failed to extract job details from URL")


@app.post("/api/jobs/extract")
async def extract_job(request: Request):
    body = await request.json()
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "URL is required")

    config.reload_config()
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(400, "Anthropic API key needed to extract job details from URL")

    extracted = _extract_from_url(url)
    return {
        "title": extracted.title,
        "company": extracted.company,
        "description": extracted.description,
        "location": extracted.location,
    }


@app.post("/api/jobs")
async def add_manual_job(request: Request):
    body = await request.json()
    url = (body.get("url") or "").strip()
    title = (body.get("title") or "").strip()
    company = (body.get("company") or "").strip()
    description = (body.get("description") or "").strip()
    location = (body.get("location") or "").strip()

    if url and not (title and company):
        config.reload_config()
        if not config.ANTHROPIC_API_KEY:
            raise HTTPException(400, "Anthropic API key needed to extract job details from URL")

        extracted = _extract_from_url(url)
        title = title or extracted.title
        company = company or extracted.company
        description = description or extracted.description
        location = location or extracted.location

    if not title or not company:
        raise HTTPException(400, "Title and company are required")

    job_id = save_manual_job(
        title=title, company=company, description=description,
        url=url, location=location, score=0, reason="Manually added",
    )
    return {"status": "created", "job_id": job_id}


# --- Profile Generation ---

@app.post("/api/generate-profile")
async def generate_profile(request: Request):
    body = await request.json()
    resume_text = body.get("resume", "")
    if not resume_text.strip():
        raise HTTPException(400, "Resume text is required")

    config.reload_config()
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(400, "Anthropic API key not configured")

    try:
        llm = _get_llm().with_structured_output(ProfileGeneration)
        result: ProfileGeneration = llm.invoke([HumanMessage(content=(
            "Analyze this resume and generate three things:\n\n"
            "1. A candidate profile as a bullet-point list (8-12 bullets) summarizing "
            "key qualifications, experience level, technical expertise, industries, "
            "education, and location.\n\n"
            "2. A target roles description listing what roles this person should look for, "
            "based on their seniority and skills.\n\n"
            "3. A list of 15-25 specific job search queries to find matching positions "
            "(e.g. 'VP Engineering', 'Head of AI', 'Director of Product Design').\n\n"
            f"## Resume\n{resume_text}"
        ))])
        return {
            "profile": result.profile,
            "target_roles": result.target_roles,
            "search_queries": result.search_queries,
        }
    except Exception:
        log.error("Profile generation failed", exc_info=True)
        raise HTTPException(500, "Failed to generate profile from resume")


# --- Tailoring ---

@app.post("/api/jobs/{job_id}/tailor")
def tailor_job(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    delete_application(job_id)

    config.reload_config()
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(400, "Anthropic API key not configured")

    resume_md = ""
    if config.RESUME_PATH.exists():
        resume_md = config.RESUME_PATH.read_text()
    if not resume_md:
        raise HTTPException(400, "No resume uploaded")

    llm = _get_llm()

    try:
        resp = llm.invoke([HumanMessage(content=config.PROMPT_RESUME.format(
            title=job["title"],
            company=job["company"],
            description=job["description"][:2000],
            resume=resume_md,
        ))])
        tailored_resume = resp.content.strip()
    except Exception:
        log.warning("Resume tailoring failed", exc_info=True)
        tailored_resume = resume_md

    try:
        resp = llm.invoke([HumanMessage(content=config.PROMPT_COVER_LETTER.format(
            title=job["title"],
            company=job["company"],
            description=job["description"][:2000],
            profile=config.CANDIDATE_PROFILE,
        ))])
        cover_letter = resp.content.strip()
    except Exception:
        log.warning("Cover letter failed", exc_info=True)
        cover_letter = ""

    if config.PROMPT_HUMANIZE:
        tailored_resume = _humanize(llm, tailored_resume)
        if cover_letter:
            cover_letter = _humanize(llm, cover_letter)

    save_application(job_id, tailored_resume, cover_letter)
    app_data = get_application(job_id)
    return {"status": "created", "application": app_data}


@app.get("/api/jobs/{job_id}/resume.pdf")
def download_resume_pdf(job_id: int):
    app_data = get_application(job_id)
    if not app_data or not app_data["tailored_resume"]:
        raise HTTPException(404, "No tailored resume. Click 'Prepare Application' first.")

    job = get_job(job_id)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        markdown_to_pdf(app_data["tailored_resume"], tmp_path, title=f"Resume - {job['company']}")
        pdf_bytes = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    company_slug = job["company"].lower().replace(" ", "-")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="resume-{company_slug}.pdf"'},
    )


@app.get("/api/jobs/{job_id}/cover-letter.pdf")
def download_cover_letter_pdf(job_id: int):
    app_data = get_application(job_id)
    if not app_data or not app_data["cover_letter"]:
        raise HTTPException(404, "No cover letter. Click 'Prepare Application' first.")

    job = get_job(job_id)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        markdown_to_pdf(app_data["cover_letter"], tmp_path, title=f"Cover Letter - {job['company']}")
        pdf_bytes = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    company_slug = job["company"].lower().replace(" ", "-")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="cover-letter-{company_slug}.pdf"'},
    )


# --- Static frontend (must be last) ---
_frontend_dir = Path(__file__).resolve().parent.parent / "web" / "build"
if _frontend_dir.exists():
    app.mount("/", SPAStaticFiles(directory=str(_frontend_dir), html=True), name="frontend")


def serve():
    import uvicorn
    uvicorn.run("matchbox.api:app", host="0.0.0.0", port=8000)
