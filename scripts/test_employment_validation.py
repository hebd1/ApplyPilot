"""Smoke test employment validation."""
from applypilot.config import load_profile
from applypilot.scoring.employment import is_merged_company_header, validate_employment_structure

p = load_profile()
bad = {"experience": [{"header": "SDE at Kount Inc (Equifax)", "bullets": ["x"]}]}
good = {
    "experience": [
        {"header": "Software Development Engineer at Equifax", "bullets": ["a"]},
        {"header": "Software Development Engineer In Test at Kount Inc", "bullets": ["b"]},
        {"header": "IT Intern at Center for High Performance Computing (CHPC)", "bullets": ["c"]},
    ]
}
print("merged detect:", is_merged_company_header("SDE at Kount Inc (Equifax)"))
print("bad errors:", validate_employment_structure(bad, p))
print("good errors:", validate_employment_structure(good, p))
