from applypilot.config import load_env
from applypilot.database import init_db, get_stats

load_env()
init_db()
print(get_stats())
