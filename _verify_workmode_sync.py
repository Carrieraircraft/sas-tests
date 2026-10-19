"""验证工作模式切换后，状态机推送的 work_mode 与数据库保持一致。

复现的缺陷：拧紧配置里把螺丝模式切成模组模式，主页仍显示螺丝模式，重启才生效。
根因是 refreshStateContextConfig 读库失败时会把 work_mode 静默写回 "screw"，
而除了重启没有任何路径会再读库。

判定条件（每一轮都要满足）：
  1. 后端 system_params_batch_update_response 返回 success=true（前端据此提示保存结果）
  2. data:request:system_params 返回的 WorkMode 等于刚写入的值（库里确实改了）
  3. hardware_status_update.job_statistics.work_mode 等于刚写入的值（状态机跟上了）
"""

import asyncio
import json
import sys

import websockets

WS_URL = "ws://192.168.0.168:80"

# 后端防抖 300ms 后才刷新 StateContext，留足余量
SETTLE_SECONDS = 2.0
RECV_TIMEOUT = 10.0


async def _recv_until(ws, predicate, timeout=RECV_TIMEOUT):
    """读消息直到 predicate 返回非 None，返回该值；超时抛 TimeoutError。"""

    async def _loop():
        while True:
            raw = await ws.recv()
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            result = predicate(msg)
            if result is not None:
                return result

    return await asyncio.wait_for(_loop(), timeout)


async def check_mode(ws, mode: str) -> bool:
    ok = True

    await ws.send(json.dumps({
        "type": "system_params_batch_update",
        "params": [{"param_name": "WorkMode", "param_value": mode}],
        "modify_user": "verify_script",
    }))

    ack = await _recv_until(
        ws,
        lambda m: m if m.get("type") == "system_params_batch_update_response" else None,
    )
    if ack.get("success"):
        print(f"  [1/3] 保存确认 success=true")
    else:
        ok = False
        print(f"  [1/3] 保存确认失败: {ack}")

    await asyncio.sleep(SETTLE_SECONDS)

    await ws.send("data:request:system_params")
    params = await _recv_until(
        ws,
        lambda m: m.get("data") or {}
        if m.get("type") == "data_response" and m.get("data_type") == "system_params"
        else None,
    )
    db_mode = params.get("WorkMode")
    if db_mode == mode:
        print(f"  [2/3] 数据库 WorkMode = {db_mode}")
    else:
        ok = False
        print(f"  [2/3] 数据库 WorkMode = {db_mode}，期望 {mode}")

    pushed = await _recv_until(
        ws,
        lambda m: ((m.get("data") or {}).get("job_statistics") or {}).get("work_mode")
        if m.get("type") == "hardware_status_update"
        else None,
    )
    if pushed == mode:
        print(f"  [3/3] 状态机推送 work_mode = {pushed}")
    else:
        ok = False
        print(f"  [3/3] 状态机推送 work_mode = {pushed}，期望 {mode}  <-- 主页会显示错误模式")

    return ok


async def main() -> None:
    # 反复来回切，制造与写库线程的并发，暴露偶发的锁冲突/竞态
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    failures = 0

    async with websockets.connect(WS_URL, max_size=None) as ws:
        # 除 login/heartbeat 外后端一律要求已登录，否则参数写入会被拒
        await ws.send(json.dumps({
            "type": "login",
            "data": {"username": "admin", "password": "123"},
        }))
        login = await _recv_until(
            ws, lambda m: m if m.get("type") == "login_response" else None
        )
        if not login.get("success"):
            print(f"登录失败: {login.get('error')}")
            sys.exit(1)
        print("已登录\n")

        for i in range(1, rounds + 1):
            for mode in ("module", "screw"):
                print(f"[第 {i} 轮] 切换到 {mode}")
                if not await check_mode(ws, mode):
                    failures += 1

    print()
    if failures:
        print(f"失败 {failures} 次")
        sys.exit(1)
    print(f"全部通过（{rounds} 轮 x 2 次切换）")


if __name__ == "__main__":
    asyncio.run(main())
