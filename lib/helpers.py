"""数据工厂 + 断言辅助 + 快照工具"""
import random
import json
import time
import asyncio
from typing import Optional

from .constants import (
    MsgType,
    DEFAULT_WS_TIMEOUT,
    MAX_STEPS_PER_SPEC,
    MAX_POINT_COUNT,
    MAX_UNIQUE_SPECS_PER_MODULE,
)


class ScrewSpecFactory:
    """生成符合后端 screw_param_config 格式的测试数据"""

    @staticmethod
    def _base_detail_params(**overrides) -> dict:
        defaults = {
            "torque_unit": 1,
            "screw_cnt": 8,
            "prog_cnt": 2,
            "tighten_ng_soft_power_off": 0,
            "complete_soft_power_off": 0,
            "counter_inc_mode": 1,
            "repeat_gap_time": 0,
            "torque_compensation": 0.0,
            "end_torque_keep_time_ms": 25,
            "gyrometer_start_angle": 0,
            "gyrometer_stop_angle": 0,
            "prog_start_valid_step": 0,
            "loosen_gap_time": 0,
            "repeat_angle_max": 0,
            "confirm_cnt": 1,
            "vel_limit_torque_percent": 80,
            "torque_filter_time_ms": 10,
            "vel_check_enable": 1,
            "torque_check_enable": 1,
            "time_check_enable": 1,
            "degree_check_enable": 1,
            "socket_specification": 0,
            "torque_target": 0.325,
            "torque_max": 0.4,
            "torque_min": 0.25,
            "vel_target": 180,
            "vel_max": 300,
            "vel_min": 100,
            "degree_target": 180,
            "degree_max": 360,
            "degree_min": 90,
            "time_target": 3000,
            "time_max": 5000,
            "time_min": 1000,
        }
        defaults.update(overrides)
        return defaults

    @staticmethod
    def _base_step(step_index: int = 0, **overrides) -> dict:
        defaults = {
            "screw_step": step_index + 1,
            "ok_if_1": 2,
            "ok_if_2": 4,
            "ok_if_3": 0,
            "ok_if_4": 0,
            "ref_vel": 180,
            "ref_torque": 0.325,
            "ref_degree": 180,
            "ref_time": 3000,
            "from_vel": 0,
            "to_vel": 180,
            "ok_out": 0,
            "ok_out_status": 0,
            "ok_out_pulse_time": 500,
            "ng_out": 0,
            "ng_out_status": 0,
            "ng_out_pulse_time": 500,
            "start_in": 0,
            "start_in_status": 0,
            "run_dir_positive": 0,
            "es": 1,
        }
        defaults.update(overrides)
        return defaults

    @classmethod
    def default(cls, spec_id: int) -> dict:
        return {
            "type": MsgType.SCREW_PARAM_CONFIG,
            "mode": 1,
            "specification_id": spec_id,
            "specification_name": f"TestSpec-{spec_id}",
            "machine_type_id": 0,
            "detail_params": cls._base_detail_params(prog_cnt=1),
            "step_params": [cls._base_step(0)],
        }

    @classmethod
    def with_steps(cls, spec_id: int, step_count: int) -> dict:
        step_count = max(1, min(step_count, MAX_STEPS_PER_SPEC))
        return {
            "type": MsgType.SCREW_PARAM_CONFIG,
            "mode": 1,
            "specification_id": spec_id,
            "specification_name": f"TestSpec-{spec_id}-{step_count}s",
            "machine_type_id": 0,
            "detail_params": cls._base_detail_params(prog_cnt=step_count),
            "step_params": [cls._base_step(i) for i in range(step_count)],
        }

    @classmethod
    def complex_full(cls, spec_id: int) -> dict:
        return {
            "type": MsgType.SCREW_PARAM_CONFIG,
            "mode": 1,
            "specification_id": spec_id,
            "specification_name": f"FullSpec-{spec_id}",
            "machine_type_id": 0,
            "detail_params": cls._base_detail_params(
                screw_cnt=16,
                prog_cnt=MAX_STEPS_PER_SPEC,
                tighten_ng_soft_power_off=1,
                complete_soft_power_off=1,
                counter_inc_mode=2,
                repeat_gap_time=100,
                torque_compensation=0.05,
                end_torque_keep_time_ms=50,
                gyrometer_start_angle=10,
                gyrometer_stop_angle=45,
                prog_start_valid_step=1,
                loosen_gap_time=200,
                repeat_angle_max=720,
                confirm_cnt=3,
                vel_limit_torque_percent=90,
                torque_filter_time_ms=20,
                socket_specification=5,
                torque_target=2.0,
                torque_max=2.5,
                torque_min=1.7,
                vel_target=800,
                vel_max=1000,
                vel_min=650,
                degree_target=720,
                degree_max=820,
                degree_min=640,
                time_target=2000,
                time_max=2500,
                time_min=1600,
            ),
            "step_params": [
                cls._base_step(
                    i,
                    ok_if_1=2,
                    ok_if_2=4,
                    ok_if_3=8,
                    ok_if_4=16,
                    ref_vel=700 + i * 10,
                    ref_torque=1.8 + i * 0.02,
                    ref_degree=650 + i * 5,
                    ref_time=1700 + i * 20,
                    from_vel=50,
                    to_vel=250 + i * 10,
                    ok_out=1,
                    ok_out_status=1,
                    ng_out=1,
                    ng_out_status=1,
                    run_dir_positive=i % 2,
                    es=1,
                )
                for i in range(MAX_STEPS_PER_SPEC)
            ],
        }

    @classmethod
    def random(cls, spec_id: int) -> dict:
        step_count = random.randint(1, MAX_STEPS_PER_SPEC)
        # 生成合法的安全配置：min <= target <= max
        torque_min = round(random.uniform(0.1, 1.0), 2)
        torque_max = round(torque_min + random.uniform(0.2, 2.0), 2)
        torque_target = round(random.uniform(torque_min, torque_max), 2)
        vel_min = random.randint(50, 200)
        vel_max = vel_min + random.randint(100, 500)
        vel_target = random.randint(vel_min, vel_max)
        degree_min = random.randint(30, 200)
        degree_max = degree_min + random.randint(100, 500)
        degree_target = random.randint(degree_min, degree_max)
        time_min = random.randint(500, 2000)
        time_max = time_min + random.randint(500, 3000)
        time_target = random.randint(time_min, time_max)
        return {
            "type": MsgType.SCREW_PARAM_CONFIG,
            "mode": 1,
            "specification_id": spec_id,
            "specification_name": f"RandSpec-{spec_id}-{random.randint(1000,9999)}",
            "machine_type_id": 0,
            "detail_params": cls._base_detail_params(
                screw_cnt=random.randint(1, 16),
                prog_cnt=step_count,
                tighten_ng_soft_power_off=random.randint(0, 1),
                complete_soft_power_off=random.randint(0, 1),
                counter_inc_mode=random.randint(0, 2),
                repeat_gap_time=random.randint(0, 500),
                torque_compensation=round(random.uniform(0, 0.1), 3),
                end_torque_keep_time_ms=random.randint(10, 100),
                gyrometer_start_angle=random.randint(0, 30),
                gyrometer_stop_angle=random.randint(0, 90),
                confirm_cnt=random.randint(1, 5),
                vel_limit_torque_percent=random.randint(50, 100),
                torque_filter_time_ms=random.randint(5, 50),
                torque_target=torque_target,
                torque_max=torque_max,
                torque_min=torque_min,
                vel_target=vel_target,
                vel_max=vel_max,
                vel_min=vel_min,
                degree_target=degree_target,
                degree_max=degree_max,
                degree_min=degree_min,
                time_target=time_target,
                time_max=time_max,
                time_min=time_min,
            ),
            "step_params": [
                cls._base_step(
                    i,
                    ok_if_1=random.choice([0, 2, 4]),
                    ok_if_2=random.choice([0, 2, 4, 8]),
                    ok_if_3=random.choice([0, 4, 8, 16]),
                    ok_if_4=random.choice([0, 8, 16]),
                    ref_vel=random.randint(50, 500),
                    ref_torque=round(random.uniform(0.05, 3.0), 2),
                    ref_degree=random.randint(0, 720),
                    ref_time=random.randint(0, 5000),
                    from_vel=random.randint(0, 100),
                    to_vel=random.randint(100, 500),
                    ok_out=random.randint(0, 1),
                    ok_out_status=random.randint(0, 1),
                    ok_out_pulse_time=random.randint(100, 1000),
                    ng_out=random.randint(0, 1),
                    ng_out_status=random.randint(0, 1),
                    ng_out_pulse_time=random.randint(100, 1000),
                    start_in=random.randint(0, 1),
                    start_in_status=random.randint(0, 1),
                    run_dir_positive=random.randint(0, 1),
                    es=random.randint(0, 1),
                )
                for i in range(step_count)
            ],
        }


