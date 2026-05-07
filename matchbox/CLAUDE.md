# Matchbox Backend

Python 3.12+ package. Run with `uv run matchbox` (CLI) or `uv run matchbox-web` (FastAPI server on port 8000).

## Architecture

- `api.py` — FastAPI app, all HTTP endpoints, company discovery logic, serves the static frontend build from `web/build/`
- `config.py` — Global config loaded from `data/config.yaml`, cascading defaults (code → config.yaml.default → config.yaml → env vars). Call `reload_config()` before reading config in long-lived processes.
- `search.py` — Remotive and JSearch (RapidAPI) job fetchers. `Job` dataclass is defined here and imported everywhere.
- `careers.py` — Greenhouse, Lever, Ashby board fetchers + career page scraper. Career pages auto-detect ATS URLs and use the API instead of scraping. `search_all_career_sources()` is the main entry point.
- `startups.py` — HN Who is Hiring and YC Jobs scrapers.
- `match.py` — LLM-based job scoring against candidate profile using `ChatAnthropic.with_structured_output()`.
- `tailor.py` — Parallel resume/cover letter generation with optional humanize pass. Uses `ThreadPoolExecutor`.
- `db.py` — SQLite layer (`data/jobs.db`). Jobs, applications, dedup keys.
- `pdf.py` — Markdown → PDF via WeasyPrint.
- `remoteintech.py` — Fetches/caches 876 remote-friendly companies from the Remote In Tech GitHub repo (tarball download, YAML frontmatter parsing, 24h TTL cache).
- `main.py` — CLI entry point for batch processing.

## Key patterns

- All config is global module-level variables in `config.py`, mutated by `_apply()`. Not great but it works — don't add more global state.
- Job sources catch exceptions internally and return empty lists, logging warnings. The `_SearchWarningCollector` in `api.py` captures these warnings during search and surfaces them to the frontend.
- Company discovery tries sources in order: token variants → Ashby → Remote In Tech → LLM fallback. The LLM uses `with_structured_output(CompanyDiscovery)`.
- Board validation functions (`_try_greenhouse`, `_try_lever`, `_try_ashby`) hit the real API to confirm the board exists and has jobs. Greenhouse also validates the board name matches the expected company.

## Data

All user data lives in `data/`: config.yaml, RESUME.md, jobs.db, generated PDFs. The `DATA_DIR` is configurable via the `DATA_DIR` env var for Docker.

## Testing

No test suite yet. Verify changes with:
```
uv run python -c "from matchbox import api, careers, config; print('ok')"
```
