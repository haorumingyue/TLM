"""最小级联测试：两条皮带直接对接，验证前60m是否震荡"""
import math

def advect(cells, speed, dx, dt):
    if speed <= 1e-6:
        return cells[:], 0.0
    cfl = speed * dt / dx
    substeps = max(1, int(math.ceil(cfl / 0.95)))
    local_cfl = cfl / substeps
    updated = list(cells)
    total_out = 0.0
    for _ in range(substeps):
        total_out += local_cfl * updated[-1]
        nxt = [0.0] * len(updated)
        nxt[0] = updated[0] * (1.0 - local_cfl)
        for j in range(1, len(updated)):
            nxt[j] = updated[j] * (1.0 - local_cfl) + updated[j-1] * local_cfl
        updated = nxt
    return updated, total_out

# 一条短皮带 200m，max_density=0.111
N = 200
dx = 1.0
dt = 1.0
speed = 4.5
max_dens = 0.111
cells = [0.0] * N

# 模拟上游每步注入 0.01t 到首格
inflow_per_step = 0.01

print("step | cell[0]  | cell[1]  | cell[2]  | cell[10] | cell[50] | cell[99] | outflow")
for step in range(1, 1001):
    # 注入首格
    cells[0] += inflow_per_step
    # 传导
    adv, out = advect(cells, speed, dx, dt)
    cells = adv
    if step % 100 == 0:
        print(f"{step:4d} | {cells[0]:8.5f} | {cells[1]:8.5f} | {cells[2]:8.5f} | {cells[10]:8.5f} | {cells[50]:8.5f} | {cells[99]:8.5f} | {out:.6f}")
