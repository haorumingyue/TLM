from dataclasses import dataclass
from typing import List, Dict
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Slider
import matplotlib

# 配置matplotlib中文字体支持
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']  # 用来正常显示中文标签
matplotlib.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号

@dataclass
class CoalPacket:
    mass: float      # 质量 (kg)
    speed: float     # 速度 (m/s)
    length: float    # 长度 (m)
    position: float  # 头部位置 (m)

    @property
    def tail_position(self) -> float:
        """计算尾部位置"""
        return self.position - self.length

    @property
    def linear_density(self) -> float:
        """计算线性密度 (kg/m)"""
        return self.mass / self.length if self.length > 0 else 0


class Belt:
    def __init__(self, belt_id: str, name: str, speed: float, length: float):
        self.belt_id = belt_id          # 皮带ID
        self.name = name                # 皮带名称
        self.speed = speed              # 皮带速度 (m/s)
        self.length = length            # 皮带长度 (m)
        self.packets: List[CoalPacket] = []  # 煤包列表
    
    def add_packet(self, packet: CoalPacket) -> None:
        self.packets.append(packet)
    
    def update(self, dt: float) -> None:
        # 更新所有煤包的位置
        for packet in self.packets:
            packet.position += packet.speed * dt
        
        # 移除已经离开皮带的煤包
        self.packets = [p for p in self.packets if p.tail_position <= self.length]
    
    def transfer(self) -> List[CoalPacket]:
        transferred = [p for p in self.packets if p.position > self.length]
        self.packets = [p for p in self.packets if p.position <= self.length]
        return transferred
    
    def get_coal_distribution(self, resolution: float = 1.0) -> Dict[str, np.ndarray]:
        """获取煤量分布
        
        Args:
            resolution: 采样分辨率 (m)，每个采样点代表1米间隔
        
        Returns:
            包含位置和重量数组的字典（每个采样点的重量，单位：kg）
        """
        # 每米一个采样点（resolution=1.0时）
        # 对于很长的皮带，限制采样点数量以保证性能，但保证至少每米一个点
        if resolution <= 1.0:
            num_points = max(int(self.length), 1)  # 每米一个点
        else:
            num_points = max(200, int(np.ceil(self.length / resolution)))
        
        x = np.linspace(0, self.length, num_points)
        y = np.zeros(num_points)  # 每个采样点的重量（kg）
        
        # 每个采样间隔的实际宽度
        actual_res = self.length / num_points if num_points > 1 else resolution
        
        for packet in self.packets:
            start_pos = max(0, packet.tail_position)
            end_pos = min(self.length, packet.position)
            
            if start_pos >= end_pos:
                continue
            
            # 计算煤包覆盖的采样点范围
            start_idx = int(start_pos / actual_res)
            end_idx = int(end_pos / actual_res)
            
            # 边界保护
            start_idx = min(start_idx, num_points - 1)
            end_idx = min(end_idx, num_points - 1)
            
            if start_idx <= end_idx:
                # 计算每个采样间隔内煤包的重量
                for idx in range(start_idx, end_idx + 1):
                    # 计算该采样间隔的起始和结束位置
                    interval_start = idx * actual_res
                    interval_end = (idx + 1) * actual_res
                    
                    # 计算煤包与这个采样间隔的重叠长度
                    overlap_start = max(start_pos, interval_start)
                    overlap_end = min(end_pos, interval_end)
                    overlap_length = max(0, overlap_end - overlap_start)
                    
                    # 该间隔内的重量 = 线性密度 × 重叠长度
                    if overlap_length > 0:
                        y[idx] += packet.linear_density * overlap_length
        
        return {'position': x, 'density': y}


