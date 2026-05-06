from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from . import config
from .manual import load_manual_jobs, mark_manual_done
from .match import match_jobs
from .pdf import markdown_to_pdf
from .search import Job, search_all, deduplicate
from .tailor import Application, _humanize, tailor_applications

log = logging.getLogger(__name__)


def _load_resume() -> str:
    path = config.RESUME_PATH
    if not path.exists():
        log.error("Resume not found at %s", path)
        sys.exit(1)
    return path.read_text()


def _job_key(job: Job) -> str:
    return f"{job.company.lower().strip()}|{job.title.lower().strip()}"


def _load_seen_jobs() -> set[str]:
    if config.SEEN_JOBS_PATH.exists():
        try:
            data = json.loads(config.SEEN_JOBS_PATH.read_text())
            cutoff = (date.today() - timedelta(days=30)).isoformat()
            keys: set[str] = set()
            for dt, entries in data.items():
                if dt >= cutoff:
                    keys.update(entries)
            return keys
        except Exception:
            return set()
    return set()


def _save_seen_jobs(seen: set[str], jobs: list[Job]) -> None:
    new_keys = {_job_key(j) for j in jobs}

    data: dict[str, list[str]] = {}
    if config.SEEN_JOBS_PATH.exists():
        try:
            data = json.loads(config.SEEN_JOBS_PATH.read_text())
        except Exception:
            pass

    cutoff = (date.today() - timedelta(days=30)).isoformat()
    data = {k: v for k, v in data.items() if k >= cutoff}

    today_key = date.today().isoformat()
    existing = set(data.get(today_key, []))
    data[today_key] = sorted(existing | new_keys)

    config.SEEN_JOBS_PATH.write_text(json.dumps(data, indent=2))


def _filter_new_jobs(jobs: list[Job], seen: set[str]) -> list[Job]:
    new = [j for j in jobs if _job_key(j) not in seen]
    log.info("Filtered %d seen -> %d new jobs", len(jobs) - len(new), len(new))
    return new


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _format_applications(applications: list[Application], start_index: int = 1) -> str:
    lines: list[str] = []
    for i, app in enumerate(applications, start_index):
        job = app.match.job
        slug = _slugify(f"{job.company}-{job.title}")
        lines.append(f"---\n")
        lines.append(f"## {i}. {job.title} — {job.company}\n")
        lines.append(f"**Score:** {app.match.score}/100  ")
        lines.append(f"**Source:** {job.source}  ")
        if job.salary:
            lines.append(f"**Salary:** {job.salary}  ")
        if job.location:
            lines.append(f"**Location:** {job.location}  ")
        lines.append(f"**Posted:** {job.posted_date or 'N/A'}\n")
        lines.append(f"**Why it fits:** {app.match.reason}\n")
        lines.append(f"**Apply:** [{job.url}]({job.url})\n")
        lines.append(f"**Files:** `applications/{slug}/`\n")
        lines.append(f"### Cover Letter\n")
        lines.append(f"{app.cover_letter}\n")
    return "\n".join(lines)


def _write_report(applications: list[Application], output_dir: Path, label: str = "") -> Path:
    today = date.today().isoformat()
    suffix = f"-{label}" if label else ""
    report_path = output_dir / f"report{suffix}.md"

    header = f"# Job Search Report — {today}"
    if label:
        header += f" ({label})"
    lines = [f"{header}\n"]

    if not applications:
        lines.append("No matching jobs found.\n")
    else:
        lines.append(f"Found **{len(applications)}** matching roles:\n")
        lines.append(_format_applications(applications))

    report_path.write_text("\n".join(lines))
    log.info("Report written: %s", report_path)
    return report_path


def _write_applications(applications: list[Application], output_dir: Path) -> None:
    apps_dir = output_dir / "applications"

    for app in applications:
        job = app.match.job
        slug = _slugify(f"{job.company}-{job.title}")
        app_dir = apps_dir / slug
        app_dir.mkdir(parents=True, exist_ok=True)

        resume_md_path = app_dir / "resume.md"
        resume_md_path.write_text(app.tailored_resume)

        cover_md_path = app_dir / "cover_letter.md"
        cover_md_path.write_text(app.cover_letter)

        try:
            markdown_to_pdf(app.tailored_resume, app_dir / "resume.pdf", title=f"Resume — {job.company}")
        except Exception:
            log.warning("PDF generation failed for resume: %s", slug, exc_info=True)

        try:
            markdown_to_pdf(app.cover_letter, app_dir / "cover_letter.pdf", title=f"Cover Letter — {job.company}")
        except Exception:
            log.warning("PDF generation failed for cover letter: %s", slug, exc_info=True)

    log.info("Wrote %d application packages", len(applications))


