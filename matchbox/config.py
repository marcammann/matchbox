from __future__ import annotations

import os
import shutil
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_DIR = DATA_DIR / "output"
SEEN_JOBS_PATH = DATA_DIR / ".seen_jobs.json"
CONFIG_PATH = DATA_DIR / "config.yaml"
_EXAMPLE_CONFIG = DATA_DIR / "config.yaml.default"

if not CONFIG_PATH.exists() and _EXAMPLE_CONFIG.exists():
    shutil.copy2(_EXAMPLE_CONFIG, CONFIG_PATH)


def _load_yaml() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


RESUME_PATH: Path = Path()
ANTHROPIC_API_KEY: str = ""
RAPIDAPI_KEY: str = ""
MODEL: str = "claude-sonnet-4-6"
MATCH_THRESHOLD: int = 55
SEARCH_QUERIES: list[str] = []
CANDIDATE_PROFILE: str = ""
TARGET_ROLES: str = ""
ROLE_KEYWORDS: list[str] = []
STARTUP_ROLE_KEYWORDS: list[str] = []
LOCATION: str = "remote"
SOURCES: dict[str, bool] = {}
CAREER_PAGES: list[dict[str, str]] = []
GREENHOUSE_BOARDS: list[dict[str, str]] = []
LEVER_BOARDS: list[dict[str, str]] = []
PROMPT_MATCHING_SYSTEM: str = ""
PROMPT_MATCHING: str = ""
PROMPT_RESUME: str = ""
PROMPT_COVER_LETTER: str = ""
PROMPT_HUMANIZE: str = ""
PDF_CSS: str = ""

_DEFAULT_MATCHING_SYSTEM = (
    "You are a job-matching assistant. You evaluate job listings for "
    "fit with a specific candidate.\n\n"
    "Return ONLY valid JSON — no markdown fences, no commentary."
)

_DEFAULT_MATCHING = (
    "Evaluate each job for fit with this candidate.\n\n"
    "## Candidate Profile\n{profile}\n\n"
    "## Target Roles\n{target_roles}\n\n"
    "## Scoring (0-100)\n"
    "- Role level alignment (40 pts): VP / Director / Head / Principal / C-level?\n"
    "- Skills match (30 pts): AI/ML, architecture, platform, leadership, design systems?\n"
    "- Industry relevance (20 pts): Health tech, AI, or top-tier tech company?\n"
    "- Remote fit (10 pts): Truly remote-friendly for US-based candidate?\n\n"
    "## Jobs\n{jobs_json}\n\n"
    "Return a JSON array of objects with keys: id (int), score (int 0-100), "
    "reason (string, 1-2 sentences), gaps (string, 1 sentence about skill/experience "
    "gaps or \"\" if none).\n\n"
    "Include ALL jobs with their scores, even low-scoring ones."
)

_DEFAULT_RESUME = (
    "Customize this resume for the role below.\n\n"
    "Rules:\n"
    "1. Keep all facts truthful — never fabricate experience, titles, or dates\n"
    "2. Rewrite the Summary (2-3 sentences) to speak directly to this role\n"
    "3. Reorder and adjust emphasis of bullet points to foreground relevant experience\n"
    "4. You may trim less-relevant bullets to keep the resume focused\n"
    "5. Preserve the markdown format exactly\n"
    "6. Aim for 2-page length when rendered\n\n"
    "## Role\nTitle: {title}\nCompany: {company}\nDescription:\n{description}\n\n"
    "## Original Resume\n{resume}\n\n"
    "Return ONLY the customized resume markdown. No commentary, no fences."
)

_DEFAULT_COVER_LETTER = (
    "Write a cover letter for this application.\n\n"
    "Rules:\n"
    "1. 3-4 paragraphs, conversational but professional\n"
    "2. Open with genuine interest in the company or role — not generic flattery\n"
    "3. Connect 2-3 specific experiences from the candidate's background to the role's needs\n"
    "4. Close with forward-looking enthusiasm\n"
    "5. Don't rehash the resume — add perspective on why this role, this company, right now\n"
    "6. Use a modern opening (\"Hi [Company] team,\" or similar) — not \"Dear Hiring Manager\"\n"
    "7. Under 300 words\n\n"
    "## Role\nTitle: {title}\nCompany: {company}\nDescription:\n{description}\n\n"
    "## Candidate Background (summary)\n{profile}\n\n"
    "Return ONLY the cover letter text. No commentary, no fences."
)

