from __future__ import annotations

import sqlite3
import logging
from datetime import date, datetime
from pathlib import Path

from . import config

log = logging.getLogger(__name__)


def _db_path() -> Path:
    return config.DATA_DIR / "jobs.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            description TEXT DEFAULT '',
            url TEXT DEFAULT '',
            source TEXT DEFAULT '',
            location TEXT DEFAULT '',
            category TEXT DEFAULT '',
            salary TEXT DEFAULT '',
            posted_date TEXT DEFAULT '',
            found_date TEXT NOT NULL,
            score INTEGER DEFAULT 0,
            reason TEXT DEFAULT '',
            gaps TEXT DEFAULT '',
            dedup_key TEXT NOT NULL,
            status TEXT DEFAULT 'open'
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_found_date ON jobs(found_date DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_dedup ON jobs(dedup_key);

        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(id),
            tailored_resume TEXT DEFAULT '',
            cover_letter TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
    """)
    _migrate(conn)
    conn.close()
    log.info("Database initialized at %s", _db_path())


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "status" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN status TEXT DEFAULT 'open'")
        conn.commit()


def get_existing_dedup_keys() -> set[str]:
    conn = get_db()
    keys = {row["dedup_key"] for row in conn.execute("SELECT DISTINCT dedup_key FROM jobs")}
    conn.close()
    return keys


def save_matched_jobs(matched_jobs: list, found_date: str | None = None) -> int:
    if not matched_jobs:
        return 0

    found_date = found_date or date.today().isoformat()
    conn = get_db()
    count = 0

    for match in matched_jobs:
        job = match.job
        try:
            conn.execute(
                """INSERT INTO jobs (title, company, description, url, source, location,
                   category, salary, posted_date, found_date, score, reason, gaps, dedup_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job.title, job.company, job.description, job.url, job.source,
                 job.location, job.category or "", job.salary or "",
                 job.posted_date or "", found_date,
                 match.score, match.reason, getattr(match, "gaps", ""),
                 job._dedup_key),
            )
            count += 1
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    conn.close()
    return count


def get_jobs_grouped() -> dict[str, list[dict]]:
    conn = get_db()
    rows = conn.execute(
        """SELECT j.*,
           CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END as has_application
           FROM jobs j
           LEFT JOIN applications a ON j.id = a.job_id
           ORDER BY j.found_date DESC,
                    CASE WHEN j.source = 'manual' THEN 0 ELSE 1 END,
                    j.score DESC"""
    ).fetchall()
    conn.close()

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        d = dict(row)
        dt = d["found_date"]
        grouped.setdefault(dt, []).append(d)
    return grouped


def get_job(job_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_application(job_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_job_status(job_id: int, status: str) -> None:
    conn = get_db()
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()
    conn.close()


def save_manual_job(
    title: str, company: str, description: str, url: str,
    location: str = "", score: int = 0, reason: str = "",
) -> int:
    dedup_key = f"{company.lower().strip()}|{title.lower().strip()}"
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO jobs (title, company, description, url, source, location,
           category, salary, posted_date, found_date, score, reason, gaps, dedup_key)
           VALUES (?, ?, ?, ?, 'manual', ?, '', '', '', ?, ?, ?, '', ?)""",
        (title, company, description, url, location,
         date.today().isoformat(), score, reason, dedup_key),
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    return job_id


def delete_application(job_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM applications WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()


def save_application(job_id: int, tailored_resume: str, cover_letter: str) -> None:
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO applications (job_id, tailored_resume, cover_letter, created_at)
           VALUES (?, ?, ?, ?)""",
        (job_id, tailored_resume, cover_letter, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
