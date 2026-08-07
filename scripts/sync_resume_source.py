"""Sync ~/.applypilot resume + profile from the canonical ELI_HEBDON_RESUME_2026 source.

Prefers Documents/Resumes text; falls back to Downloads PDF text sibling if present.
Keeps work-product projects in preserved_projects and personal apps in personal_projects.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

SOURCE_TXT = Path("/mnt/c/Users/elihe/Documents/Resumes/ELI_HEBDON_RESUME_2026.txt")
SOURCE_PDF = Path("/mnt/c/Users/elihe/Downloads/ELI_HEBDON_RESUME_2026.pdf")
APP = Path.home() / ".applypilot"
PROFILE_PATH = APP / "profile.json"
RESUME_TXT = APP / "resume.txt"
RESUME_PDF = APP / "resume.pdf"

WORK_PRODUCT_PROJECTS = [
    "Reusable Identity Platform",
    "MultiFactor Authentication Service",
    "Launch of New K360 Fraud Prevention Platform",
]

PERSONAL_PROJECTS = [
    {
        "name": "AnyWidget",
        "description": (
            "Android home screen widget app. Built with Kotlin, Firebase, MySQL, "
            "and Google Stitch. Over 1k downloads on the Google Play Store."
        ),
    },
    {
        "name": "BrainLock",
        "description": (
            "iOS App locker featuring brain puzzles. Built with Kotlin Multiplatform, "
            "Firebase, and MySQL."
        ),
    },
    {
        "name": "Pellego",
        "description": (
            "Java e-reading application with AWS Cognito & DynamoDB. Awarded first "
            "place in front-end design for Senior Capstone Project."
        ),
    },
]


def main() -> None:
    if not SOURCE_TXT.is_file():
        raise SystemExit(f"Source resume not found: {SOURCE_TXT}")

    APP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_TXT, RESUME_TXT)
    print(f"copied {SOURCE_TXT} -> {RESUME_TXT}")

    if SOURCE_PDF.is_file():
        shutil.copy2(SOURCE_PDF, RESUME_PDF)
        print(f"copied {SOURCE_PDF} -> {RESUME_PDF}")
    else:
        print(f"PDF not found at {SOURCE_PDF} (skipped)")

    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    facts = profile.setdefault("resume_facts", {})
    facts["preserved_companies"] = [
        "Equifax",
        "Kount Inc",
        "Center for High Performance Computing (CHPC)",
    ]
    facts["preserved_projects"] = list(WORK_PRODUCT_PROJECTS)
    facts["personal_projects"] = list(PERSONAL_PROJECTS)
    facts["preserved_school"] = "University of Utah"
    facts["real_metrics"] = [
        "99.9%",
        "~30k daily users",
        "sub-100ms",
        "25%",
        "30%",
        "1k downloads",
        "20%",
    ]
    facts["employment_history"] = [
        {
            "company": "Equifax",
            "title": "Software Development Engineer",
            "subtitle": "Boise, ID | June 2025-Present",
        },
        {
            "company": "Kount Inc",
            "title": "Software Development Engineer / SDET",
            "subtitle": "Boise, ID | May 2021-June 2025",
        },
        {
            "company": "Center for High Performance Computing (CHPC)",
            "title": "IT Intern",
            "subtitle": "Salt Lake City, UT | 2019-2020",
        },
    ]
    facts["education_details"] = {
        "school": "University of Utah",
        "location": "Salt Lake City, UT",
        "degree": "Bachelor of Science in Computer Science, Minor in Russian",
        "year": "2021",
        "highlights": [
            "Recipient of the Utah Flagship Scholarship",
            "Dean's List (2016, 2018, 2019)",
        ],
    }
    facts["additional_information"] = [
        "Proficient Russian speaker, Google Play Store application developer, digital artist"
    ]

    boundary = profile.setdefault("skills_boundary", {})
    boundary["programming_languages"] = [
        "Golang",
        "Typescript",
        "Javascript",
        "Python",
        "Kotlin",
        "Java",
    ]
    boundary["frameworks"] = [
        "Angular",
        "RxJS",
        "Node.js",
        "Kotlin Multiplatform",
    ]
    boundary["tools"] = [
        "Docker",
        "AWS",
        "Git",
        "Gitlab CI/CD",
        "Kubernetes",
        "Helm",
        "Terraform",
        "Apigee",
        "Firebase",
        "MySQL",
        "DynamoDB",
        "Cognito",
        "Protobuf",
        "gRPC",
        "Google Stitch",
    ]

    PROFILE_PATH.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    print(f"updated {PROFILE_PATH}")


if __name__ == "__main__":
    main()
