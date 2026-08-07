"""Score one real job from the database via Cursor Auto."""
from applypilot.config import load_env
from applypilot.database import init_db
from applypilot.scoring.scorer import run_scoring

load_env()
init_db()
result = run_scoring(limit=1)
print(result)