def _run_humanize_only() -> None:
    if not config.PROMPT_HUMANIZE:
        log.error("No humanize prompt configured in config.yaml")
        sys.exit(1)

    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    app_dirs = sorted(config.OUTPUT_DIR.rglob("applications/*/"))
    if not app_dirs:
        log.info("No application folders found in %s", config.OUTPUT_DIR)
        return

    count = 0
    for app_dir in app_dirs:
        if not app_dir.is_dir():
            continue

        resume_path = app_dir / "resume.md"
        cover_path = app_dir / "cover_letter.md"

        if not resume_path.exists() and not cover_path.exists():
            continue

        label = app_dir.relative_to(config.OUTPUT_DIR)
        log.info("Humanizing: %s", label)

        if resume_path.exists():
            original = resume_path.read_text()
            humanized = _humanize(client, original)
            resume_path.write_text(humanized)
            try:
                markdown_to_pdf(humanized, app_dir / "resume.pdf",
                                title=f"Resume — {app_dir.name}")
            except Exception:
                log.warning("PDF failed for %s/resume.pdf", label, exc_info=True)

        if cover_path.exists():
            original = cover_path.read_text()
            humanized = _humanize(client, original)
            cover_path.write_text(humanized)
            try:
                markdown_to_pdf(humanized, app_dir / "cover_letter.pdf",
                                title=f"Cover Letter — {app_dir.name}")
            except Exception:
                log.warning("PDF failed for %s/cover_letter.pdf", label, exc_info=True)

        count += 1

    log.info("Humanized %d application packages", count)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily job search agent")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--manual-only", action="store_true",
                      help="Only process manual_jobs.txt, skip automated search")
    mode.add_argument("--startups-only", action="store_true",
                      help="Only search startup sources (HN Who is Hiring + YC Jobs)")
    mode.add_argument("--humanize-only", action="store_true",
                      help="Re-humanize all existing resume.md and cover_letter.md files in output/")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    log.info("=== Job Search Agent — %s ===", date.today().isoformat())

    if not config.ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY is required. Set it in .env or environment.")
        sys.exit(1)

    if args.humanize_only:
        _run_humanize_only()
        return

    resume_md = _load_resume()
    log.info("Resume loaded from %s (%d chars)", config.RESUME_PATH, len(resume_md))

    manual_matches = load_manual_jobs()
    if manual_matches:
        log.info("Loaded %d manual jobs", len(manual_matches))

    jobs: list[Job] = []
    matches: list = []

    if args.manual_only:
        log.info("Manual-only mode — skipping automated search")
        if not manual_matches:
            log.info("No manual jobs to process. Add URLs to manual_jobs.txt.")
            return
    elif args.startups_only:
        from .startups import search_all_startups

        seen = _load_seen_jobs()
        log.info("Startups-only mode")
        jobs = deduplicate(search_all_startups())
        log.info("Found %d startup jobs", len(jobs))

        new_jobs = _filter_new_jobs(jobs, seen)
        if new_jobs:
            log.info("Matching %d jobs against profile...", len(new_jobs))
            matches = match_jobs(new_jobs)
            log.info("Got %d matches above threshold", len(matches))
    else:
        seen = _load_seen_jobs()
        log.info("Loaded %d days of seen-job history", len(seen))

        log.info("Searching for jobs...")
        jobs = search_all()
        log.info("Found %d total jobs across all sources", len(jobs))

        new_jobs = _filter_new_jobs(jobs, seen)

        if new_jobs:
            log.info("Matching %d jobs against profile...", len(new_jobs))
            matches = match_jobs(new_jobs)
            log.info("Got %d matches above threshold", len(matches))

    all_matches = manual_matches + matches

    if all_matches:
        log.info("Tailoring resumes and cover letters for %d jobs (%d manual, %d matched)...",
                 len(all_matches), len(manual_matches), len(matches))
        applications = tailor_applications(all_matches, resume_md, config.CANDIDATE_PROFILE)
    else:
        log.info("No jobs to process today.")
        applications = []

    mark_manual_done(manual_matches)

    today_dir = config.OUTPUT_DIR / date.today().isoformat()
    today_dir.mkdir(parents=True, exist_ok=True)

    report_label = "startups" if args.startups_only else "manual" if args.manual_only else ""
    report_path = _write_report(applications, today_dir, label=report_label)
    if applications:
        _write_applications(applications, today_dir)

    if not args.manual_only:
        _save_seen_jobs(seen, jobs)

    summary = f"Job Search Complete — {date.today().isoformat()}"
    if not args.manual_only:
        summary += f" | Jobs found: {len(jobs)}"
    summary += f" | Manual: {len(manual_matches)} | Matched: {len(matches)}"
    summary += f" | Applications: {len(applications)} | Report: {report_path}"
    log.info(summary)


if __name__ == "__main__":
    main()
