from __future__ import annotations

import logging
from pathlib import Path

import markdown
import weasyprint

from . import config

log = logging.getLogger(__name__)

_DEFAULT_CSS_PATH = Path(__file__).resolve().parent.parent / "templates" / "resume.css"


def _load_css() -> str:
    if config.PDF_CSS:
        return config.PDF_CSS
    if _DEFAULT_CSS_PATH.exists():
        return _DEFAULT_CSS_PATH.read_text()
    return ""


def _md_to_html(md_text: str, title: str = "") -> str:
    body = markdown.markdown(md_text, extensions=["extra", "smarty"])
    css = _load_css()
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>"""


def markdown_to_pdf(md_text: str, output_path: Path, title: str = "") -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = _md_to_html(md_text, title)
    weasyprint.HTML(string=html).write_pdf(str(output_path))
    log.info("PDF written: %s", output_path)
    return output_path
