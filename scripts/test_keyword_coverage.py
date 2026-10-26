#!/usr/bin/env python3
"""ATS keyword coverage: the job's top hard skills vs the tailored resume text."""
from __future__ import annotations

from applypilot.scoring.keywords import coverage, skill_in_text
from applypilot.scoring.tailor import _build_tailor_prompt

RESUME = """Backend Software Engineer
* Languages: Go, TypeScript, SQL
* Backend & Data: gRPC, REST, PostgreSQL, AWS SQS
* Cloud & DevOps: AWS (Cognito, SQS), Kubernetes, Helm, GitLab CI/CD
* Built Go microservices for a multi-tenant platform with good reliability.
"""

ALLOWED = ["Go", "Golang", "TypeScript", "SQL", "gRPC", "REST", "PostgreSQL", "AWS SQS",
           "AWS", "Kubernetes", "Helm", "GitLab CI/CD", "Terraform", "Java"]


def main() -> None:
    # Aliases and word boundaries.
    assert skill_in_text("Golang", RESUME)
    assert skill_in_text("Postgres", RESUME)
    assert skill_in_text("K8s", RESUME)
    assert skill_in_text("CI/CD", RESUME)
    assert skill_in_text("microservices", RESUME)
    assert not skill_in_text("Java", RESUME), "Java must not match inside JavaScript/other words"
    assert not skill_in_text("Go", "Worked at Google on good things ago."), "Go is case-sensitive and whole-word"
    assert not skill_in_text("React", "Built reactive pipelines."), "React must not match reactive"
    assert not skill_in_text("Rust", RESUME)

    cov = coverage(["Golang", "Postgres", "Kubernetes", "Rust", "CI/CD", "Terraform"], RESUME, ALLOWED)
    assert cov["covered"] == ["Golang", "Postgres", "Kubernetes", "CI/CD"], cov
    assert cov["missing_on_list"] == ["Terraform"], cov   # Eli has it: the tailor should add it
    assert cov["missing_gap"] == ["Rust"], cov            # a real gap: never add it
    assert cov["score"] == round(4 / 6, 2), cov

    assert coverage([], RESUME, ALLOWED) is None
    assert coverage(None, RESUME, ALLOWED) is None
    # Duplicates and blanks are ignored; order is kept.
    cov = coverage(["Go", "go", " ", "SQL"], RESUME, ALLOWED)
    assert cov["top"] == ["Go", "SQL"] and cov["score"] == 1.0, cov

    profile = {"personal": {"full_name": "E"}, "skills_boundary": {"languages": ["Go"]},
               "resume_facts": {}, "experience": {}}
    assert "jd_top_skills" in _build_tailor_prompt(profile)

    print("test_keyword_coverage: ok")


if __name__ == "__main__":
    main()
