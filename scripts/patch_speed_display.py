"""
一次性修补 coal_conveyor/viz_sim.py 中的建议带速显示（标题、右轴、speed_text）。
运行（仓库根目录）: python scripts/patch_speed_display.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
path = ROOT / "coal_conveyor" / "viz_sim.py"
text = path.read_text(encoding="utf-8")

# 1. 子图标题
text = text.replace(
    "累计进出煤量统计 & 带速",
    "累计进出煤量统计 & 建议带速 (紫线) vs 实际常速 (灰虚线)",
)

# 2. 右轴 ylabel
text = text.replace(
    'self.ax_speed.set_ylabel("带速 (m/s)", color="#8e44ad")',
    'self.ax_speed.set_ylabel("建议带速 (m/s)", color="#8e44ad")',
)

# 3. 右轴刻度范围 + 参考线 / 图例（与当前 viz_sim 结构一致，\n 换行）
old_stat = (
    "        self.ax_speed = ax.twinx()\n"
    '        self.ax_speed.set_ylabel("建议带速 (m/s)", color="#8e44ad")\n'
    "        self.ax_speed.set_ylim(1.0, 5.0)\n"
    '        self.speed_line, = self.ax_speed.plot([], [], color="#8e44ad", linewidth=1.5, linestyle=":")\n'
    '        self.status_text = self.fig.text(0.5, 0.01, "初始化中...", ha="center", fontsize=9, color="gray")\n'
)
new_stat = (
    "        self.ax_speed = ax.twinx()\n"
    '        self.ax_speed.set_ylabel("建议带速 (m/s)", color="#8e44ad")\n'
    "        self.ax_speed.set_ylim(0.5, 5.5)\n"
    "        self.ax_speed.axhline(\n"
    "            y=self.cfg.ACTUAL_SPEED,\n"
    '            color="#888888",\n'
    '            linestyle="--",\n'
    "            linewidth=1.5,\n"
    '            label=f"实际常速 {self.cfg.ACTUAL_SPEED}m/s",\n'
    "        )\n"
    '        self.speed_line, = self.ax_speed.plot(\n'
    "            [],\n"
    "            [],\n"
    '            color="#8e44ad",\n'
    "            linewidth=2.0,\n"
    '            linestyle="-",\n'
    '            label="建议带速",\n'
    "        )\n"
    "        self.saving_fill_stat = self.ax_speed.fill_between(\n"
    "            [], [], self.cfg.ACTUAL_SPEED, color=\"#8e44ad\", alpha=0.13, label=\"节能区间\"\n"
    "        )\n"
    '        self.ax_speed.legend(loc="upper right", fontsize=8)\n'
    '        self.status_text = self.fig.text(0.5, 0.01, "初始化中...", ha="center", fontsize=9, color="gray")\n'
)

if old_stat in text:
    text = text.replace(old_stat, new_stat)
    print("✅ 修补 3: 右轴参考线 / 图例")
elif "self.ax_speed.axhline" in text and "实际常速" in text:
    print("⏭ 修补 3: 已应用过，跳过")
else:
    print("❌ 修补 3 未找到目标文本，请手动检查 coal_conveyor/viz_sim.py")

# 4. speed_text 显示内容
old4 = (
    "        self.speed_text.set_text(\n"
    '            f"带速: {self.sim.belt_speed:.2f} m/s   "\n'
    '            f"皮带存煤: {self.sim.stats[\'total_coal\']:.1f} t   "\n'
    '            f"进煤: {sum(self.sim.total_inflow.values()):.1f} t"\n'
    "        )\n"
)
new4 = (
    "        _saving = max(\n"
    "            0, (self.cfg.ACTUAL_SPEED - self.sim.belt_speed) / self.cfg.ACTUAL_SPEED * 100\n"
    "        )\n"
    "        self.speed_text.set_text(\n"
    '            f"建议带速: {self.sim.belt_speed:.2f} m/s   "\n'
    '            f"实际常速: {self.cfg.ACTUAL_SPEED:.1f} m/s   "\n'
    '            f"节能估算: {_saving:.1f}%   "\n'
    '            f"皮带存煤: {self.sim.stats[\'total_coal\']:.1f} t"\n'
    "        )\n"
)
if old4 in text:
    text = text.replace(old4, new4)
    print("✅ 修补 4: speed_text")
else:
    print("❌ 修补 4 未找到 speed_text 目标，可能已修改过")

path.write_text(text, encoding="utf-8")
print(f"\n✅ 已写回: {path.relative_to(ROOT)}")
