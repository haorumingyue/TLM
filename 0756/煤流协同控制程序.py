from dataclasses import dataclass
from typing import List, Dict
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Slider
import matplotlib
import random

# 随机输入生成器参数
burst_min = 1.0
burst_max = 1.0
normal_min = 0.9  # 缩小范围，更接近目标值
normal_max = 1.1  # 缩小范围，更接近目标值
noise_range = 0.05  # ±5%，减小噪声范围

def sample_mass(target_flow_rate, burst_prob, dt=0.5):
    """基于目标流量和噪声生成煤包质量
    
    Args:
        target_flow_rate: 目标流量 (t/h)
        burst_prob: 爆发概率
        dt: 时间步长 (s)
        
    Returns:
        煤包质量 (t)
    """
    # 将t/h转换为t/step
    base = target_flow_rate * (dt / 3600.0)
    
    # 状态倍率
    if random.random() < burst_prob:
        mult = random.uniform(burst_min, burst_max)
    else:
        mult = random.uniform(normal_min, normal_max)
    # 噪声
    noise = random.uniform(1 - noise_range, 1 + noise_range)
    return max(0.0, base * mult * noise)

# 配置matplotlib中文字体支持
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']  # 用来正常显示中文标签
matplotlib.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号

@dataclass
class CoalPacket:
    mass: float      # 质量 (t)
    speed: float     # 速度 (m/s)
    length: float    # 长度 (m)
    position: float  # 头部位置 (m)

    @property
    def tail_position(self) -> float:
        """计算尾部位置"""
        return self.position - self.length

    @property
    def linear_density(self) -> float:
        """计算线性密度 (t/m)"""
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
            包含位置和重量数组的字典（每个采样点的重量，单位：t）
        """
        # 每米一个采样点（resolution=1.0时）
        # 对于很长的皮带，限制采样点数量以保证性能，但保证至少每米一个点
        if resolution <= 1.0:
            num_points = max(int(self.length), 1)  # 每米一个点
        else:
            num_points = max(200, int(np.ceil(self.length / resolution)))
        
        x = np.linspace(0, self.length, num_points)
        y = np.zeros(num_points)  # 每个采样点的重量（t）
        
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
            Belt(belt_id="B3", name="101皮带", speed=4.0, length=147.0)
        ]
        self.time = 0.0
        # 流量统计：跟踪两个输入点的累积流量
        self.input_A_total_mass = 0.0  # 输入点A累积总质量 (t)
        self.input_B_total_mass = 0.0  # 输入点B累积总质量 (t)
        self.input_A_flow_rate = 0.0   # 输入点A当前流量 (t/h)
        self.input_B_flow_rate = 0.0   # 输入点B当前流量 (t/h)
        self.input_C_total_mass = 0.0  # 输入点C累积总质量 (t)
        self.input_C_flow_rate = 0.0   # 输入点C当前流量 (t/h)
        self.last_input_A_mass = 0.0   # 用于计算瞬时流量
        self.last_input_B_mass = 0.0
        self.last_input_C_mass = 0.0
        self.last_flow_update_time = 0.0
        
        # 速度控制状态：用于实现降速延时判定
        self.speed_control_state = [
            {
                'last_speed': 4.0,  # 主运皮带，初始速度设置为4.0m/s
                'last_q_range': 1,   # 初始流量范围设置为最高范围，以便触发降速逻辑
                'deceleration_timer': 0.0,  # 降速计时器 (s)
                'deceleration_triggered': False,  # 是否已触发降速判定
                'target_speed_after_delay': 0.0  # 延时后的目标速度
            },
            {
                'last_speed': 4.0,  # 主斜井皮带
                'last_q_range': 1,   # 1: [800,1000], 2: [600,800), 3: [400,600), 4: <400
                'deceleration_timer': 0.0,
                'deceleration_triggered': False,
                'target_speed_after_delay': 0.0
            },
            {
                'last_speed': 4.0,  # 101皮带
                'last_q_range': 1,   # 1: [800,1000], 2: [600,800), 3: [400,600), 4: <400
                'deceleration_timer': 0.0,
                'deceleration_triggered': False,
                'target_speed_after_delay': 0.0
            }
        ]
        self.deceleration_delay = 5 * 60  # 5分钟，单位：秒
    
    def add_coal_input(self, belt_index: int, mass: float, position: float = 0.0, input_source: str = None) -> None:
        """在指定皮带上添加煤流输入
        
        Args:
            belt_index: 皮带索引 (0-2)
            mass: 煤包质量 (t)
            position: 投放位置 (m)
            input_source: 输入源标识 ('A', 'B' 或 'C')，如果为None则根据position自动判断
        """
        if 0 <= belt_index < len(self.belts):
            belt = self.belts[belt_index]
            # 固定煤包长度为1米，避免速度对长度的影响导致流量计算异常
            length = 1.0  # 固定煤包长度为1米
            packet = CoalPacket(
                mass=mass,
                speed=belt.speed,
                length=length,
                position=position + length  # 头部位置 = 投放位置 + 长度
            )
            belt.add_packet(packet)
            
            # 跟踪流量统计（根据position和belt_index判断输入源）
            if input_source is None:
                if belt_index == 0:
                    if abs(position - 0.0) < 0.1:
                        input_source = 'A'
                    elif abs(position - 2500.0) < 0.1:
                        input_source = 'B'
                elif belt_index == 1 and abs(position - 0.0) < 0.1:
                    input_source = 'C'
            
            if input_source == 'A':
                self.input_A_total_mass += mass
            elif input_source == 'B':
                self.input_B_total_mass += mass
            elif input_source == 'C':
                self.input_C_total_mass += mass
    
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
            # 跳过主运皮带(B1)的传递，因为它的煤落入井下煤仓
            if i == 0:
                # 直接移除B1上离开的煤包，不传递到后续皮带
                self.belts[i].transfer()
            else:
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
        # 使用传入的dt作为时间增量，确保与实际煤包生成周期一致
        time_delta = dt
        
        # 计算最近时间段内的平均流量
        if time_delta > 0:
            # 计算每个输入点的质量增量
            delta_mass_A = self.input_A_total_mass - self.last_input_A_mass
            delta_mass_B = self.input_B_total_mass - self.last_input_B_mass
            delta_mass_C = self.input_C_total_mass - self.last_input_C_mass
            
            # 计算瞬时流量（质量增量/时间增量，转换为t/h）
            # 注意：delta_mass是t，time_delta是s，所以需要乘以3600将t/s转换为t/h
            flow_A = (delta_mass_A / time_delta) * 3600
            flow_B = (delta_mass_B / time_delta) * 3600
            flow_C = (delta_mass_C / time_delta) * 3600
            
            # 更新历史值
            self.last_input_A_mass = self.input_A_total_mass
            self.last_input_B_mass = self.input_B_total_mass
            self.last_input_C_mass = self.input_C_total_mass
            self.last_flow_update_time = self.time
        else:
            flow_A = 0.0
            flow_B = 0.0
            flow_C = 0.0
        
        # 更新瞬时流量（平滑过渡以避免剧烈波动）
        alpha = 0.9  # 增加平滑系数，使流量更快响应目标值
        
        self.input_A_flow_rate = alpha * flow_A + (1 - alpha) * self.input_A_flow_rate
        self.input_B_flow_rate = alpha * flow_B + (1 - alpha) * self.input_B_flow_rate
        self.input_C_flow_rate = alpha * flow_C + (1 - alpha) * self.input_C_flow_rate
        
        return {
            'input_A_total': self.input_A_total_mass,
            'input_B_total': self.input_B_total_mass,
            'input_C_total': self.input_C_total_mass,
            'input_A_flow_rate': self.input_A_flow_rate,
            'input_B_flow_rate': self.input_B_flow_rate,
            'input_C_flow_rate': self.input_C_flow_rate
        }
    
    def calculate_belt_max_flow(self, belt_index: int) -> float:
        """计算皮带的最大流量
        
        Args:
            belt_index: 皮带索引
            
        Returns:
            最大流量 (t/h)
        """
        belt = self.belts[belt_index]
        
        if not belt.packets:
            return 0.0
        
        # 所有皮带都使用相同的方法计算最大流量点
        # 将皮带分成多个小段，计算每个小段的线性密度
        segment_length = 1.0  # 每个小段1米
        num_segments = max(int(belt.length / segment_length), 1)  # 至少1个小段
        
        # 初始化每个小段的质量为0
        segment_masses = [0.0] * num_segments
        
        # 遍历所有煤包，将质量分配到对应的小段
        for packet in belt.packets:
            # 计算煤包的起始和结束位置
            start_pos = packet.tail_position  # 煤包的尾部位置
            end_pos = packet.position  # 煤包的头部位置
            
            # 确保煤包在皮带上
            start_pos = max(0, start_pos)
            end_pos = min(belt.length, end_pos)
            
            if start_pos >= end_pos:
                continue
            
            # 煤包的有效长度和线性密度
            packet_effective_length = end_pos - start_pos
            if packet_effective_length <= 0:
                continue
                
            packet_effective_mass = (packet_effective_length / packet.length) * packet.mass
            linear_density = packet_effective_mass / packet_effective_length
            
            # 遍历煤包覆盖的所有小段
            current_pos = start_pos
            while current_pos < end_pos:
                # 确定当前小段的索引和范围
                current_segment = int(current_pos / segment_length)
                if current_segment >= num_segments:
                    break
                    
                segment_start = current_segment * segment_length
                segment_end = (current_segment + 1) * segment_length
                
                # 计算煤包与当前小段的重叠长度
                overlap_start = max(current_pos, segment_start)
                overlap_end = min(end_pos, segment_end)
                overlap_length = max(0, overlap_end - overlap_start)
                
                # 计算该小段应获得的质量
                if overlap_length > 0:
                    mass_in_segment = linear_density * overlap_length
                    segment_masses[current_segment] += mass_in_segment
                
                # 移动到下一个小段
                current_pos = segment_end
        
        # 找到质量最大的小段
        if segment_masses:
            max_segment_mass = max(segment_masses)
        else:
            max_segment_mass = 0.0
        
        # 计算该小段的线性密度 (t/m)
        max_density = max_segment_mass / segment_length
        
        # 计算最大流量 (t/h) = 线性密度 * 带速 * 3600
        max_flow = max_density * belt.speed * 3600
        
        return max_flow
    
    def adjust_belt_speed(self, belt_index: int, dt: float) -> None:
        """根据流量调整皮带速度
        
        Args:
            belt_index: 皮带索引
            dt: 时间增量（秒），用于更新降速计时器
        """
        belt = self.belts[belt_index]
        state = self.speed_control_state[belt_index]
        
        # 确定当前流量范围
        if belt_index == 0:  # 主运皮带
            # 计算Q_主运_max
            Q_A = self.input_A_flow_rate
            Q_B = self.input_B_flow_rate
            Q_d = Q_A + Q_B
            Q_max_t = self.calculate_belt_max_flow(belt_index)
            Q_current = max(Q_d, Q_max_t)
            
            # 确定当前Q_range
            if Q_current >= 1400:
                current_q_range = 1
                target_speed = 4.0
            elif Q_current >= 1000:
                current_q_range = 2
                target_speed = 3.2
            elif Q_current >= 600:
                current_q_range = 3
                target_speed = 2.4
            else:
                current_q_range = 4
                target_speed = 1.6
        
        elif belt_index == 1:  # 主斜井皮带
            # 计算Q_主斜井_max
            Q_C = self.input_C_flow_rate
            Q_max_t = self.calculate_belt_max_flow(belt_index)
            Q_current = max(Q_C, Q_max_t)
            
            # 确定当前Q_range
            if Q_current >= 800:
                current_q_range = 1
                target_speed = 2.6
            elif Q_current >= 600:
                current_q_range = 2
                target_speed = 2.2
            elif Q_current >= 400:
                current_q_range = 3
                target_speed = 1.8
            else:
                current_q_range = 4
                target_speed = 1.4
        
        elif belt_index == 2:  # 101皮带
            # 计算Q_101_max
            Q_current = self.calculate_belt_max_flow(belt_index)
            
            # 确定当前Q_range
            if Q_current >= 800:
                current_q_range = 1
                target_speed = 2.4
            elif Q_current >= 600:
                current_q_range = 2
                target_speed = 2.0
            elif Q_current >= 400:
                current_q_range = 3
                target_speed = 1.6
            else:
                current_q_range = 4
                target_speed = 1.2
        
        else:
            return
        
        # 处理速度控制逻辑
        if current_q_range > state['last_q_range']:  # 流量下降，可能需要降速
            if target_speed < belt.speed:
                if not state['deceleration_triggered']:
                    # 首次触发降速判定
                    state['deceleration_triggered'] = True
                    state['deceleration_timer'] = 0.0
                    state['target_speed_after_delay'] = target_speed
                else:
                    # 已经触发降速判定，更新计时器
                    state['deceleration_timer'] += dt  # 使用实际的时间增量
                    
                    if state['deceleration_timer'] >= self.deceleration_delay:
                        # 延时结束，执行降速
                        state['deceleration_triggered'] = False
                        state['last_speed'] = state['target_speed_after_delay']
                        state['last_q_range'] = current_q_range
                        state['deceleration_timer'] = 0.0
                        
                        # 更新皮带速度和煤包速度
                        belt.speed = state['target_speed_after_delay']
                        for packet in belt.packets:
                            packet.speed = state['target_speed_after_delay']
        
        elif current_q_range < state['last_q_range']:  # 流量上升，立即升速
            if target_speed > belt.speed:
                # 取消任何正在进行的降速判定
                state['deceleration_triggered'] = False
                state['deceleration_timer'] = 0.0
                
                # 更新状态
                state['last_speed'] = target_speed
                state['last_q_range'] = current_q_range
                
                # 更新皮带速度和煤包速度
                belt.speed = target_speed
                for packet in belt.packets:
                    packet.speed = target_speed
        
        else:  # 流量范围不变
            if state['deceleration_triggered']:
                # 如果正在进行降速判定，但流量范围又回到原来的范围，取消判定
                state['deceleration_triggered'] = False
                state['deceleration_timer'] = 0.0
                state['target_speed_after_delay'] = 0.0


def visualize_system():
    """可视化煤流系统"""
    system = CoalFlowSystem()
    
    # 定义爆发概率变量
    burst_prob_A = 0.0
    burst_prob_B = 0.0
    burst_prob_C = 0.0
    
    # 创建图形和子图，左侧留出空间给控制面板
    fig = plt.figure(figsize=(16, 10))
    
    # 调整布局：左侧用于图表，右侧用于控制面板
    gs = fig.add_gridspec(3, 2, width_ratios=[14, 5], hspace=0.4, left=0.08, right=0.97, top=0.95, bottom=0.05)
    axes = [fig.add_subplot(gs[i, 0]) for i in range(3)]
    
    # 为每条皮带创建绘图元素
    lines = []
    polys = []
    current_y_limits = [1.0] * 3  # 初始Y轴上限为1.0，更适合实际煤量范围
    title_texts = []  # 存储标题文本对象，用于动态更新
    belt_info_texts = []  # 存储每条皮带的总量文本（显示在图表上）
    input_flow_texts = []  # 存储输入流量文本（显示在第一条皮带图表上）
    
    for i, ax in enumerate(axes):
        belt = system.belts[i]
        ax.set_xlim(0, belt.length)
        ax.set_ylim(0, 1)  # 初始Y轴上限为1.0，更适合实际煤量范围
        title_text = ax.set_title(f"{belt.name} - 长度: {belt.length}m, 速度: {belt.speed:.2f} m/s", fontsize=11)
        title_texts.append(title_text)
        ax.set_xlabel("Position (m)")
        ax.set_ylabel("Coal Weight (t)")
        ax.grid(True, alpha=0.3)
        
        line, = ax.plot([], [], color='#2c3e50', lw=2)
        poly = ax.fill_between([], [], color='#2c3e50', alpha=0.3)
        lines.append(line)
        polys.append(poly)
        
        # 在图表上添加实时总重量显示文本（右上角）
        info_text = ax.text(0.98, 0.95, f'实时总重量: 0.0 t', 
                           transform=ax.transAxes, fontsize=10,
                           verticalalignment='top', horizontalalignment='right',
                           bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        belt_info_texts.append(info_text)
        
        # 对于第一条皮带，添加输入流量信息显示（左上角，横向两列排列）
        if i == 0:
            # 左侧列：输入点A信息
            input_A_total_text = ax.text(0.02, 0.95, '输入点A累积: 0.0 t', 
                                         transform=ax.transAxes, fontsize=9,
                                         verticalalignment='top', horizontalalignment='left',
                                         bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
            input_A_flow_text = ax.text(0.02, 0.85, '输入点A流量: 0.0 t/h', 
                                        transform=ax.transAxes, fontsize=9,
                                        verticalalignment='top', horizontalalignment='left',
                                        bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
            # 右侧列：输入点B信息
            input_B_total_text = ax.text(0.30, 0.95, '输入点B累积: 0.0 t', 
                                         transform=ax.transAxes, fontsize=9,
                                         verticalalignment='top', horizontalalignment='left',
                                         bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))
            input_B_flow_text = ax.text(0.30, 0.85, '输入点B流量: 0.0 t/h', 
                                        transform=ax.transAxes, fontsize=9,
                                        verticalalignment='top', horizontalalignment='left',
                                        bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))
            input_flow_texts = [input_A_total_text, input_A_flow_text, 
                               input_B_total_text, input_B_flow_text]
        
        # 对于第二条皮带，添加输入点C的信息显示
        if i == 1:
            input_C_total_text = ax.text(0.02, 0.95, '输入点C累积: 0.0 t', 
                                         transform=ax.transAxes, fontsize=9,
                                         verticalalignment='top', horizontalalignment='left',
                                         bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.8))
            input_C_flow_text = ax.text(0.02, 0.85, '输入点C流量: 0.0 t/h', 
                                        transform=ax.transAxes, fontsize=9,
                                        verticalalignment='top', horizontalalignment='left',
                                        bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.8))
            input_flow_texts.extend([input_C_total_text, input_C_flow_text])
    
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
    for i in range(3):
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
    
    # 添加输入流量控制滑块（A、B在主运皮带，C在主斜井皮带）
    fig.text(0.70, 0.35, '流量控制 (t/h)', transform=fig.transFigure,
             fontsize=12, weight='bold', verticalalignment='top')
    
    # 输入A流量滑块
    ax_slider_A = fig.add_axes([0.70, 0.30, 0.25, 0.04])
    slider_A = Slider(ax_slider_A, '', 0.0, 1000.0, valinit=200.0, valfmt='%.1f')
    fig.text(0.70, 0.325, '输入A:', transform=fig.transFigure, fontsize=9, verticalalignment='center')
    
    # 输入B流量滑块
    ax_slider_B = fig.add_axes([0.70, 0.22, 0.25, 0.04])
    slider_B = Slider(ax_slider_B, '', 0.0, 1000.0, valinit=200.0, valfmt='%.1f')
    fig.text(0.70, 0.245, '输入B:', transform=fig.transFigure, fontsize=9, verticalalignment='center')
    
    # 输入C流量滑块
    ax_slider_C = fig.add_axes([0.70, 0.14, 0.25, 0.04])
    slider_C = Slider(ax_slider_C, '', 0.0, 1000.0, valinit=200.0, valfmt='%.1f')
    fig.text(0.70, 0.165, '输入C:', transform=fig.transFigure, fontsize=9, verticalalignment='center')
    
    # 存储输入滑块以便在更新函数中使用
    input_sliders = [slider_A, slider_B, slider_C]
    

    
    def update(frame):
        try:
            nonlocal current_y_limits
            
            # 使用动画实际的时间步长(50ms)，确保系统更新准确
            dt = 0.05
            
            # 每帧只添加一次煤包，避免流量被放大
            # 获取滑块值作为目标流量
            target_flow_A = slider_A.val
            target_flow_B = slider_B.val
            target_flow_C = slider_C.val
            
            # 添加调试打印：查看滑块值
            if frame % 5 == 0:
                print(f"Frame {frame}: 滑块值 - A={target_flow_A}, B={target_flow_B}, C={target_flow_C}")
            
            # 随机化三个输入源的质量，使用更小的随机范围
            # 由于每帧运行5次系统更新，实际时间步长是5*dt
            actual_dt = 5 * dt
            mass_A = sample_mass(target_flow_A, burst_prob_A, dt=actual_dt)
            mass_B = sample_mass(target_flow_B, burst_prob_B, dt=actual_dt)
            mass_C = sample_mass(target_flow_C, burst_prob_C, dt=actual_dt)
            
            # 添加调试打印：查看生成的煤包质量
            if frame % 5 == 0:
                print(f"Frame {frame}:")
                print(f"  实际时间步长: {actual_dt}s")
                print(f"  生成质量: A={mass_A:.6f}t, B={mass_B:.6f}t, C={mass_C:.6f}t")
                print(f"  理论质量 (A): {target_flow_A * (actual_dt / 3600.0):.6f}t")
                print(f"  理论流量 (A): {(mass_A / actual_dt) * 3600:.2f}t/h")
            
            # 在第一条皮带添加煤流输入（A源在起点，B源在中段）
            system.add_coal_input(belt_index=0, mass=mass_A, position=0, input_source='A')
            system.add_coal_input(belt_index=0, mass=mass_B, position=2500.0, input_source='B')
            
            # 在主斜井皮带添加煤流输入（C源在起点）
            system.add_coal_input(belt_index=1, mass=mass_C, position=0, input_source='C')
            
            # 每帧运行5次系统更新，恢复之前的时间流动速度
            for _ in range(5):
                # 更新系统
                system.update(dt)
                
                # 调整所有皮带速度
                for i in range(3):
                    system.adjust_belt_speed(i, dt)
            
            # 只在所有系统更新完成后更新一次流量统计
            system.get_flow_statistics(actual_dt)
            
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
                    max_y = float(np.max(y))
                    # 当有明显的煤流时，确保Y轴上限至少为最大煤流量的1.5倍
                    # 当没有煤流时，保持一个合理的上限
                    if max_y > 0.1:  # 有明显煤流
                        target_y = max(1.0, max_y * 1.5)
                        smooth_factor = 0.5  # 更快地调整Y轴上限
                    else:  # 几乎没有煤流
                        target_y = max(1.0, current_y_limits[i])  # 保持当前上限至少为1.0
                        smooth_factor = 0.1  # 缓慢调整
                    
                    # 更新Y轴上限
                    current_y_limits[i] += (target_y - current_y_limits[i]) * smooth_factor
                    axes[i].set_ylim(0, current_y_limits[i])
                
                # 更新图表上的实时总重量和最大煤流量显示
                total_mass = sum(p.mass for p in belt.packets)
                max_flow = system.calculate_belt_max_flow(i)
                belt_info_texts[i].set_text(f'实时总重量: {total_mass:.1f} t\n最大煤流量: {max_flow:.2f} t/h')
            
            # 调试：每10帧打印所有皮带的状态
            if frame % 5 == 0:
                # 主运皮带（索引0）
                main_belt = system.belts[0]
                Q_A = system.input_A_flow_rate
                Q_B = system.input_B_flow_rate
                Q_d = Q_A + Q_B
                Q_max_t = system.calculate_belt_max_flow(0)
                Q_current = max(Q_d, Q_max_t)
                total_mass_main = sum(p.mass for p in main_belt.packets)
                print(f"Frame {frame}: 主运皮带 - 输入A={Q_A:.2f}t/h, 输入B={Q_B:.2f}t/h, Q_d={Q_d:.2f}t/h, Q_max_t={Q_max_t:.2f}t/h, Q_current={Q_current:.2f}t/h, 总质量={total_mass_main:.2f}t")
                
                # 主斜井皮带（索引1）
                inclined_belt = system.belts[1]
                Q_C = system.input_C_flow_rate
                Q_max_t_inclined = system.calculate_belt_max_flow(1)
                Q_current_inclined = max(Q_C, Q_max_t_inclined)
                total_mass_inclined = sum(p.mass for p in inclined_belt.packets)
                print(f"Frame {frame}: 主斜井皮带 - 输入C={Q_C:.2f}t/h, Q_max_t={Q_max_t_inclined:.2f}t/h, Q_current={Q_current_inclined:.2f}t/h, 总质量={total_mass_inclined:.2f}t")
                
                # 101皮带（索引2）
                belt_101 = system.belts[2]
                Q_101_max = system.calculate_belt_max_flow(2)
                total_mass_101 = sum(p.mass for p in belt_101.packets)
                print(f"Frame {frame}: 101皮带 - Q_max_t={Q_101_max:.2f}t/h, 总质量={total_mass_101:.2f}t, 煤包数量={len(belt_101.packets)}")
                
                # 增加更详细的煤包信息
                if frame % 20 == 0:
                    print(f"Frame {frame}: 主运皮带煤包详情:")
                    for i, packet in enumerate(main_belt.packets[:5]):  # 只显示前5个煤包
                        print(f"  煤包{i}: 质量={packet.mass:.4f}t, 长度={packet.length:.2f}m, 位置={packet.position:.2f}m, 尾部={packet.tail_position:.2f}m")
                    if len(main_belt.packets) > 5:
                        print(f"  ... 共{len(main_belt.packets)}个煤包")
            
            # 更新皮带上的输入流量信息
            if input_flow_texts:
                flow_stats = {
                    'input_A_total': system.input_A_total_mass,
                    'input_A_flow_rate': system.input_A_flow_rate,
                    'input_B_total': system.input_B_total_mass,
                    'input_B_flow_rate': system.input_B_flow_rate,
                    'input_C_total': system.input_C_total_mass,
                    'input_C_flow_rate': system.input_C_flow_rate
                }
                input_flow_texts[0].set_text(f'输入点A累积: {flow_stats["input_A_total"]:.1f} t')
                input_flow_texts[1].set_text(f'输入点A流量: {flow_stats["input_A_flow_rate"]:.2f} t/h')
                input_flow_texts[2].set_text(f'输入点B累积: {flow_stats["input_B_total"]:.1f} t')
                input_flow_texts[3].set_text(f'输入点B流量: {flow_stats["input_B_flow_rate"]:.2f} t/h')
                # 如果有输入C的显示，更新它
                if len(input_flow_texts) > 4:
                    input_flow_texts[4].set_text(f'输入点C累积: {flow_stats["input_C_total"]:.1f} t')
                    input_flow_texts[5].set_text(f'输入点C流量: {flow_stats["input_C_flow_rate"]:.2f} t/h')
            
            return lines + [time_text] + belt_info_texts + input_flow_texts + title_texts
        except Exception as e:
            import traceback
            print(f"Update error at frame {frame}: {e}")
            print(traceback.format_exc())
            # 返回空列表，避免动画崩溃
            return []
    
    # 初始化测试：验证流量计算是否正确
    print("=== 初始化流量计算验证 ===")
    system = CoalFlowSystem()
    
    # 模拟添加一个煤包
    target_flow = 200.0  # t/h
    dt = 0.05  # 50ms
    mass = target_flow * (dt / 3600.0)  # 理论质量
    print(f"目标流量: {target_flow}t/h, dt: {dt}s, 理论煤包质量: {mass:.6f}t")
    
    # 添加煤包到主运皮带
    system.add_coal_input(0, mass, 0)
    system.update(dt)
    
    # 计算最大流量
    max_flow = system.calculate_belt_max_flow(0)
    print(f"实际计算最大流量: {max_flow:.2f}t/h")
    print("=========================")
    
    # 创建动画
    print("开始模拟煤流系统...")
    ani = FuncAnimation(fig, update, interval=50, blit=False)
    
    # 处理窗口关闭事件，确保程序能正确退出
    def handle_close(event):
        import sys
        print("关闭窗口，结束模拟...")
        plt.close()
        sys.exit(0)
    
    fig.canvas.mpl_connect('close_event', handle_close)
    plt.show()


def test_flow_calculation():
    """测试流量计算是否正确"""
    # 打开文件用于写入测试结果
    with open("test_results.txt", "w") as f:
        f.write("=== 流量计算测试开始 ===\n")
        f.write("测试函数被调用\n")
        system = CoalFlowSystem()
        f.write("煤流系统已创建\n")
        
        # 设置目标流量
        target_flow_A = 200.0  # t/h
        target_flow_B = 200.0  # t/h
        target_flow_C = 200.0  # t/h
        
        dt = 0.05  # 50ms
        actual_dt = 5 * dt  # 由于每帧运行5次系统更新
        
        # 禁用爆发模式
        burst_prob_A = 0.0
        burst_prob_B = 0.0
        burst_prob_C = 0.0
        
        # 模拟添加煤包并更新系统
        for i in range(100):
            # 计算煤包质量
            mass_A = sample_mass(target_flow_A, burst_prob_A, dt=actual_dt)
            mass_B = sample_mass(target_flow_B, burst_prob_B, dt=actual_dt)
            mass_C = sample_mass(target_flow_C, burst_prob_C, dt=actual_dt)
            
            # 添加煤包
            system.add_coal_input(belt_index=0, mass=mass_A, position=0, input_source='A')
            system.add_coal_input(belt_index=0, mass=mass_B, position=2500.0, input_source='B')
            system.add_coal_input(belt_index=1, mass=mass_C, position=0, input_source='C')
            
            # 更新系统
            for _ in range(5):
                system.update(dt)
            system.get_flow_statistics(actual_dt)
            
            # 每10次迭代写入一次结果
            if i % 10 == 0:
                # 计算主运皮带的最大流量
                max_flow_main = system.calculate_belt_max_flow(0)
                total_mass_main = sum(p.mass for p in system.belts[0].packets)
                
                # 检查A和B点的煤包是否重叠
                a_packets = [p for p in system.belts[0].packets if 0 <= p.position <= 1000]
                b_packets = [p for p in system.belts[0].packets if 2000 <= p.position <= 3500]
                overlapping = False
                for a_packet in a_packets:
                    for b_packet in b_packets:
                        if (a_packet.tail_position <= b_packet.position and 
                            a_packet.position >= b_packet.tail_position):
                            overlapping = True
                            break
                    if overlapping:
                        break
                
                f.write(f"迭代 {i}: 主运皮带最大流量 = {max_flow_main:.2f} t/h, 总质量 = {total_mass_main:.2f} t, 煤包重叠 = {overlapping}\n")
        
        f.write("=== 测试完成 ===\n")
    
    # 测试完成后读取并打印结果
    with open("test_results.txt", "r") as f:
        results = f.read()
        print(results)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        # 非可视化测试模式
        print("运行非可视化测试模式...")
        test_flow_calculation()
    else:
        try:
            print("启动可视化程序...")
            visualize_system()
        except Exception as e:
            print(f"程序运行出错: {e}")
            import traceback
            traceback.print_exc()
            print("\n提示: 如果在无头环境中运行，请使用 '--test' 参数启动非可视化测试模式")