class CoalFlowSystem:
    """煤流系统，管理多条皮带的煤流传输"""
    
    def __init__(self):
        """初始化4条不同长度的皮带"""
        self.belts: List[Belt] = [
            Belt(belt_id="B1", name="主运大巷皮带", speed=4.0, length=5000.0),
            Belt(belt_id="B2", name="主斜井皮带", speed=4.0, length=1160.0),
            Belt(belt_id="B3", name="101皮带", speed=4.0, length=147.0),
            Belt(belt_id="B4", name="102皮带", speed=4.0, length=54.0)
        ]
        self.time = 0.0
        # 流量统计：跟踪两个输入点的累积流量
        self.input_A_total_mass = 0.0  # 输入点A累积总质量 (kg)
        self.input_B_total_mass = 0.0  # 输入点B累积总质量 (kg)
        self.input_A_flow_rate = 0.0   # 输入点A当前流量 (kg/s)
        self.input_B_flow_rate = 0.0   # 输入点B当前流量 (kg/s)
        self.last_input_A_mass = 0.0   # 用于计算瞬时流量
        self.last_input_B_mass = 0.0
        self.last_flow_update_time = 0.0
    
    def add_coal_input(self, belt_index: int, mass: float, position: float = 0.0, input_source: str = None) -> None:
        """在指定皮带上添加煤流输入
        
        Args:
            belt_index: 皮带索引 (0-3)
            mass: 煤包质量 (kg)
            position: 投放位置 (m)
            input_source: 输入源标识 ('A' 或 'B')，如果为None则根据position自动判断
        """
        if 0 <= belt_index < len(self.belts):
            belt = self.belts[belt_index]
            # 根据速度和时间步长计算煤包长度
            length = belt.speed * 0.5  # 假设0.5秒的投放间隔
            packet = CoalPacket(
                mass=mass,
                speed=belt.speed,
                length=length,
                position=position + length  # 头部位置 = 投放位置 + 长度
            )
            belt.add_packet(packet)
            
            # 跟踪流量统计（根据position判断输入源：0为A，2500为B）
            if input_source is None:
                if abs(position - 0.0) < 0.1:
                    input_source = 'A'
                elif abs(position - 2500.0) < 0.1:
                    input_source = 'B'
            
            if input_source == 'A':
                self.input_A_total_mass += mass
            elif input_source == 'B':
                self.input_B_total_mass += mass
    
    def update(self, dt: float) -> None:
        """更新整个煤流系统
        
        Args:
            dt: 时间步长 (s)
        """
        self.time += dt
        
        # 1. 更新所有皮带上的煤包位置
        for belt in self.belts:
            belt.update(dt)
        
        # 2. 处理皮带间的煤包传递
        for i in range(len(self.belts) - 1):
            current_belt = self.belts[i]
            next_belt = self.belts[i + 1]
            
            # 获取需要传递的煤包
            transferred_packets = current_belt.transfer()
            
            # 将煤包添加到下一条皮带
            for packet in transferred_packets:
                # 调整煤包速度为下一条皮带的速度
                packet.speed = next_belt.speed
                # 重置位置到下一条皮带的起点
                packet.position = packet.length
                next_belt.add_packet(packet)
        
        # 3. 最后一条皮带的煤包传递（排出系统）
        self.belts[-1].transfer()
    
    def get_all_distributions(self, resolution: float = 1.0) -> Dict[str, Dict[str, np.ndarray]]:
        distributions = {}
        for belt in self.belts:
            distributions[belt.belt_id] = belt.get_coal_distribution(resolution)
        return distributions
    
    def get_system_info(self) -> Dict[str, any]:
        info = {
            'time': self.time,
            'belts': []
        }
        
        for belt in self.belts:
            belt_info = {
                'id': belt.belt_id,
                'name': belt.name,
                'length': belt.length,
                'speed': belt.speed,
                'packet_count': len(belt.packets),
                'total_mass': sum(p.mass for p in belt.packets)
            }
            info['belts'].append(belt_info)
        
        return info
    
    def get_flow_statistics(self, dt: float = 0.5) -> Dict[str, float]:
        """获取流量统计信息
        
        Args:
            dt: 时间步长，用于计算瞬时流量
        
        Returns:
            包含流量统计信息的字典
        """
        # 计算平均流量（累积量除以时间）
        avg_flow_A = self.input_A_total_mass / max(self.time, 0.1) if self.time > 0 else 0.0
        avg_flow_B = self.input_B_total_mass / max(self.time, 0.1) if self.time > 0 else 0.0
        
        # 更新瞬时流量（使用最近的统计数据，基于平均流量）
        self.input_A_flow_rate = avg_flow_A
        self.input_B_flow_rate = avg_flow_B
        
        return {
            'input_A_total': self.input_A_total_mass,
            'input_B_total': self.input_B_total_mass,
            'input_A_flow_rate': self.input_A_flow_rate,
            'input_B_flow_rate': self.input_B_flow_rate
        }


