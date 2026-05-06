from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from . import config
from .match import MatchedJob
from .search import Job

log = logging.getLogger(__name__)


def _get_llm() -> ChatAnthropic:
    return ChatAnthropic(model=config.MODEL, api_key=config.ANTHROPIC_API_KEY, max_tokens=4096)


@dataclass
class Application:
    match: MatchedJob
    tailored_resume: str
    cover_letter: str


def tailor_applications(
    matches: list[MatchedJob],
    resume_md: str,
    profile: str,
    max_applications: int = 0,
) -> list[Application]:
    if not config.ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY not set — skipping tailoring")
        return []

    to_process = matches[:max_applications] if max_applications > 0 else matches

    def _tailor_one(match: MatchedJob) -> Application:
        llm = _get_llm()
        job = match.job
        log.info("Tailoring for: %s at %s", job.title, job.company)
        desc = job.short_description(2000)

        with ThreadPoolExecutor(max_workers=2) as inner:
            resume_future = inner.submit(_generate_resume, llm, job, desc, resume_md)
            cover_future = inner.submit(_generate_cover_letter, llm, job, desc, profile)
            tailored_resume = resume_future.result()
            cover_letter = cover_future.result()

        if config.PROMPT_HUMANIZE:
            log.info("Humanizing: %s at %s", job.title, job.company)
            with ThreadPoolExecutor(max_workers=2) as inner:
                rf = inner.submit(_humanize, llm, tailored_resume)
                cf = inner.submit(_humanize, llm, cover_letter) if cover_letter else None
                tailored_resume = rf.result()
                if cf:
                    cover_letter = cf.result()

        return Application(match=match, tailored_resume=tailored_resume, cover_letter=cover_letter)

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_tailor_one, m): m for m in to_process}
        applications: list[Application] = []
        for future in as_completed(futures):
            applications.append(future.result())

    applications.sort(key=lambda a: to_process.index(a.match))
    log.info("Tailored %d applications", len(applications))
    return applications


def _generate_resume(llm: ChatAnthropic, job: Job, desc: str, resume_md: str) -> str:
    try:
        resp = llm.invoke([HumanMessage(content=config.PROMPT_RESUME.format(
            title=job.title, company=job.company, description=desc, resume=resume_md,
        ))])
        return resp.content.strip()
    except Exception:
        log.warning("Resume tailoring failed for %s at %s", job.title, job.company, exc_info=True)
        return resume_md


def _generate_cover_letter(llm: ChatAnthropic, job: Job, desc: str, profile: str) -> str:
    try:
        resp = llm.invoke([HumanMessage(content=config.PROMPT_COVER_LETTER.format(
            title=job.title, company=job.company, description=desc, profile=profile,
        ))])
        return resp.content.strip()
    except Exception:
        log.warning("Cover letter failed for %s at %s", job.title, job.company, exc_info=True)
        return ""


def _humanize(llm: ChatAnthropic, text: str) -> str:
    try:
        resp = llm.invoke([HumanMessage(content=config.PROMPT_HUMANIZE.format(text=text))])
        return resp.content.strip()
    except Exception:
        log.warning("Humanize pass failed, keeping original", exc_info=True)
        return text
