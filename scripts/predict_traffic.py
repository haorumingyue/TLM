import os
import re
import sys
import subprocess

# --- 1. 简易依赖自动检测 ---
def install_requirements():
    try:
        import pandas, matplotlib, torch
        from chronos import Chronos2Pipeline
    except ImportError:
        print("依赖缺失，正在自动安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "chronos-forecasting", "pandas", "matplotlib", "torch", "plotly"])
        print("依赖安装完成！\n")
        os.execv(sys.executable, ['python'] + sys.argv)

install_requirements()

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import torch
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from chronos import Chronos2Pipeline

# ============================================================
# --- 2. 全局参数设置 ---
# ============================================================
DATA_DIR          = "data"
MODEL_DIR         = os.path.join(os.getcwd(), "models", "chronos-2")
CONTEXT_LENGTH    = 60          # 以预测点之前 60 个数据点作为上下文
PREDICTION_LENGTH = 10          # 每次向未来预测 10 个点
PLOT_SAVE_PATH    = os.path.join("output", "forecast_result.html")
TARGET_DATES      = ['20250513']
MAX_WINDOWS       = 2000        # 最多推理窗口数，避免单次运行时间过长（None = 不限制）

# 断点检测：两条记录之间时间间隔超过此阈值(秒)，则视为数据断点
GAP_THRESHOLD_SEC = 30

# ============================================================
# --- 3. 数据加载与解析 ---
# ============================================================
def parse_file(filepath):
    """解析单个日志文件，返回 DataFrame (timestamp, traffic)。"""
    timestamps, traffic_values = [], []
    pattern = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+:\s+流量:\s+([0-9\.]+None|None|[0-9\.]+)"
    )
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            m = pattern.search(line)
            if m:
                timestamps.append(m.group(1))
                val = m.group(2)
                traffic_values.append(np.nan if val == "None" else float(val) if val.replace('.', '', 1).isdigit() else np.nan)

    df = pd.DataFrame({"timestamp": timestamps, "traffic": traffic_values})
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['traffic'] = df['traffic'].interpolate(method='linear').bfill().ffill()
    return df


def load_and_merge_files(data_dir, target_dates):
    dfs = []
    for date_str in sorted(target_dates):
        fp = os.path.join(data_dir, f"{date_str}.txt")
        if not os.path.exists(fp):
            print(f"  ⚠️  文件不存在，已跳过: {fp}")
            continue
        print(f"  ✅ 加载文件: {os.path.basename(fp)}")
        dfs.append(parse_file(fp))
    if not dfs:
        raise FileNotFoundError("未找到任何有效的日志文件！")
    merged = pd.concat(dfs, ignore_index=True).sort_values('timestamp').reset_index(drop=True)
    return merged


def build_breakpoint_mask(timestamps, gap_threshold_sec=GAP_THRESHOLD_SEC):
    """
    返回一个布尔数组 is_break[i]：
    若第 i 条和第 i+1 条之间的时间间隔超过阈值，则 is_break[i]=True。
    用于判断某个滑动窗口是否跨越了断点，跨越则跳过不参与评估。
    """
    ts = pd.to_datetime(timestamps)
    # .diff() 在 DatetimeIndex 上返回 TimedeltaIndex（无 .dt），需包装为 pd.Series
    diffs = pd.Series(ts).diff().dt.total_seconds().fillna(0).values
    # is_break[i] = True 表示第 i 个点之前存在断点（即 i-1 → i 是大跳转）
    is_break = diffs > gap_threshold_sec
    return is_break


# ============================================================
# --- 4. 评估指标 ---
# ============================================================
def calc_metrics(pred, actual):
    """计算 MAE、RMSE、sMAPE、WAPE 四个指标。"""
    err  = pred - actual
    mae  = np.mean(np.abs(err))
    rmse = np.sqrt(np.mean(err ** 2))
    # sMAPE（对称MAPE，对小值更稳健） —— 范围 [0%, 200%]
    smape = np.mean(2 * np.abs(err) / (np.abs(pred) + np.abs(actual) + 1e-8)) * 100
    # WAPE（加权绝对百分比误差，等效于 MAE/mean(actual)）
    wape  = np.sum(np.abs(err)) / (np.sum(np.abs(actual)) + 1e-8) * 100
    return mae, rmse, smape, wape


