"""性能测量与基线对比工具"""
import time
import json
import os
from typing import Optional
from dataclasses import dataclass, field, asdict


@dataclass
class PerfRecord:
    name: str
    elapsed_ms: float
    threshold_ms: float
    passed: bool


class PerformanceTracker:
    """跟踪和记录性能数据"""

    def __init__(self):
        self._records: list[PerfRecord] = []

    def record(self, name: str, elapsed_ms: float, threshold_ms: float):
        passed = elapsed_ms <= threshold_ms
        self._records.append(PerfRecord(name, elapsed_ms, threshold_ms, passed))
        return passed

    def summary(self) -> dict:
        total = len(self._records)
        passed = sum(1 for r in self._records if r.passed)
        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "records": [asdict(r) for r in self._records],
        }

    def save_baseline(self, path: str):
        with open(path, "w") as f:
            json.dump(self.summary(), f, indent=2)

    def compare_with_baseline(self, path: str) -> list[str]:
        """与基线对比，返回退化项列表"""
        if not os.path.exists(path):
            return []
        with open(path) as f:
            baseline = json.load(f)

        degradations = []
        baseline_map = {
            r["name"]: r["elapsed_ms"] for r in baseline.get("records", [])
        }
        for rec in self._records:
            if rec.name in baseline_map:
                baseline_ms = baseline_map[rec.name]
                if rec.elapsed_ms > baseline_ms * 1.5:
                    degradations.append(
                        f"{rec.name}: {baseline_ms:.1f}ms -> {rec.elapsed_ms:.1f}ms "
                        f"(+{((rec.elapsed_ms / baseline_ms) - 1) * 100:.0f}%)"
                    )
        return degradations
