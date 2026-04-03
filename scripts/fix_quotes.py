"""Fix escaped quotes in coal_conveyor_web.py dict keys. Run from repo root: python scripts/fix_quotes.py"""
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
web = ROOT / "coal_conveyor_web.py"

with open(web, "r", encoding="utf-8") as f:
    lines = f.readlines()

fixed = []
keys = ["total_out", "on_belt", "lanes", "spd_t", "spd_v", "cumin", "cumout", "coal", "pred_queue"]
for line in lines:
    if '\\"' in line and any(k in line for k in keys):
        line = line.replace('\\"', '"')
    fixed.append(line)

with open(web, "w", encoding="utf-8") as f:
    f.writelines(fixed)

print("Done. Checking syntax...")
try:
    py_compile.compile(str(web), doraise=True)
    print("Syntax OK")
except py_compile.PyCompileError as e:
    print(f"Syntax error: {e}")
