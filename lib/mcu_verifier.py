"""从 .bin 文件解析 MCU CONFIG_DATA，提供字段查询接口。

复用 dump_mcu_config.py 中的 ctypes 结构体定义（--from-bin 模式），
不依赖 spidev，可在 Windows 本机运行。

典型用法：
    verifier = McuVerifier("C:/tmp/mcu_test.bin")
    assert verifier.get_prog_cnt(slot=0) == 3
    assert abs(verifier.get_ref_torque(slot=0, step=0) - 0.55) < 0.01
"""

import ctypes
import os
import sys

# 将项目根目录加入 sys.path，以便 import dump_mcu_config
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dump_mcu_config import (  # noqa: E402
    CONFIG_DATA,
    SCREW_MAX,
    SCREW_PROG_MAX,
    TORQUE_UNIT_MAP,
    bytes_to_str,
)


class McuVerifier:
    """解析从树莓派下载的 MCU CONFIG_DATA .bin 文件，提供螺丝参数查询接口。

    MCU 物理槽位编号为 0-15（对应 CONFIG_DATA.ctrl_cfg.screw_cfg.screw[0-15]），
    与数据库逻辑 ID（0-127）的映射由后端 SlotTable 管理，需要调用方自行解析
    slot_status_get 响应或查询 DB 获取映射关系。
    """

    def __init__(self, bin_path: str):
        """从 .bin 文件加载并解析 MCU 配置。

        Args:
            bin_path: 本地 .bin 文件路径（由 remote.download_mcu_bin 下载）

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件太小，可能不是完整的 CONFIG_DATA dump
        """
        with open(bin_path, "rb") as f:
            raw = f.read()

        required = ctypes.sizeof(CONFIG_DATA)
        if len(raw) < required:
            # 不足时用零填充，避免解析出错（部分 dump 可能被截断）
            raw = raw + b"\x00" * (required - len(raw))

        self._cfg = CONFIG_DATA.from_buffer_copy(raw[:required])
        self._bin_path = bin_path

    # ── 基础访问 ───────────────────────────────────────────────────────────────

    def get_screw(self, slot: int):
        """返回 MCU 物理槽位（0-15）对应的 SCREW 结构体。

        Args:
            slot: 物理槽位号，0-15

        Returns:
            SCREW ctypes 结构体实例

        Raises:
            AssertionError: slot 超出 0-15 范围
        """
        assert 0 <= slot < SCREW_MAX, f"MCU slot must be 0-{SCREW_MAX - 1}, got {slot}"
        return self._cfg.ctrl_cfg.screw_cfg.screw[slot]

    def get_prog(self, slot: int, step: int):
        """返回指定物理槽位的第 step 步 SCREW_PROG 结构体。

        Args:
            slot: 物理槽位号，0-15
            step: 步骤编号，0-7

        Returns:
            SCREW_PROG ctypes 结构体实例
        """
        assert 0 <= step < SCREW_PROG_MAX, (
            f"step must be 0-{SCREW_PROG_MAX - 1}, got {step}"
        )
        return self.get_screw(slot).prog[step]

    # ── 螺丝名称 ───────────────────────────────────────────────────────────────

    def get_screw_name(self, slot: int) -> str:
        """返回物理槽位的螺丝名称（UTF-8 解码，去除尾部空字节）。"""
        raw_name = self.get_screw(slot).screw_name
        return bytes_to_str(raw_name)

    # ── 详情参数 ───────────────────────────────────────────────────────────────

    def get_prog_cnt(self, slot: int) -> int:
        """返回物理槽位的步骤数（prog_cnt）。"""
        return int(self.get_screw(slot).detail_prama.prog_cnt)

    def get_screw_cnt(self, slot: int) -> int:
        """返回物理槽位的螺丝数量（screw_cnt）。"""
        return int(self.get_screw(slot).detail_prama.screw_cnt)

    def get_torque_unit(self, slot: int) -> int:
        """返回物理槽位的扭矩单位编号（0=mN.m, 1=kgf.cm, 2=lbf.in, 3=N.m）。"""
        return int(self.get_screw(slot).detail_prama.torque_unit)

    def get_torque_unit_str(self, slot: int) -> str:
        """返回物理槽位的扭矩单位字符串（如 'kgf.cm'）。"""
        return TORQUE_UNIT_MAP.get(self.get_torque_unit(slot), "unknown")

    def get_torque_target(self, slot: int) -> float:
        """返回物理槽位的目标扭矩（torque_target）。"""
        return float(self.get_screw(slot).detail_prama.torque_target)

    def get_torque_min(self, slot: int) -> float:
        """返回物理槽位的最小扭矩（torque_min）。"""
        return float(self.get_screw(slot).detail_prama.torque_min)

    def get_torque_max(self, slot: int) -> float:
        """返回物理槽位的最大扭矩（torque_max）。"""
        return float(self.get_screw(slot).detail_prama.torque_max)

    # ── 步骤参数 ───────────────────────────────────────────────────────────────

    def get_ref_torque(self, slot: int, step: int) -> float:
        """返回指定物理槽位和步骤的参考扭矩（ref_torque）。"""
        return float(self.get_prog(slot, step).ref_torque)

    def get_ref_vel(self, slot: int, step: int) -> float:
        """返回指定物理槽位和步骤的参考速度（ref_vel）。"""
        return float(self.get_prog(slot, step).ref_vel)

    def get_ref_degree(self, slot: int, step: int) -> float:
        """返回指定物理槽位和步骤的参考角度（ref_degree）。"""
        return float(self.get_prog(slot, step).ref_degree)

    def get_ok_if(self, slot: int, step: int) -> list:
        """返回步骤的 ok_if 条件列表（4个元素）。"""
        ok_if_arr = self.get_prog(slot, step).ok_if
        return [int(ok_if_arr[i]) for i in range(4)]

    # ── 便捷摘要 ───────────────────────────────────────────────────────────────

    def slot_summary(self, slot: int) -> dict:
        """返回物理槽位的主要参数摘要（便于调试输出）。"""
        return {
            "slot": slot,
            "screw_name": self.get_screw_name(slot),
            "prog_cnt": self.get_prog_cnt(slot),
            "screw_cnt": self.get_screw_cnt(slot),
            "torque_unit": self.get_torque_unit_str(slot),
            "torque_target": self.get_torque_target(slot),
            "torque_min": self.get_torque_min(slot),
            "torque_max": self.get_torque_max(slot),
        }

    def all_active_slots(self, max_slot: int = SCREW_MAX) -> list:
        """返回所有名称不为空的物理槽位列表（简单启发式判断是否已写入数据）。"""
        return [
            s for s in range(max_slot)
            if self.get_screw_name(s).strip()
        ]

    def __repr__(self) -> str:
        return f"McuVerifier(bin_path={self._bin_path!r})"
