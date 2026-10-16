#!/usr/bin/env python3
"""统计 MCU 回传曲线点数（每颗覆盖率/包间隔/每包点数）。

用法:
  python monitor_curve_samples.py [N]          # 经 SSH 读最近 N 条 Job_Data.Plot_Data（默认 5）
  python monitor_curve_samples.py --ws [秒]     # 连 WS 统计增量帧到达频率与 sample_index 连续性
环境变量: SAS_HOST(默认 192.168.0.168) SAS_USER(pi) SAS_KEY(~/.ssh/id_ed25519)
"""
import collections
import json
import os
import subprocess
import sys

HOST = os.environ.get("SAS_HOST", "192.168.0.168")
USER = os.environ.get("SAS_USER", "pi")
KEY = os.environ.get("SAS_KEY", os.path.expanduser("~/.ssh/id_ed25519"))
PERIOD_MS = 1.018


def analyze(job_id, plot):
    d = json.loads(plot)
    t = d.get("time_data") or []
    if len(t) < 2:
        print(job_id, "无曲线")
        return
    runs, run, gaps = [], 1, []
    for k in range(1, len(t)):
        dt = (t[k] - t[k - 1]) * 1000
        if dt < 3:
            run += 1
        else:
            runs.append(run)
            run = 1
            gaps.append(dt)
    runs.append(run)
    span = t[-1] - t[0]
    cover = 100 * len(t) / (span * 1000 / PERIOD_MS) if span > 0 else 0
    print(f"{job_id}: 点数={len(t)} 时长={span:.2f}s 点率={len(t)/span:.0f}/s 包数={len(runs)} "
          f"每包点数分布={sorted(collections.Counter(runs).items())} "
          f"包间隔均值={sum(gaps)/max(len(gaps),1):.1f}ms 最大={max(gaps, default=0):.1f}ms 覆盖率={cover:.0f}%")


def run_db(n):
    sql = f"select ID||'|'||Plot_Data from Job_Data order by ID desc limit {n}"
    cmd = ["ssh", "-i", KEY, "-o", "BatchMode=yes", f"{USER}@{HOST}",
           f"sqlite3 -readonly /home/pi/backend/data/SAS.db \"{sql}\""]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if "|" in line:
            i, p = line.split("|", 1)
            analyze(i, p)


def run_ws(seconds):
    import asyncio
    import struct
    import time
    import websockets  # pip install websockets

    async def main():
        url = f"ws://{HOST}/ws"
        frames, pts, last_idx, jumps, gaps = 0, 0, None, 0, []
        t_last = None
        async with websockets.connect(url, max_size=None) as ws:
            end = time.time() + seconds
            while time.time() < end:
                try:
                    msg = await asyncio.wait_for(ws.recv(), 1.0)
                except asyncio.TimeoutError:
                    continue
                if not isinstance(msg, bytes) or len(msg) < 40 or msg[:4] != b"DCU1":
                    continue
                flags = struct.unpack_from("<H", msg, 6)[0]
                n = struct.unpack_from("<I", msg, 20)[0]
                frames += 1
                pts += n
                now = time.time()
                if t_last:
                    gaps.append((now - t_last) * 1000)
                t_last = now
                if flags & 4:
                    off = 40 + n * 8 + (n * 4 if flags & 1 else 0)
                    idx = struct.unpack_from(f"<{n}I", msg, off)
                    if last_idx is not None and idx[0] <= last_idx:
                        jumps += 1
                    last_idx = idx[-1]
        print(f"增量帧={frames} 点数={pts} 帧间隔均值={sum(gaps)/max(len(gaps),1):.0f}ms "
              f"最大={max(gaps, default=0):.0f}ms sample_index 倒退={jumps}")

    asyncio.run(main())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--ws":
        run_ws(float(sys.argv[2]) if len(sys.argv) > 2 else 30)
    else:
        run_db(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