_DEFAULT_HUMANIZE = (
    "Rewrite the following text so it reads like a human wrote it, not an AI.\n\n"
    "Rules:\n"
    "1. Preserve ALL factual content, names, dates, titles, and structure exactly\n"
    "2. Break up formulaic sentence patterns — vary sentence length and rhythm\n"
    "3. Replace generic AI filler (\"leverage\", \"spearheaded\", \"passionate about\", "
    "\"proven track record\", \"uniquely positioned\", \"I'm excited to\", \"drives me\") "
    "with specific, plain language\n"
    "4. Avoid em dashes (—) unless they genuinely fit the sentence better than "
    "a comma, period, or parenthetical. Most of the time, they don't.\n"
    "5. Cut unnecessary intensifiers (\"genuinely\", \"deeply\", \"truly\", \"incredibly\")\n"
    "6. Don't start multiple paragraphs with \"I\" or \"At [Company]\"\n"
    "7. Keep the same tone and register — don't make it more casual or more formal\n"
    "8. For resumes: preserve the exact markdown format\n"
    "9. For cover letters: keep it under the same word count\n\n"
    "## Text to rewrite\n{text}\n\n"
    "Return ONLY the rewritten text. No commentary, no fences."
)


def _apply(cfg: dict) -> None:
    global RESUME_PATH, ANTHROPIC_API_KEY, RAPIDAPI_KEY, MODEL, MATCH_THRESHOLD
    global SEARCH_QUERIES, CANDIDATE_PROFILE, TARGET_ROLES
    global ROLE_KEYWORDS, STARTUP_ROLE_KEYWORDS
    global LOCATION, SOURCES
    global CAREER_PAGES, GREENHOUSE_BOARDS, LEVER_BOARDS
    global PROMPT_MATCHING_SYSTEM, PROMPT_MATCHING, PROMPT_RESUME
    global PROMPT_COVER_LETTER, PROMPT_HUMANIZE
    global PDF_CSS

    RESUME_PATH = (DATA_DIR / cfg.get("resume_path", "RESUME.md")).resolve()

    api_keys = cfg.get("api_keys", {})
    ANTHROPIC_API_KEY = api_keys.get("anthropic", "") or os.getenv("ANTHROPIC_API_KEY", "")
    RAPIDAPI_KEY = api_keys.get("rapidapi", "") or os.getenv("RAPIDAPI_KEY", "")

    MODEL = cfg.get("model", "claude-sonnet-4-6")
    MATCH_THRESHOLD = cfg.get("match_threshold", 55)
    SEARCH_QUERIES = cfg.get("search_queries", [])
    CANDIDATE_PROFILE = cfg.get("profile", "").strip()
    TARGET_ROLES = cfg.get("target_roles", "").strip()
    ROLE_KEYWORDS = cfg.get("role_keywords", [])
    STARTUP_ROLE_KEYWORDS = cfg.get("startup_role_keywords", [])
    LOCATION = cfg.get("location", "remote").strip()
    SOURCES = cfg.get("sources", {})
    CAREER_PAGES = cfg.get("career_pages", [])
    GREENHOUSE_BOARDS = cfg.get("greenhouse_boards", [])
    LEVER_BOARDS = cfg.get("lever_boards", [])

    prompts = cfg.get("prompts", {})
    PROMPT_MATCHING_SYSTEM = prompts.get("matching_system", "").strip() or _DEFAULT_MATCHING_SYSTEM
    PROMPT_MATCHING = prompts.get("matching", "").strip() or _DEFAULT_MATCHING
    PROMPT_RESUME = prompts.get("resume_tailoring", "").strip() or _DEFAULT_RESUME
    PROMPT_COVER_LETTER = prompts.get("cover_letter", "").strip() or _DEFAULT_COVER_LETTER
    PROMPT_HUMANIZE = prompts.get("humanize", "").strip() or _DEFAULT_HUMANIZE

    PDF_CSS = cfg.get("pdf_css", "").strip()


_raw: dict = _load_yaml() or {}
_apply(_raw)


def reload_config() -> dict:
    global _raw
    _raw = _load_yaml()
    _apply(_raw)
    return _raw


def get_raw_config() -> dict:
    return dict(_raw)


def source_enabled(name: str) -> bool:
    return SOURCES.get(name, True)


def save_config(cfg: dict) -> None:
    global _raw
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    _raw = cfg
    _apply(cfg)
