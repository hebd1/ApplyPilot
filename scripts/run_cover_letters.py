"""Run cover letter generation only."""
from applypilot.config import load_env
from applypilot.scoring.cover_letter import run_cover_letters

if __name__ == "__main__":
    load_env()
    stats = run_cover_letters(min_score=7, limit=50)
    print(stats)
