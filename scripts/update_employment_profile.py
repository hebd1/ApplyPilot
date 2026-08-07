"""Update profile employment_history and split Kount/Equifax in resume.txt."""
import json
from pathlib import Path

APP = Path.home() / ".applypilot"
profile_path = APP / "profile.json"
resume_path = APP / "resume.txt"

profile = json.loads(profile_path.read_text(encoding="utf-8"))
profile["resume_facts"]["preserved_companies"] = [
    "Equifax",
    "Kount Inc",
    "Center for High Performance Computing (CHPC)",
]
profile["resume_facts"]["employment_history"] = [
    {
        "company": "Equifax",
        "title": "Software Development Engineer",
        "subtitle": "Boise, ID | 2022-Present",
    },
    {
        "company": "Kount Inc",
        "title": "Software Development Engineer In Test (SDET)",
        "subtitle": "Boise, ID | 2020-2021",
    },
    {
        "company": "Center for High Performance Computing (CHPC)",
        "title": "IT Intern",
        "subtitle": "Salt Lake City, UT | 2019-2020",
    },
]
profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
print(f"updated {profile_path}")

RESUME = """Eli J. Hebdon
Full Stack Software Engineer
Nampa, ID 83687 • elihebdon@gmail.com • + 1 (801) 420-4031


PROFESSIONAL SUMMARY


Full Stack Software Engineer with over five years of experience specializing in resilient backend services, identity management, and cloud infrastructure. Proven track record in architecting multi-tenant Identity platforms, complex AWS account migrations, and system-wide security enhancements.


TECHNICAL SKILLS
* Languages & Frameworks: Typescript, Golang, Angular, Python, Java, RXJS, SCSS
* Cloud & Infrastructure: Amazon Web Services (AWS), Terraform, Helm, Kubernetes, Docker, Apigee


PROFESSIONAL EXPERIENCE


EQUIFAX                                Boise, ID
Software Development Engineer           2022-Present
* Spearheaded the production launch of a reusable identity platform by managing cross-functional infrastructure delivery, Apigee ingress configuration, and Rampart encryption, successfully hardening security compliance and unblocking the company's identity initiative.
* Overhauled journaling object architecture by enforcing strict Protobuf contracts; this initiative resolved technical debt, optimized SQL and Snowflake query performance, and eliminated breaking changes in Sigma reporting dashboards, leading to a 60% improvement in query performance and a 30% reduction in data processing costs.
* Architected an asynchronous MFA message processing system using AWS SQS, replacing synchronous legacy bottlenecks to ensure high system uptime and a seamless user experience during peak traffic, achieving a 25% decrease in authentication latency during peak traffic periods.


KOUNT INC                              Boise, ID
Software Development Engineer In Test (SDET)        2020-2021
* Built and maintained automated test infrastructure for identity and fraud services during the Equifax acquisition integration period.


Selected Project Experience
* Reusable Identity Platform
* Deployed a multi-tenant WebAuthn Identity-as-a-Service (IDaaS) platform, enabling secure, passwordless authentication across services while ensuring strict tenant isolation and regulatory compliance, supporting sub-100ms response times.


* MultiFactor Authentication Service
* Rewrote the OTP, OTH (One-Time-Hash), SMS, and email service from the ground up to ensure strict regulatory compliance and security, improving overall system reliability by 99.9% while handling 30k+ daily transactions.
* Integrated Incode document verification and Identity Verification Service (IVS) into the MFA pipeline, delivering a high-trust, identity-first authentication flow.


* Launch of New K360 Fraud Prevention Platform
* Architected the backend data pipeline and inference orchestration for a fraud risk scoring AI model, establishing robust data storage and feedback loops to enable continuous model refinement and predictive accuracy improvements, reducing false positives by 15%.


CENTER FOR HIGH PERFORMANCE COMPUTING (CHPC)        Salt Lake City, UT
IT Intern                2019-2020
* Maximized uptime of Data Center resources through critical infrastructure system installations and monitoring.


EDUCATION


UNIVERSITY OF UTAH          Salt Lake City, UT
Bachelor of Science in Computer Science, Minor in Russian                                                                                         2021
"""

resume_path.write_text(RESUME.strip() + "\n", encoding="utf-8")
print(f"updated {resume_path}")
