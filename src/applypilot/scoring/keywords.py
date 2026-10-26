"""ATS keyword coverage: how many of a job's top hard skills a resume shows.

The tailoring LLM lists the job's top hard skills (``jd_top_skills``); this
module checks them against the tailored resume text with alias and
word-boundary matching. Missing skills split into ``missing_on_list`` (Eli
has them, so the tailor should add them) and ``missing_gap`` (real gaps,
never to be added).
"""

from __future__ import annotations

import re

# canonical -> spellings that count as the same skill in a resume
ALIASES: dict[str, list[str]] = {
    "go": ["Go", "Golang"],
    "postgresql": ["PostgreSQL", "Postgres"],
    "kubernetes": ["Kubernetes", "K8s"],
    "javascript": ["JavaScript"],
    "typescript": ["TypeScript"],
    "node.js": ["Node.js", "NodeJS", "Node"],
    "ci/cd": ["CI/CD", "CICD", "continuous integration", "continuous delivery",
              "GitLab CI/CD", "GitHub Actions"],
    "aws": ["AWS", "Amazon Web Services"],
    "gcp": ["GCP", "Google Cloud"],
    "rest": ["REST", "RESTful"],
    "grpc": ["gRPC"],
    "microservices": ["microservices", "microservice"],
    "distributed systems": ["distributed systems", "distributed system"],
    "authentication": ["authentication", "auth"],
    "sqs": ["SQS", "AWS SQS"],
    "observability": ["observability", "monitoring"],
}

_CANONICAL: dict[str, str] = {}
for _canon, _spellings in ALIASES.items():
    _CANONICAL[_canon] = _canon
    for _s in _spellings:
        _CANONICAL.setdefault(_s.lower(), _canon)


def canonical(skill: str) -> str:
    key = " ".join(str(skill).split()).lower()
    return _CANONICAL.get(key, key)


def _variants(skill: str) -> list[str]:
    return [skill.strip()] + ALIASES.get(canonical(skill), [])


def skill_in_text(skill: str, text: str) -> bool:
    """Whole-word, alias-aware match. Spellings of 1-2 letters ("Go") are case-sensitive."""
    for v in _variants(skill):
        if not v:
            continue
        pattern = r"(?<![A-Za-z0-9+#.])" + re.escape(v) + r"(?![A-Za-z0-9+#])"
        flags = 0 if len(v) <= 2 else re.IGNORECASE
        if re.search(pattern, text, flags):
            return True
    return False


def coverage(top_skills, resume_text: str, allowed_skills: list[str]) -> dict | None:
    """Coverage report for the job's top skills, or None when the job listed none."""
    top: list[str] = []
    seen: set[str] = set()
    for raw in top_skills or []:
        skill = " ".join(str(raw).split())
        if not skill or canonical(skill) in seen:
            continue
        seen.add(canonical(skill))
        top.append(skill)
    if not top:
        return None

    allowed = {canonical(a) for a in allowed_skills or []}
    covered = [s for s in top if skill_in_text(s, resume_text)]
    missing = [s for s in top if s not in covered]
    return {
        "top": top,
        "covered": covered,
        "missing_on_list": [s for s in missing if canonical(s) in allowed],
        "missing_gap": [s for s in missing if canonical(s) not in allowed],
        "score": round(len(covered) / len(top), 2),
    }


def allowed_skills(profile: dict) -> list[str]:
    """Flatten profile skills_boundary into one list."""
    out: list[str] = []
    for items in (profile.get("skills_boundary") or {}).values():
        if isinstance(items, list):
            out.extend(str(i) for i in items)
    return out
