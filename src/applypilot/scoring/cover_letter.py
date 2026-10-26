"""Cover letter generation: LLM-powered, profile-driven, with validation.

Generates concise, engineering-voice cover letters tailored to specific job
postings. All personal data (name, skills, achievements) comes from the user's
profile at runtime. No hardcoded personal information.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone

from applypilot.config import COVER_LETTER_DIR, RESUME_PATH, load_profile
from applypilot.database import get_connection, get_jobs_by_stage
from applypilot.llm import get_client
from applypilot.scoring.employment import format_employment_for_prompt
from applypilot.scoring.playbook import load_playbook
from applypilot.scoring.validator import (
    BANNED_WORDS,
    LLM_LEAK_PHRASES,
    sanitize_text,
    validate_cover_letter,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5  # max cross-run retries before giving up


# ── Prompt Builder (profile-driven) ──────────────────────────────────────

def _build_cover_letter_prompt(profile: dict) -> str:
    """Build the cover letter system prompt from the user's profile.

    All personal data, skills, and sign-off name come from the profile.
    """
    personal = profile.get("personal", {})
    boundary = profile.get("skills_boundary", {})
    resume_facts = profile.get("resume_facts", {})

    # Sign-off must use full legal name
    sign_off_name = personal.get("full_name", "")
    city = personal.get("city", "")
    state = personal.get("province_state", "")
    country = personal.get("country", "United States")

    # Flatten all allowed skills
    all_skills: list[str] = []
    for items in boundary.values():
        if isinstance(items, list):
            all_skills.extend(items)
    skills_str = ", ".join(all_skills) if all_skills else "the tools listed in the resume"

    # Real metrics from resume_facts
    real_metrics = resume_facts.get("real_metrics", [])
    preserved_projects = resume_facts.get("preserved_projects", [])
    personal_projects = resume_facts.get("personal_projects", []) or []

    # Build achievement examples for the prompt
    projects_hint = ""
    if preserved_projects:
        projects_hint += (
            f"\nWork-product projects to reference in experience: "
            f"{', '.join(preserved_projects)}"
        )
    personal_names = []
    for entry in personal_projects:
        if isinstance(entry, dict) and entry.get("name"):
            personal_names.append(str(entry["name"]))
        elif str(entry).strip():
            personal_names.append(str(entry).strip())
    if personal_names:
        projects_hint += f"\nPersonal projects (optional mention): {', '.join(personal_names)}"

    metrics_hint = ""
    if real_metrics:
        metrics_hint = f"\nReal metrics to use: {', '.join(real_metrics)}"

    employment_block = format_employment_for_prompt(profile)
    employment_hint = (
        f"\nEmployment history (separate employers — never merge Kount Inc and Equifax):\n"
        f"{employment_block}"
    )

    # Build the full banned list from the validator so the prompt stays in sync
    # with what will actually be rejected — the validator checks all of these.
    all_banned = ", ".join(f'"{w}"' for w in BANNED_WORDS)
    leak_banned = ", ".join(f'"{p}"' for p in LLM_LEAK_PHRASES)

    work_auth = profile.get("work_authorization", {})
    auth_note = ""
    playbook = load_playbook()
    if playbook:
        if work_auth.get("legally_authorized_to_work"):
            auth_note = ("\nIf the job mentions citizenship or sponsorship, one short clause: authorized to work "
                         "in the US, no sponsorship needed. Never claim clearance or the ability to obtain one.")
        return f"""Write a short cover letter for {sign_off_name}. Target: interview.

FORMAT (header contact block is added automatically at PDF render):

Subject: [Job Title] – [Company]

Dear [Company] Hiring Team,

