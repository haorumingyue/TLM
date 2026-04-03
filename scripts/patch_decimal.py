"""
patch_decimal.py — 将 coal_conveyor 包内所有 :.Nf 格式说明符中 N>4 的改为最多 4 位小数
运行（仓库根目录）: python scripts/patch_decimal.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
pkg = ROOT / "coal_conveyor"


def cap_decimals(m):
    n = int(m.group(1))
    return f":.{min(n, 4)}f"


total_changed = 0
for path in sorted(pkg.glob("*.py")):
    text = path.read_text(encoding="utf-8")
    patched = re.sub(r":\.(\d+)f", cap_decimals, text)
    before = re.findall(r":\.(\d+)f", text)
    after = re.findall(r":\.(\d+)f", patched)
    changed = sum(1 for a, b in zip(before, after) if a != b)
    if changed:
        path.write_text(patched, encoding="utf-8")
        total_changed += changed
        print(f"  {path.name}: {changed} 处")

print(f"✅ 完成：共修改 {total_changed} 处格式说明符。")