class ModuleFactory:
    """生成符合后端 module_config 格式的测试数据"""

    @staticmethod
    def _base_point(point_id: int, screw_spec: int = 0, **overrides) -> dict:
        defaults = {
            "point_id": point_id,
            "screw_spec": screw_spec,
            "x": 100 + point_id * 50,
            "y": 200 + point_id * 50,
            "expected_angle_a": 0,
            "expected_angle_b": 0,
            "angle_tolerance": 5,
        }
        defaults.update(overrides)
        return defaults

    @classmethod
    def manual(cls, module_id: int, screw_specs: list[int]) -> dict:
        points = [
            cls._base_point(i, spec)
            for i, spec in enumerate(screw_specs[:MAX_POINT_COUNT])
        ]
        return {
            "type": MsgType.MODULE_CONFIG,
            "module_id": module_id,
            "product_name": f"ManualModule-{module_id}",
            "position_points": points,
            "point_count": len(points),
            "background_image": "",
            "image_markers": "[]",
            "torque_arm_config": None,
            "modify_user": "test",
        }

    @classmethod
    def torque_arm(cls, module_id: int, points: int) -> dict:
        points = max(1, min(points, MAX_POINT_COUNT))
        position_points = [cls._base_point(i, screw_spec=0) for i in range(points)]
        return {
            "type": MsgType.MODULE_CONFIG,
            "module_id": module_id,
            "product_name": f"TorqueArmModule-{module_id}",
            "position_points": position_points,
            "point_count": len(position_points),
            "background_image": "",
            "image_markers": "[]",
            "torque_arm_config": {
                "arm_length": 250.0,
                "arm_offset": 0.0,
                "rotation_center_x": 400,
                "rotation_center_y": 300,
            },
            "modify_user": "test",
        }

    @classmethod
    def random(cls, module_id: int, max_specs: int = 8) -> dict:
        point_count = random.randint(1, MAX_POINT_COUNT)
        specs_pool = list(range(max_specs))
        position_points = [
            cls._base_point(
                i,
                screw_spec=random.choice(specs_pool),
                x=random.randint(0, 800),
                y=random.randint(0, 600),
                expected_angle_a=random.randint(0, 360),
                expected_angle_b=random.randint(0, 360),
                angle_tolerance=random.randint(1, 15),
            )
            for i in range(point_count)
        ]
        has_torque_arm = random.choice([True, False])
        torque_arm_config = None
        if has_torque_arm:
            torque_arm_config = {
                "arm_length": round(random.uniform(100, 500), 1),
                "arm_offset": round(random.uniform(-50, 50), 1),
                "rotation_center_x": random.randint(100, 700),
                "rotation_center_y": random.randint(100, 500),
            }
        return {
            "type": MsgType.MODULE_CONFIG,
            "module_id": module_id,
            "product_name": f"RandModule-{module_id}-{random.randint(1000,9999)}",
            "position_points": position_points,
            "point_count": len(position_points),
            "background_image": "",
            "image_markers": "[]",
            "torque_arm_config": torque_arm_config,
            "modify_user": "test",
        }


