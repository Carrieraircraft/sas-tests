"""复现 2026-07-28 缺陷：IDLE 状态下切工作模式后条码被拒。

在 AutoBind + ScanPowerOn 下，配置刷新事件曾无条件把 IDLE 子状态设为
JOB_SELECTED，导致状态机跳过 WAIT_BARCODE_SCAN 直接上电到 ST_READY_STANDBY，
之后所有扫码都被 BarcodeIngest 判为"工序进行中"拒收。

本脚本只负责在系统停在 IDLE 时触发一次工作模式切换，判定看 journal。
"""

import asyncio
import json
import sys

import websockets

WS_URL = "ws://192.168.0.168:80"


async def switch_work_mode(mode: str) -> None:
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({
            "type": "system_params_batch_update",
            "params": [{"param_name": "WorkMode", "param_value": mode}],
        }))
        # 后端异步落库 + 防抖后才触发配置变更回调，留足时间让日志落地
        await asyncio.sleep(3)
    print(f"WorkMode -> {mode}")


async def main() -> None:
    for mode in sys.argv[1:] or ["screw", "module"]:
        await switch_work_mode(mode)


if __name__ == "__main__":
    asyncio.run(main())
