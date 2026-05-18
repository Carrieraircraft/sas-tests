"""Quick script to inspect torque constraint values from the backend."""
import asyncio
import json
import websockets

async def main():
    async with websockets.connect("ws://192.168.0.168:80") as ws:
        for mt_id in [1, 2, 3, 14, 16]:
            await ws.send(json.dumps({"type": "machine_type_constraints_query", "machineTypeId": mt_id}))
            while True:
                raw = await ws.recv()
                try:
                    resp = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if resp.get("type") == "echo":
                    continue
                break
            constraints = resp.get("constraints", [])
            for c in constraints:
                pn = c.get("paramName")
                if "torque" in pn.lower():
                    print(f"MT={mt_id}  param={pn}  torqueUnit={c.get('torqueUnit')}  min={c.get('minValue')}  max={c.get('maxValue')}")

asyncio.run(main())