async def snapshot_spec_list(ws, timeout: float = DEFAULT_WS_TIMEOUT) -> list[dict]:
    """通过 WS 获取规格列表快照（与 get_spec_list 一致，字段为 data）。"""
    if hasattr(ws, "get_spec_list"):
        return await ws.get_spec_list()
    request = json.dumps({"type": MsgType.SPEC_OPTIONS_GET})
    await ws.send(request)
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    msg = json.loads(raw)
    if msg.get("type") != MsgType.SPEC_OPTIONS_RESPONSE:
        raise ValueError(
            f"Expected {MsgType.SPEC_OPTIONS_RESPONSE}, got {msg.get('type')}"
        )
    return msg.get("data", [])


def assert_snapshot_equal(before: list[dict], after: list[dict]):
    """对比两个快照，不一致则抛出 AssertionError"""
    if len(before) != len(after):
        raise AssertionError(
            f"Snapshot length mismatch: before={len(before)}, after={len(after)}"
        )
    for i, (b, a) in enumerate(zip(before, after)):
        if b != a:
            raise AssertionError(
                f"Snapshot differs at index {i}:\n  before={json.dumps(b, ensure_ascii=False)}\n  after ={json.dumps(a, ensure_ascii=False)}"
            )


def assert_response_time(elapsed_ms: float, threshold_ms: float):
    """性能断言：响应时间必须在阈值内"""
    if elapsed_ms > threshold_ms:
        raise AssertionError(
            f"Response too slow: {elapsed_ms:.1f}ms > {threshold_ms:.1f}ms threshold"
        )