def visualize_system():
    """可视化煤流系统"""
    system = CoalFlowSystem()
    
    # 创建图形和子图，左侧留出空间给控制面板
    fig = plt.figure(figsize=(16, 10))
    
    # 调整布局：左侧用于图表，右侧用于控制面板
    gs = fig.add_gridspec(4, 2, width_ratios=[14, 5], hspace=0.4, left=0.08, right=0.97, top=0.95, bottom=0.05)
    axes = [fig.add_subplot(gs[i, 0]) for i in range(4)]
    
    # 为每条皮带创建绘图元素
    lines = []
    polys = []
    current_y_limits = [10.0] * 4  # 初始Y轴上限
    title_texts = []  # 存储标题文本对象，用于动态更新
    belt_info_texts = []  # 存储每条皮带的总量文本（显示在图表上）
    input_flow_texts = []  # 存储输入流量文本（显示在第一条皮带图表上）
    
    for i, ax in enumerate(axes):
        belt = system.belts[i]
        ax.set_xlim(0, belt.length)
        ax.set_ylim(0, 10)
        title_text = ax.set_title(f"{belt.name} - 长度: {belt.length}m, 速度: {belt.speed:.2f} m/s", fontsize=11)
        title_texts.append(title_text)
        ax.set_xlabel("Position (m)")
        ax.set_ylabel("Coal Weight (kg)")
        ax.grid(True, alpha=0.3)
        
        line, = ax.plot([], [], color='#2c3e50', lw=2)
        poly = ax.fill_between([], [], color='#2c3e50', alpha=0.3)
        lines.append(line)
        polys.append(poly)
        
        # 在图表上添加实时总重量显示文本（右上角）
        info_text = ax.text(0.98, 0.95, f'实时总重量: 0.0 kg', 
                           transform=ax.transAxes, fontsize=10,
                           verticalalignment='top', horizontalalignment='right',
                           bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        belt_info_texts.append(info_text)
        
        # 对于第一条皮带，添加输入流量信息显示（左上角，横向两列排列）
        if i == 0:
            # 左侧列：输入点A信息
            input_A_total_text = ax.text(0.02, 0.95, '输入点A累积: 0.0 kg', 
                                         transform=ax.transAxes, fontsize=9,
                                         verticalalignment='top', horizontalalignment='left',
                                         bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
            input_A_flow_text = ax.text(0.02, 0.85, '输入点A流量: 0.0 kg/s', 
                                        transform=ax.transAxes, fontsize=9,
                                        verticalalignment='top', horizontalalignment='left',
                                        bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
            # 右侧列：输入点B信息
            input_B_total_text = ax.text(0.30, 0.95, '输入点B累积: 0.0 kg', 
                                         transform=ax.transAxes, fontsize=9,
                                         verticalalignment='top', horizontalalignment='left',
                                         bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))
            input_B_flow_text = ax.text(0.30, 0.85, '输入点B流量: 0.0 kg/s', 
                                        transform=ax.transAxes, fontsize=9,
                                        verticalalignment='top', horizontalalignment='left',
                                        bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))
            input_flow_texts = [input_A_total_text, input_A_flow_text, 
                               input_B_total_text, input_B_flow_text]
    
    # 时间显示
    time_text = fig.text(0.02, 0.98, '', transform=fig.transFigure, 
                        verticalalignment='top', fontsize=12, weight='bold')
    
    # 创建控制面板：速度滑块
    slider_axes = []
    sliders = []
    slider_y_start = 0.82
    slider_spacing = 0.15  # 减小间距以节省空间
    
    def update_speed(belt_index, val):
        """更新皮带速度的回调函数"""
        new_speed = sliders[belt_index].val
        belt = system.belts[belt_index]
        
        # 更新皮带速度
        belt.speed = new_speed
        
        # 更新该皮带上的所有煤包速度
        for packet in belt.packets:
            packet.speed = new_speed
        
        # 更新标题显示
        title_texts[belt_index].set_text(
            f"{belt.name} - 长度: {belt.length}m, 速度: {belt.speed:.2f} m/s"
        )
        fig.canvas.draw_idle()
    
    # 添加控制面板标题
    fig.text(0.70, 0.97, '速度控制 (m/s)', transform=fig.transFigure,
             fontsize=12, weight='bold', verticalalignment='top')
    
    # 为每条皮带创建速度滑块
    for i in range(4):
        belt = system.belts[i]
        # 计算滑块位置（从顶部开始，每个滑块之间有间距）
        slider_y = slider_y_start - i * slider_spacing
        
        # 添加皮带名称标签（缩短名称以适应布局）
        short_name = belt.name[:6] if len(belt.name) > 6 else belt.name
        fig.text(0.70, slider_y + 0.025, f'{short_name}:', transform=fig.transFigure,
                fontsize=9, verticalalignment='center')
        
        # 创建滑块轴
        ax_slider = fig.add_axes([0.70, slider_y, 0.25, 0.04])
        slider_axes.append(ax_slider)
        
        # 创建滑块 (速度范围: 0.1 到 10.0 m/s)
        slider = Slider(ax_slider, '', 0.1, 10.0, 
                       valinit=belt.speed, valfmt='%.2f')
        sliders.append(slider)
        
        # 连接回调函数（使用lambda捕获索引）
        slider.on_changed(lambda val, idx=i: update_speed(idx, val))
    
    # 新增：随机输入生成器参数
    import random
    A_base = 10.0   # kg/步（等效于 dt=0.5 下的每步质量）
    B_base = 8.0
    burst_prob_A = 0.05
    burst_prob_B = 0.04
    burst_min = 1.5
    burst_max = 3.0
    normal_min = 0.6
    normal_max = 1.4
    noise_range = 0.2  # ±20%
    
    def sample_mass(base, burst_prob):
        # 状态倍率
        if random.random() < burst_prob:
            mult = random.uniform(burst_min, burst_max)
        else:
            mult = random.uniform(normal_min, normal_max)
        # 噪声
        noise = random.uniform(1 - noise_range, 1 + noise_range)
        return max(0.0, base * mult * noise)
    
    def update(frame):
        nonlocal current_y_limits
        
        dt = 0.5
        
        # 每帧运行多次以加速显示
        for _ in range(5):
            # 随机化两个输入源的质量
            mass_A = sample_mass(A_base, burst_prob_A)
            mass_B = sample_mass(B_base, burst_prob_B)
            
            # 在第一条皮带添加煤流输入（A源在起点，B源在中段）
            system.add_coal_input(belt_index=0, mass=mass_A, position=0, input_source='A')
            system.add_coal_input(belt_index=0, mass=mass_B, position=2500.0, input_source='B')
            
            # 更新系统
            system.update(dt)
        
        # 更新时间显示
        time_text.set_text(f'Time: {system.time:.1f}s')
        
        # 更新每条皮带的显示
        for i, belt in enumerate(system.belts):
            dist = belt.get_coal_distribution(resolution=1.0)
            x, y = dist['position'], dist['density']
            
            # 更新线条
            lines[i].set_data(x, y)
            
            # 更新填充
            polys[i].remove()
            polys[i] = axes[i].fill_between(x, y, color='#2c3e50', alpha=0.3)
            
            # 更新标题显示当前速度
            title_texts[i].set_text(
                f"{belt.name} - 长度: {belt.length}m, 速度: {belt.speed:.2f} m/s"
            )
            
            # 动态调整Y轴（平滑过渡）
            if len(y) > 0:
                target_y = max(10.0, float(np.max(y)) * 1.3)
                smooth_factor = 0.3 if target_y > current_y_limits[i] else 0.1
                current_y_limits[i] += (target_y - current_y_limits[i]) * smooth_factor
                axes[i].set_ylim(0, current_y_limits[i])
            
            # 更新图表上的实时总重量显示
            total_mass = sum(p.mass for p in belt.packets)
            belt_info_texts[i].set_text(f'实时总重量: {total_mass:.1f} kg')
        
        # 更新第一条皮带上的输入流量信息
        if input_flow_texts:
            flow_stats = system.get_flow_statistics(dt)
            input_flow_texts[0].set_text(f'输入点A累积: {flow_stats["input_A_total"]:.1f} kg')
            input_flow_texts[1].set_text(f'输入点A流量: {flow_stats["input_A_flow_rate"]:.2f} kg/s')
            input_flow_texts[2].set_text(f'输入点B累积: {flow_stats["input_B_total"]:.1f} kg')
            input_flow_texts[3].set_text(f'输入点B流量: {flow_stats["input_B_flow_rate"]:.2f} kg/s')
        
        return lines + [time_text] + belt_info_texts + input_flow_texts + title_texts
    
    # 创建动画
    print("开始模拟煤流系统...")
    ani = FuncAnimation(fig, update, interval=50, blit=False)
    plt.show()


if __name__ == "__main__":
    visualize_system()