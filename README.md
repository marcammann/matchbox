# Matchbox

AI-powered job search agent that finds roles, matches them to your profile, and prepares tailored applications.

![Matchbox dashboard](docs/screenshot.png)

## Video walkthrough

[![Setup guide](https://cdn.loom.com/sessions/thumbnails/686f07368a7641a2a43f0afef80cbcac-with-play.gif)](https://www.loom.com/share/686f07368a7641a2a43f0afef80cbcac)
[![Usage guide](https://cdn.loom.com/sessions/thumbnails/e648bdb974924a65ba222facd1bf5943-with-play.gif)](https://www.loom.com/share/e648bdb974924a65ba222facd1bf5943)

## What it does

- **Multi-source search** — Remotive, JSearch (LinkedIn/Indeed/Glassdoor), Greenhouse boards, Lever boards, company career pages, HN Who is Hiring, YC Jobs
- **AI scoring** — every job is evaluated against your profile and target roles using Claude
- **Tailored applications** — generates customized resumes and cover letters for top matches
- **Web dashboard** — browse, manage, and prepare applications with a clean UI
- **CLI mode** — batch processing for automated daily runs
- **Company targeting** — add companies by name and Matchbox finds where they list jobs

## Quick start

### Prerequisites

- Python 3.12+
- Node.js 22+ (for frontend build)
- [uv](https://docs.astral.sh/uv/) package manager
- An [Anthropic API key](https://console.anthropic.com/)
- A [RapidAPI key](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) (strongly recommended — enables JSearch for LinkedIn/Indeed/Glassdoor results)

### Setup

No setup files are required — configure everything through the web UI on first launch. Or to pre-configure:

```bash
cp data/config.yaml.default data/config.yaml   # edit with your API keys and profile
cp data/RESUME.example.md data/RESUME.md       # paste your resume in markdown
```

### Run the web app

```bash
uv sync
cd web && npm install && npm run build && cd ..
uv run matchbox-web
```

Open [http://localhost:8000](http://localhost:8000)

### Run the CLI

```bash
uv run matchbox
```

### Docker

```bash
docker compose up --build
```

All user data (config, resume, database, generated PDFs) lives in the `data/` directory — shared between Docker and the CLI.

## Configuration

All configuration lives in `data/config.yaml`:

- **API keys** — Anthropic (required), RapidAPI (optional, enables JSearch)
- **Profile** — your professional background, used for matching and cover letters
- **Target roles** — description of what you're looking for
- **Search queries** — keywords to search across job boards
- **Target companies** — Greenhouse/Lever board tokens and career page URLs
- **Sources** — toggle which job boards to search
- **Prompts** — customize how the AI scores jobs, tailors resumes, and writes cover letters
- **PDF CSS** — custom styling for generated resume and cover letter PDFs

API keys can also be set via environment variables (`ANTHROPIC_API_KEY`, `RAPIDAPI_KEY`) or `.env` file.

## Architecture

- **Backend:** Python / FastAPI (`matchbox/`)
- **Frontend:** SvelteKit 5 (`web/`)
- **Data:** all user files live in `data/` (config, resume, database, output)
- **Database:** SQLite (auto-created as `data/jobs.db`)
- **AI:** Anthropic Claude via LangChain for scoring, tailoring, and extraction
- **PDF:** WeasyPrint for resume and cover letter generation

## Why this isn't production-ready

Matchbox was sketched out quickly as a personal tool. There's a long list of things that would need to change before it could be a real product:

- **No auth or multi-tenancy.** Adding proper authentication (SSO, OAuth) is a significant effort on its own, and SSO providers add cost and complexity.
- **Fragile long-running processes.** API calls kick off background tasks that can silently fail. In production, these should be modeled as durable workflows with retries, state tracking, and proper error recovery.
- **Manual API key management.** Users have to bring their own Anthropic and RapidAPI keys. A real product would absorb AI costs and handle billing (Stripe, usage metering, etc.). Something like OpenRouter could simplify model access with a single key, but that still requires key management infrastructure. Keeping this BYO-key means zero additional cost to try it.
- **Limited job board coverage.** The search relies on heuristics across a handful of ATS platforms (Greenhouse, Lever, Ashby) and job aggregators. A production system would need integrations with all major ATS providers and a proper service to identify where each company posts jobs. Many companies only list jobs on their own sites behind JavaScript-heavy pages — Netflix is a good example — which would require per-company scraping workflows with browser automation.
- Lots more, but this is just a starting point.

## License

MIT
