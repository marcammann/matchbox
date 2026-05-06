from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import anthropic

from . import config
from .search import Job

log = logging.getLogger(__name__)

BATCH_SIZE = 15


@dataclass
class MatchedJob:
    job: Job
    score: int
    reason: str
    gaps: str = ""


def _build_scoring_prompt(jobs: list[Job]) -> str:
    jobs_data = []
    for i, job in enumerate(jobs):
        jobs_data.append(
            {
                "id": i,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "summary": job.short_description(600),
            }
        )

    return config.PROMPT_MATCHING.format(
        profile=config.CANDIDATE_PROFILE,
        target_roles=config.TARGET_ROLES,
        jobs_json=json.dumps(jobs_data, indent=2),
        threshold=config.MATCH_THRESHOLD,
    )


def _score_batch(batch: list[Job], client: anthropic.Anthropic) -> list[MatchedJob]:
    prompt = _build_scoring_prompt(batch)
    try:
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=2048,
            system=config.PROMPT_MATCHING_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        results = json.loads(text)
    except Exception:
        log.warning("Scoring failed for batch of %d jobs", len(batch), exc_info=True)
        return []

    matched = []
    for result in results:
        idx = result["id"]
        if 0 <= idx < len(batch):
            matched.append(
                MatchedJob(
                    job=batch[idx],
                    score=result["score"],
                    reason=result["reason"],
                    gaps=result.get("gaps", ""),
                )
            )
    return matched


def match_jobs(jobs: list[Job]) -> list[MatchedJob]:
    if not config.ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY not set — returning all jobs unscored")
        return [MatchedJob(job=j, score=0, reason="Not scored — no API key") for j in jobs]

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    batches = [jobs[i : i + BATCH_SIZE] for i in range(0, len(jobs), BATCH_SIZE)]
    matched: list[MatchedJob] = []

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(_score_batch, batch, client) for batch in batches]
        for future in as_completed(futures):
            matched.extend(future.result())

    matched.sort(key=lambda m: m.score, reverse=True)
    above = sum(1 for m in matched if m.score >= config.MATCH_THRESHOLD)
    log.info("Scored %d jobs: %d above threshold %d", len(matched), above, config.MATCH_THRESHOLD)
    return matched
