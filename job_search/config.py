from __future__ import annotations

import os
import shutil
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))

OUTPUT_DIR = DATA_DIR / "output"
SEEN_JOBS_PATH = DATA_DIR / ".seen_jobs.json"
CONFIG_PATH = DATA_DIR / "config.yaml"

if not CONFIG_PATH.exists() and DATA_DIR != BASE_DIR and (BASE_DIR / "config.yaml").exists():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BASE_DIR / "config.yaml", CONFIG_PATH)


def _load_yaml() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"config.yaml not found at {CONFIG_PATH}")
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


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
    PROMPT_MATCHING_SYSTEM = prompts.get("matching_system", "").strip()
    PROMPT_MATCHING = prompts.get("matching", "").strip()
    PROMPT_RESUME = prompts.get("resume_tailoring", "").strip()
    PROMPT_COVER_LETTER = prompts.get("cover_letter", "").strip()
    PROMPT_HUMANIZE = prompts.get("humanize", "").strip()

    PDF_CSS = cfg.get("pdf_css", "").strip()


_raw: dict = _load_yaml()
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
