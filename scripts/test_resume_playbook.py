#!/usr/bin/env python3
"""Playbook mode: Eli's Notion Resume Playbook constrains tailoring, judging and cover letters."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from applypilot.scoring import playbook
from applypilot.scoring.cover_letter import _build_cover_letter_prompt
from applypilot.scoring.resume_format import format_contact_line
from applypilot.scoring.tailor import _playbook_title, _build_judge_prompt, _build_tailor_prompt

PLAYBOOK = """## Banned claims
- Claiming "Senior" or any title Eli did not hold.
## Approved bullet bank
- **E1 (Go, identity):** Built Go microservices for a multi-tenant WebAuthn (passkey) IDaaS platform.
"""

PROFILE = {
    "personal": {"full_name": "Eli Hebdon", "email": "e@x.com", "phone": "8014204031",
                 "city": "Nampa", "province_state": "Idaho", "postal_code": "83687"},
    "skills_boundary": {"languages": ["Go"]},
    "resume_facts": {"preserved_companies": ["Equifax"], "real_metrics": ["25%"],
                     "employment_history": [{"company": "Equifax", "title": "SDE", "subtitle": "Boise, ID | 2025"}]},
    "work_authorization": {}, "compensation": {"salary_expectation": "1"}, "experience": {},
}


def main() -> None:
    # Seniority and level never reach the headline; the role family stays.
    cases = {
        "Senior Backend Engineer": "Backend Engineer",
        "Sr. Software Engineer II": "Software Engineer",
        "Staff Backend Software Engineer – Platform Enablement": "Backend Software Engineer",
        "Lead Full Stack Engineer (Remote)": "Full Stack Engineer",
        "Software Engineer III, Payments": "Software Engineer",
        "Principal Platform Engineer": "Platform Engineer",
        "Backend Software Engineer": "Backend Software Engineer",
    }
    for raw, want in cases.items():
        got = playbook.strip_seniority(raw)
        assert got == want, (raw, got, want)
    assert playbook.strip_seniority("Senior") == "Software Engineer"

    # Contact line: the Playbook's fixed line wins when the profile carries it.
    fixed = "Nampa, ID • e@x.com • (801) 420-4031 • linkedin.com/in/eli-hebdon • github.com/hebd1"
    with_line = {**PROFILE, "resume_facts": {**PROFILE["resume_facts"], "contact_line": fixed}}
    assert format_contact_line(with_line) == fixed
    assert "Nampa" in format_contact_line(PROFILE)

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "resume_playbook.md"
        saved = os.environ.get("RESUME_PLAYBOOK_PATH")
        os.environ["RESUME_PLAYBOOK_PATH"] = str(path)
        try:
            # No file: prompts are unchanged (legacy behaviour).
            assert playbook.load_playbook() == ""
            legacy = _build_tailor_prompt(PROFILE)
            assert "RESUME PLAYBOOK" not in legacy
            assert "TOLERANCE RULE" in _build_judge_prompt(PROFILE)

            path.write_text(PLAYBOOK, encoding="utf-8")
            assert playbook.load_playbook().startswith("## Banned claims")

            tailor = _build_tailor_prompt(PROFILE)
            assert "RESUME PLAYBOOK" in tailor and "E1 (Go, identity)" in tailor
            assert "You MAY add 2-3 closely related tools" not in tailor
            assert "Keep seniority" not in tailor

            judge = _build_judge_prompt(PROFILE)
            assert "TOLERANCE RULE" not in judge
            assert "E1 (Go, identity)" in judge and "VERDICT" in judge

            cover = _build_cover_letter_prompt(PROFILE)
            assert "150-200 words" in cover and "350-500" not in cover
            assert "E1 (Go, identity)" in cover

            # The model's title is normalized in code, not left to the prompt.
            assert _playbook_title({"title": "Senior Go Engineer"}) == {"title": "Go Engineer"}
        finally:
            if saved is None:
                os.environ.pop("RESUME_PLAYBOOK_PATH", None)
            else:
                os.environ["RESUME_PLAYBOOK_PATH"] = saved

    # Without a playbook the title is left alone.
    os.environ["RESUME_PLAYBOOK_PATH"] = "/nonexistent/playbook.md"
    try:
        assert _playbook_title({"title": "Senior Go Engineer"}) == {"title": "Senior Go Engineer"}
    finally:
        if saved is None:
            os.environ.pop("RESUME_PLAYBOOK_PATH", None)
        else:
            os.environ["RESUME_PLAYBOOK_PATH"] = saved

    print("test_resume_playbook: ok")


if __name__ == "__main__":
    main()
