"""Generate upload-ready PDFs for all tailored resumes and cover letters."""
from applypilot.config import load_env
from applypilot.database import init_db
from applypilot.scoring.pdf import batch_convert_materials

load_env()
init_db()
stats = batch_convert_materials()
print(stats)