[2-3 short paragraphs: why this role and company (from the job description), the 2 approved bullets that best match the job's top themes, and one line on ownership/on-call/mentoring when the job values it.]

Thank you for your time and consideration.

Warm regards,
{sign_off_name}

LENGTH: 150-200 words between the salutation and the thank-you line.

FACTS: Use only facts from the RESUME PLAYBOOK below (fixed facts, approved bullet bank, skills master list). Respect every banned claim. Never change a number, title, date or year count. Never call {sign_off_name} "Senior".

VOICE: plain and confident, like an engineer writing to another engineer. No em dashes or en dashes in the body.

BANNED WORDS AND PHRASES (validator rejects these):
{all_banned}

ALSO BANNED (meta-commentary):
{leak_banned}{auth_note}

Output ONLY the letter from "Subject:" through the sign-off name. No preamble. No notes after the sign-off.

## RESUME PLAYBOOK
{playbook}"""

    if work_auth.get("legally_authorized_to_work"):
        auth_note = (
            f"\nIf relevant to the role, include one sentence on work authorization "
            f"(e.g. citizen/resident of {country}, able to obtain clearance if required). "
            f"Only include if the job mentions clearance, citizenship, or sponsorship."
        )

    return f"""Write a professional cover letter for {sign_off_name}. Target: interview.

FORMAT (follow exactly — header contact block is added automatically at PDF render):

Subject: [Job Title] – [Company or Team Name]

Dear [Company] Hiring Team,

[Opening paragraph: 3-4 sentences. State the exact role title. Show you understand the company's product/mission. Connect your background to what they need. Mention AI-assisted engineering workflow if the job values modern tooling.]

[Body paragraph 1: 4-5 sentences. Deep match on core technical requirements. Cite 2 specific achievements from the resume with metrics. Use company/project names from resume_facts.]

[Body paragraph 2: 4-5 sentences. Second angle — distributed systems, platform work, IAM, infra, or whatever the job emphasizes. Another achievement with numbers.]

[Optional body paragraph 3: 2-3 sentences on culture fit, ownership, on-call, or team collaboration if relevant.]

Thank you for your time and consideration. I look forward to discussing how my [relevant expertise] can add value to the [Company] team.

Warm regards,
{sign_off_name}

LENGTH: 350-500 words. Four to five substantive paragraphs between salutation and thank-you line.

VOICE:
- Professional but confident. Full sentences, not telegraphic fragments.
- Specific company and role references from the job description.
- Every paragraph should cite real work, tools, or metrics from the resume.
- NEVER use just a first name in the sign-off — always "{sign_off_name}".

BANNED WORDS AND PHRASES (validator rejects these):
{all_banned}

ALSO BANNED (meta-commentary):
{leak_banned}

BANNED PUNCTUATION: No em dashes (—) or en dashes (–). Use commas or periods.

FABRICATION = INSTANT REJECTION:
The candidate's real tools are ONLY: {skills_str}.
Do NOT mention ANY tool not in this list.{projects_hint}{metrics_hint}{employment_hint}{auth_note}

Output ONLY the letter from "Subject:" through the sign-off name. No contact header (name/address/email at top). No preamble. No notes after the sign-off."""


# ── Helpers ──────────────────────────────────────────────────────────────

def _strip_preamble(text: str) -> str:
    """Remove LLM preamble before 'Subject:' or 'Dear' if present."""
    lower = text.lower()
    for marker in ("subject:", "dear "):
        idx = lower.find(marker)
        if idx > 0:
            return text[idx:]
    return text


# ── Core Generation ──────────────────────────────────────────────────────

def generate_cover_letter(
    resume_text: str, job: dict, profile: dict,
    max_retries: int = 3, validation_mode: str = "normal",
) -> str:
    """Generate a cover letter with fresh context on each retry + auto-sanitize.

    Same design as tailor_resume: fresh conversation per attempt, issues noted
    in the prompt, no conversation history stacking.

    Args:
        resume_text:      The candidate's resume text (base or tailored).
        job:              Job dict with title, site, location, full_description.
        profile:          User profile dict.
        max_retries:      Maximum retry attempts.
        validation_mode:  "strict", "normal", or "lenient".

    Returns:
        The cover letter text (best attempt even if validation failed).
    """
    from applypilot.job_meta import display_company

    job_text = (
        f"TITLE: {job['title']}\n"
        f"COMPANY: {display_company(job)}\n"
        f"LOCATION: {job.get('location', 'N/A')}\n\n"
        f"DESCRIPTION:\n{(job.get('full_description') or '')[:6000]}"
    )

    avoid_notes: list[str] = []
    letter = ""
    client = get_client()
    cl_prompt_base = _build_cover_letter_prompt(profile)

    for attempt in range(max_retries + 1):
        # Fresh conversation every attempt
        prompt = cl_prompt_base
        if avoid_notes:
            prompt += "\n\n## AVOID THESE ISSUES:\n" + "\n".join(
                f"- {n}" for n in avoid_notes[-5:]
            )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": (
                f"RESUME:\n{resume_text}\n\n---\n\n"
                f"TARGET JOB:\n{job_text}\n\n"
                "Write the cover letter:"
            )},
        ]

        letter = client.chat(messages, max_tokens=2048, temperature=0.7)
        letter = sanitize_text(letter)  # auto-fix em dashes, smart quotes
        letter = _strip_preamble(letter)  # remove any "Here is the letter:" prefix

        validation = validate_cover_letter(letter, mode=validation_mode)
        if validation["passed"]:
            return letter

        avoid_notes.extend(validation["errors"])
        # Warnings never block — only hard errors trigger a retry
        log.debug(
            "Cover letter attempt %d/%d failed: %s",
            attempt + 1, max_retries + 1, validation["errors"],
        )

    return letter  # last attempt even if failed


# ── Batch Entry Point ────────────────────────────────────────────────────

def run_cover_letters(min_score: int = 7, limit: int = 20,
                      validation_mode: str = "normal") -> dict:
    """Generate cover letters for high-scoring jobs that have tailored resumes.

    Args:
        min_score:       Minimum fit_score threshold.
        limit:           Maximum jobs to process.
        validation_mode: "strict", "normal", or "lenient".

    Returns:
        {"generated": int, "errors": int, "elapsed": float}
    """
    profile = load_profile()
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    conn = get_connection()

    # Fetch jobs that have tailored resumes but no cover letter yet
    jobs = conn.execute(
        "SELECT * FROM jobs "
        "WHERE fit_score >= ? AND tailored_resume_path IS NOT NULL "
        "AND full_description IS NOT NULL "
        "AND (cover_letter_path IS NULL OR cover_letter_path = '') "
        "AND COALESCE(cover_attempts, 0) < ? "
        "AND application_url IS NOT NULL AND application_url LIKE 'http%' "
        "AND LOWER(application_url) NOT LIKE '%linkedin.com%' "
        "AND LOWER(application_url) NOT LIKE '%indeed.com%' "
        "AND LOWER(application_url) NOT LIKE '%ziprecruiter%' "
        "AND LOWER(application_url) NOT LIKE '%glassdoor.com%' "
        "AND LOWER(application_url) NOT LIKE '%talent.com%' "
        "ORDER BY fit_score DESC LIMIT ?",
        (min_score, MAX_ATTEMPTS, limit * 3),
    ).fetchall()

    if not jobs:
        log.info("No jobs needing cover letters (score >= %d).", min_score)
        return {"generated": 0, "errors": 0, "elapsed": 0.0}

    # Convert rows to dicts
    if jobs and not isinstance(jobs[0], dict):
        columns = jobs[0].keys()
        jobs = [dict(zip(columns, row)) for row in jobs]

    from applypilot.job_meta import job_has_usable_apply_url

    apply_ready: list[dict] = []
    for job in jobs:
        ok, reason = job_has_usable_apply_url(job)
        if ok:
            apply_ready.append(job)
        else:
            log.info(
                "Skip cover (no usable apply URL: %s) | %s",
                reason,
                (job.get("title") or "")[:60],
            )
        if len(apply_ready) >= limit:
            break
    jobs = apply_ready

    if not jobs:
        log.info(
            "No cover-letter candidates with score >= %d and a usable application_url.",
            min_score,
        )
        return {"generated": 0, "errors": 0, "elapsed": 0.0}

    COVER_LETTER_DIR.mkdir(parents=True, exist_ok=True)
    log.info(
        "Generating cover letters for %d jobs (score >= %d)...",
        len(jobs), min_score,
    )
    t0 = time.time()
    completed = 0
    results: list[dict] = []
    error_count = 0

    for job in jobs:
        completed += 1
        try:
            letter = generate_cover_letter(resume_text, job, profile,
                                          validation_mode=validation_mode)

            # Build safe filename prefix
            safe_title = re.sub(r"[^\w\s-]", "", job["title"])[:50].strip().replace(" ", "_")
            safe_site = re.sub(r"[^\w\s-]", "", job["site"])[:20].strip().replace(" ", "_")
            prefix = f"{safe_site}_{safe_title}"

            cl_path = COVER_LETTER_DIR / f"{prefix}_CL.txt"
            cl_path.write_text(letter, encoding="utf-8")

            # Generate PDF (best-effort)
            pdf_path = None
            try:
                from applypilot.scoring.pdf import convert_to_pdf
                pdf_path = str(convert_to_pdf(
                    cl_path, job=job, profile=profile, kind="cover",
                ))
            except Exception:
                log.warning("PDF generation failed for %s", cl_path, exc_info=True)

            result = {
                "url": job["url"],
                "path": pdf_path or str(cl_path),
                "pdf_path": pdf_path,
                "title": job["title"],
                "site": job["site"],
            }
            results.append(result)

            elapsed = time.time() - t0
            rate = completed / elapsed if elapsed > 0 else 0
            log.info(
                "%d/%d [OK] | %.1f jobs/min | %s",
                completed, len(jobs), rate * 60, result["title"][:40],
            )
        except Exception as e:
            result = {
                "url": job["url"], "title": job["title"], "site": job["site"],
                "path": None, "pdf_path": None, "error": str(e),
            }
            error_count += 1
            results.append(result)
            log.error("%d/%d [ERROR] %s -- %s", completed, len(jobs), job["title"][:40], e)

    # Persist to DB: increment attempt counter for ALL, save path only for successes
    now = datetime.now(timezone.utc).isoformat()
    saved = 0
    for r in results:
        if r.get("path"):
            conn.execute(
                "UPDATE jobs SET cover_letter_path=?, cover_letter_at=?, "
                "cover_attempts=COALESCE(cover_attempts,0)+1 WHERE url=?",
                (r["path"], now, r["url"]),
            )
            saved += 1
        else:
            conn.execute(
                "UPDATE jobs SET cover_attempts=COALESCE(cover_attempts,0)+1 WHERE url=?",
                (r["url"],),
            )
    conn.commit()

    elapsed = time.time() - t0
    log.info("Cover letters done in %.1fs: %d generated, %d errors", elapsed, saved, error_count)

    return {
        "generated": saved,
        "errors": error_count,
        "elapsed": elapsed,
    }