# ============================================================
# --- 5. 主流程 ---
# ============================================================
def main():
    print("=" * 56)
    print(f"🚀 开始数据解析与处理（合并 {len(TARGET_DATES)} 天的数据）...")
    try:
        df = load_and_merge_files(DATA_DIR, TARGET_DATES)
    except Exception as e:
        print(f"数据加载错误：{e}")
        return

    total_len = len(df)
    print(f"[合并后] 共 {total_len} 条记录，时间跨度: "
          f"{df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]}")

    if total_len < CONTEXT_LENGTH + PREDICTION_LENGTH:
        print(f"❌ 数据量不足，至少需要 {CONTEXT_LENGTH + PREDICTION_LENGTH} 条。")
        return

    all_values = df['traffic'].values
    timestamps = df['timestamp'].values

    # --- 断点检测 ---
    is_break = build_breakpoint_mask(timestamps)
    n_breaks = int(is_break.sum())
    print(f"🔍 断点检测: 共发现 {n_breaks} 处时间间隔 > {GAP_THRESHOLD_SEC}s 的断点，滑窗跨越断点的窗口将被跳过。")

    # --- 模型加载 ---
    print("-" * 56)
    print(f"🤖 正在加载 Chronos-2 模型 (目录: {MODEL_DIR})...")
    if not os.path.exists(MODEL_DIR):
        print(f"❌ 找不到模型路径: {MODEL_DIR}")
        return
    try:
        pipeline = Chronos2Pipeline.from_pretrained(MODEL_DIR, device_map="auto")
    except Exception:
        pipeline = Chronos2Pipeline.from_pretrained(MODEL_DIR, device_map="cpu")
    print("✅ 模型加载成功！开始滚动推理...")

    # --- 滚动预测 ---
    QUANTILE_LEVELS = [0.1, 0.5, 0.9]
    all_pred_median, all_pred_low, all_pred_high, all_actual, all_timestamps = [], [], [], [], []
    skipped_windows = 0
    window_count    = 0
    eval_start      = CONTEXT_LENGTH

    pos = eval_start
    while pos + PREDICTION_LENGTH <= total_len:
        ctx_start = pos - CONTEXT_LENGTH
        if ctx_start < 0:
            pos += PREDICTION_LENGTH
            continue

        # --- 跨断点检测：若上下文区段或预测区段内有断点，则跳过此窗口 ---
        ctx_has_break  = is_break[ctx_start + 1 : pos + 1].any()
        pred_has_break = is_break[pos : pos + PREDICTION_LENGTH].any()
        if ctx_has_break or pred_has_break:
            skipped_windows += 1
            pos += PREDICTION_LENGTH
            continue

        context_data = all_values[ctx_start:pos]
        ground_truth = all_values[pos:pos + PREDICTION_LENGTH]
        ground_timestamps = timestamps[pos:pos + PREDICTION_LENGTH]

        context_tensor = [torch.tensor(context_data, dtype=torch.float32)]
        quantiles_list, _ = pipeline.predict_quantiles(
            context_tensor,
            prediction_length=PREDICTION_LENGTH,
            quantile_levels=QUANTILE_LEVELS,
        )
        q_np = quantiles_list[0].squeeze(0).numpy()  # (prediction_length, 3)

        all_pred_low.extend(q_np[:, 0])
        all_pred_median.extend(q_np[:, 1])
        all_pred_high.extend(q_np[:, 2])
        all_actual.extend(ground_truth)
        all_timestamps.extend(ground_timestamps)

        window_count += 1
        total_covered = window_count * PREDICTION_LENGTH
        print(f"  窗口 {window_count:4d} | 跳过 {skipped_windows:3d} | 覆盖 {total_covered:6d} 点", end="\r")
        pos += PREDICTION_LENGTH

        # 达到最大窗口上限则提前结束
        if MAX_WINDOWS is not None and window_count >= MAX_WINDOWS:
            print(f"\n⚠️  已达最大推理窗口上限 ({MAX_WINDOWS})，提前停止（可修改脚本顶部 MAX_WINDOWS 参数）。")
            break

    print(f"\n✅ 滚动推理完成: 有效窗口={window_count}, 跳过窗口={skipped_windows}, "
          f"评估点={len(all_actual)}")

    if not all_actual:
        print("❌ 没有任何有效的评估点，无法生成图表。")
        return

    pred_median = np.array(all_pred_median)
    pred_low    = np.array(all_pred_low)
    pred_high   = np.array(all_pred_high)
    actual      = np.array(all_actual)
    x_axis      = np.arange(1, len(actual) + 1)

    # --- 精度评估（四指标） ---
    mae, rmse, smape, wape = calc_metrics(pred_median, actual)
    print(f"\n📈 预测精度评估（中位数预测 vs 真实值，共 {len(actual)} 点）:")
    print(f"   MAE   (平均绝对误差)           = {mae:.4f}")
    print(f"   RMSE  (均方根误差)             = {rmse:.4f}")
    print(f"   sMAPE (对称平均绝对百分比误差)  = {smape:.2f}%   ← 更稳健的百分比指标")
    print(f"   WAPE  (加权绝对百分比误差)      = {wape:.2f}%   ← 等价于 MAE/mean(actual)")

    # --- 每日总流量对比 ---
    print("\n📅 每日总流量预测误差分析:")
    daily_df = pd.DataFrame({
        "timestamp": pd.to_datetime(all_timestamps),
        "actual": actual,
        "pred": pred_median
    })
    daily_df['date'] = daily_df['timestamp'].dt.date
    daily_sums = daily_df.groupby('date')[['actual', 'pred']].sum()
    daily_sums['abs_error'] = np.abs(daily_sums['pred'] - daily_sums['actual'])
    daily_sums['error_pct'] = (daily_sums['abs_error'] / (daily_sums['actual'] + 1e-8)) * 100
    
    for date, row in daily_sums.iterrows():
        print(f"   [{date}] 实际总量={row['actual']:8.2f} | 预测总量={row['pred']:8.2f} | 误差={row['abs_error']:6.2f} ({row['error_pct']:5.2f}%)")

    print("\n📊 正在生成交互式对比图 (包含平移缩放功能)...")

    # --- 绘图 (Plotly 交互式图表) ---
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.08, row_heights=[0.7, 0.3],
        subplot_titles=("Actual (Green) vs Forecast (Red dashed) with 80% Confidence Band", 
                        "Prediction Error (Pred - Actual)")
    )

    t_axis = daily_df['timestamp']

    # 1. 置信带 (为了填充效果，需要先绘制上界，再绘制下界并设 fill='tonexty')
    fig.add_trace(go.Scatter(
        x=t_axis, y=pred_high, mode='lines',
        line=dict(width=0), showlegend=False, hoverinfo='skip'
    ), row=1, col=1)
    
    fig.add_trace(go.Scatter(
        x=t_axis, y=pred_low, mode='lines', fill='tonexty',
        fillcolor='rgba(230, 57, 70, 0.15)', line=dict(width=0),
        name='80% Confidence Band'
    ), row=1, col=1)

    # 2. 真实值
    fig.add_trace(go.Scatter(
        x=t_axis, y=actual, mode='lines',
        name='Actual (Ground Truth)', line=dict(color='#2dc653', width=1.5)
    ), row=1, col=1)

    # 3. 预测值中位数
    fig.add_trace(go.Scatter(
        x=t_axis, y=pred_median, mode='lines',
        name='Forecast (Median)', line=dict(color='#e63946', width=1.5, dash='dash')
    ), row=1, col=1)

    # 4. 下方误差点状/柱状图
    error = pred_median - actual
    error_colors = ['#e05c5c' if e >= 0 else '#4a85c9' for e in error]
    fig.add_trace(go.Bar(
        x=t_axis, y=error, name='Error',
        marker_color=error_colors
    ), row=2, col=1)

    # 在图表上方拼接待展示的重要指标文本
    info = (f"MAE={mae:.4f}   RMSE={rmse:.4f}   "
            f"sMAPE={smape:.2f}%   WAPE={wape:.2f}%   "
            f"Windows={window_count}   Skipped={skipped_windows}")

    fig.update_layout(
        title=f"<b>Rolling Forecast vs Actual — Amazon Chronos-2</b><br><sup>{info}</sup>",
        height=750,
        hovermode="x unified",
        margin=dict(l=50, r=30, t=100, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    fig.update_yaxes(title_text="Traffic Signal Ratio", row=1, col=1)
    fig.update_yaxes(title_text="Error", row=2, col=1)

    try:
        out_dir = os.path.dirname(PLOT_SAVE_PATH)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        fig.write_html(PLOT_SAVE_PATH)
        print("-" * 56)
        print(f"🎉 交互式图表已保存至: {os.path.abspath(PLOT_SAVE_PATH)}")
        print(f"👉 请在浏览器中双击打开 {PLOT_SAVE_PATH} 以进行缩放查看。")
    except Exception as e:
        print(f"❌ 保存图表时出错: {e}")


if __name__ == "__main__":
    main()
