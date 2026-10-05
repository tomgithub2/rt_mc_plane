"""建筑导入（无需机器人进服）后端核心。

模块划分：
  · :mod:`nbt`        —— 极简 NBT 读写（含 SNBT、压缩探测、解压炸弹防护）
  · :mod:`formats`    —— .schem / .schematic / .nbt / .litematic / zip 解析
  · :mod:`mapping`    —— 方块状态注册表与版本映射（reports / 内置回退表）
  · :mod:`anvil`      —— region 文件（r.X.Z.mca）读写、区块 NBT、位打包
  · :mod:`plan`       —— 预检报告（规格 §5）
  · :mod:`tasks`      —— 异步导入任务、进度、取消、备份/回滚
  · :mod:`engines`    —— 引擎 A（插件 + RCON）/ 引擎 B（离线 Anvil）/ 原版 /place
"""

__all__ = ['nbt', 'formats', 'mapping', 'anvil', 'plan', 'tasks', 'engines']
