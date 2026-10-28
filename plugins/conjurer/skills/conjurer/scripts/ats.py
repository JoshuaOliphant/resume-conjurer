# ABOUTME: Names the applicant tracking system behind a job posting from the URLs in its jd.txt.
# ABOUTME: Lets outcomes compare callbacks by ATS vendor; an unrecognized posting reads as "unknown".
"""Detect the ATS vendor of an application from its posting URL.

Each vendor serves its hosted job boards from its own domain (`jobs.ashbyhq.com/<company>`,
`job-boards.greenhouse.io/<company>`, `<company>.wd5.myworkdayjobs.com`), so the first URL in
`jd.txt` whose host belongs to a known vendor names the system that screened the application.
A company that embeds the board on its own careers site has no vendor host in the URL; that
application reads as `unknown` unless the user names the vendor.
"""

import re
from pathlib import Path
from urllib.parse import urlparse

UNKNOWN = "unknown"

VENDOR_DOMAINS = {
    "ashbyhq.com": "ashby",
    "greenhouse.io": "greenhouse",
    "myworkdayjobs.com": "workday",
    "myworkdaysite.com": "workday",
    "lever.co": "lever",
    "icims.com": "icims",
    "eightfold.ai": "eightfold",
    "smartrecruiters.com": "smartrecruiters",
}

_URL_RE = re.compile(r"https?://[^\s<>\"')]+")


def vendor_of(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for domain, vendor in VENDOR_DOMAINS.items():
        if host == domain or host.endswith(f".{domain}"):
            return vendor
    return None


def detect_ats(text: str) -> str:
    """The vendor of the first recognized URL in ``text``, else ``unknown``."""
    for url in _URL_RE.findall(text):
        if vendor := vendor_of(url):
            return vendor
    return UNKNOWN


def app_ats(app_dir: Path) -> str:
    jd = app_dir / "jd.txt"
    return detect_ats(jd.read_text()) if jd.exists() else UNKNOWN
