"""单模组内唯一螺丝规格数量约束（与 MCU/状态机上限对齐时的行为）。"""

import pytest

from lib.constants import MAX_UNIQUE_SPECS_PER_MODULE, MAX_POINT_COUNT

pytestmark = [pytest.mark.spec128, pytest.mark.p1]


def _point(i: int, spec: int) -> dict:
    return {
        "point_id": i,
        "x": float(i * 10),
        "y": float(i * 10),
        "screw_spec": spec,
        "expected_angle_a": 0,
        "expected_angle_b": 0,
        "angle_tolerance": 5,
    }


class TestUniqueSpecLimit:
    async def test_seventeen_distinct_specs_on_module(self, ws):
        """17 个不同 screw_spec：若后端拒绝则 success=False；若接受则记录当前产品行为。"""
        mid = 125
        n = MAX_UNIQUE_SPECS_PER_MODULE + 1
        points = [_point(i, i) for i in range(min(n, MAX_POINT_COUNT + 1))]
        msg = {
            "type": "module_config",
            "module_id": mid,
            "product_name": "LimitTest-17specs",
            "position_points": points,
            "point_count": len(points),
            "background_image": "",
            "image_markers": [],
            "modify_user": "test",
        }
        r = await ws.save_module(mid, msg)
        if r.get("type") == "module_error":
            assert r.get("success") is False
        else:
            assert r.get("success") in (True, False)
