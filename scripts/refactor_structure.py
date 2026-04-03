import os
import shutil
import sys
from pathlib import Path

# 获取项目根目录
ROOT = Path("e:/TLM")

def main():
    print("开始重构 TLM 项目结构...")

    # 1. 创建新目录
    for d in ["src/core", "src/web", "src/predict", "logs"]:
        (ROOT / d).mkdir(parents=True, exist_ok=True)
        # 为每个 python 包创建 __init__.py
        init_file = ROOT / d / "__init__.py"
        if not init_file.exists():
            init_file.touch()
    
    (ROOT / "src/__init__.py").touch(exist_ok=True)

    # 2. 移动 Core 核心逻辑文件
    core_files = ["pid.py", "simulator.py", "state.py", "config.py", "data.py"]
    for f in core_files:
        src_path = ROOT / "coal_conveyor_web" / f
        if src_path.exists():
            shutil.move(src_path, ROOT / "src" / "core" / f)

    # 3. 移动 Web 业务文件与模板
    web_files = ["app.py", "cli.py", "runtime.py", "replay.py"]
    for f in web_files:
        src_path = ROOT / "coal_conveyor_web" / f
        if src_path.exists():
            shutil.move(src_path, ROOT / "src" / "web" / f)
    
    temp_dir = ROOT / "coal_conveyor_web" / "templates"
    if temp_dir.exists():
        if (ROOT / "src" / "web" / "templates").exists():
            shutil.rmtree(ROOT / "src" / "web" / "templates")
        shutil.move(temp_dir, ROOT / "src" / "web" / "templates")

    # 4. 移动 Predictor 时序模型
    pred_path = ROOT / "coal_conveyor_web" / "predictor.py"
    if pred_path.exists():
        shutil.move(pred_path, ROOT / "src" / "predict" / "predictor.py")

    # 5. 归档处理废弃的桌面版和旧的外层文件夹
    legacy_dir = ROOT / "煤流旧案全量备份"
    legacy_dir.mkdir(exist_ok=True)
    if (ROOT / "coal_conveyor").exists():
        shutil.move(ROOT / "coal_conveyor", legacy_dir / "coal_conveyor_abandoned")
    if (ROOT / "coal_conveyor_web").exists():
        shutil.move(ROOT / "coal_conveyor_web", legacy_dir / "coal_conveyor_web_empty")
    if (ROOT / "coal_conveyor_predict.py").exists():
        shutil.move(ROOT / "coal_conveyor_predict.py", legacy_dir / "coal_conveyor_predict.py")

    # 6. 处理根目录零散文件
    # 重命名外壳
    if (ROOT / "coal_conveyor_web.py").exists():
        shutil.move(ROOT / "coal_conveyor_web.py", ROOT / "run_web.py")
    
    # 归档日志
    if (ROOT / "speed_events.csv").exists():
        shutil.move(ROOT / "speed_events.csv", ROOT / "logs" / "speed_events.csv")
    if (ROOT / "forecast_result.png").exists():
        shutil.move(ROOT / "forecast_result.png", ROOT / "logs" / "forecast_result.png")

    print("\n✅ 文件物理迁移完成！")
    print("👉 请返回编辑器让 AI 助手接管剩下的工作：进行 import 相对路径的大规模重构与连线修复！")

if __name__ == "__main__":
    main()
