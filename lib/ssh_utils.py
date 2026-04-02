"""SSH 远程控制树莓派后端服务"""
import asyncio
import json
import time
from typing import Optional
import paramiko


class RemoteBackend:
    """通过 SSH 控制树莓派上的后端服务"""
    
    SERVICE_NAME = "asa-backend"
    DB_PATH = "/home/pi/data/SAS.db"
    LOG_PATH = "/home/pi/logs/asa_backend_sm.log"
    BACKUP_PATH = "/tmp/SAS_test_backup.db"
    DUMP_MCU_SCRIPT = "/home/pi/dump_mcu_config.py"
    
    def __init__(self, host: str, user: str = "pi", password: Optional[str] = None,
                 key_filename: Optional[str] = None, port: int = 22):
        self._host = host
        self._user = user
        self._password = password
        self._key_filename = key_filename
        self._port = port
        self._client: Optional[paramiko.SSHClient] = None
    
    def _ensure_connected(self):
        if self._client is None or not self._client.get_transport() or not self._client.get_transport().is_active():
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs = {
                "hostname": self._host,
                "port": self._port,
                "username": self._user,
            }
            if self._password:
                connect_kwargs["password"] = self._password
            if self._key_filename:
                connect_kwargs["key_filename"] = self._key_filename
            self._client.connect(**connect_kwargs)
    
    def _exec(self, command: str, timeout: float = 30) -> tuple[str, str, int]:
        """执行远程命令，返回 (stdout, stderr, exit_code)"""
        self._ensure_connected()
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return stdout.read().decode(), stderr.read().decode(), exit_code
    
    async def restart_backend(self):
        """重启后端服务（systemctl restart）"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._exec(f"sudo systemctl restart {self.SERVICE_NAME}"))
    
    async def stop_backend(self):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._exec(f"sudo systemctl stop {self.SERVICE_NAME}"))
    
    async def start_backend(self):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._exec(f"sudo systemctl start {self.SERVICE_NAME}"))
    
    async def kill_backend(self):
        """kill -9 模拟断电崩溃"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._exec(
            f"sudo systemctl kill -s KILL {self.SERVICE_NAME}"
        ))
    
    async def get_backend_pid(self) -> Optional[int]:
        loop = asyncio.get_event_loop()
        stdout, _, code = await loop.run_in_executor(None, lambda: self._exec(
            f"systemctl show -p MainPID --value {self.SERVICE_NAME}"
        ))
        pid = stdout.strip()
        if pid and pid != "0":
            return int(pid)
        return None
    
    async def is_backend_running(self) -> bool:
        loop = asyncio.get_event_loop()
        _, _, code = await loop.run_in_executor(None, lambda: self._exec(
            f"systemctl is-active {self.SERVICE_NAME}"
        ))
        return code == 0
    
    async def wait_until_ready(self, ws_url: str, timeout: float = 30):
        """等待后端启动并可接受 WS 连接"""
        import websockets
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                async with websockets.connect(ws_url, open_timeout=2) as ws:
                    await ws.close()
                    return
            except Exception:
                await asyncio.sleep(1)
        raise TimeoutError(f"Backend not ready at {ws_url} after {timeout}s")
    
    async def get_backend_log(self, lines: int = 50) -> str:
        loop = asyncio.get_event_loop()
        stdout, _, _ = await loop.run_in_executor(None, lambda: self._exec(
            f"tail -n {lines} {self.LOG_PATH}"
        ))
        return stdout
    
    async def backup_database(self):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._exec(
            f"cp {self.DB_PATH} {self.BACKUP_PATH}"
        ))
    
    async def restore_database(self):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._exec(
            f"cp {self.BACKUP_PATH} {self.DB_PATH}"
        ))
    
    async def replace_database(self, local_db_path: str):
        """上传本地 DB 文件替换远程 DB（用于迁移测试）"""
        loop = asyncio.get_event_loop()
        def _upload():
            self._ensure_connected()
            sftp = self._client.open_sftp()
            sftp.put(local_db_path, self.DB_PATH)
            sftp.close()
        await loop.run_in_executor(None, _upload)
    
    async def query_db(self, sql: str) -> list:
        """在树莓派上执行 SQLite 查询，返回行列表（每行为 dict）。

        使用 python3 内置 sqlite3 模块（无需系统安装 sqlite3 命令行工具）。

        示例:
            rows = await remote.query_db(
                "SELECT screw_name, prog_cnt, is_active FROM Mode1_Screw_Param WHERE id=115"
            )
            assert rows[0]["is_active"] == 1
        """
        # 使用 python3 内置模块，避免依赖 sqlite3 命令行工具
        py_script = (
            "import sqlite3, json, sys; "
            f"db = sqlite3.connect('{self.DB_PATH}'); "
            "db.row_factory = sqlite3.Row; "
            "cur = db.execute(sys.argv[1]); "
            "rows = [dict(r) for r in cur.fetchall()]; "
            "print(json.dumps(rows))"
        )
        cmd = f"python3 -c {json.dumps(py_script)} {json.dumps(sql)}"
        loop = asyncio.get_event_loop()
        stdout, stderr, code = await loop.run_in_executor(
            None, lambda: self._exec(cmd)
        )
        if code != 0:
            raise RuntimeError(f"query_db error (code={code}): {stderr.strip()}")
        return json.loads(stdout) if stdout.strip() else []

    async def dump_mcu_to_bin(self, remote_bin_path: str = "/tmp/mcu_test.bin") -> str:
        """在树莓派上运行 dump_mcu_config.py --save-bin，返回生成的 .bin 文件路径。
        
        需要树莓派上已有 dump_mcu_config.py 脚本（DUMP_MCU_SCRIPT），
        且 pi 用户有 sudo 权限（SPI 读取需要 root）。
        
        Returns:
            远程 .bin 文件的绝对路径
        """
        loop = asyncio.get_event_loop()
        stdout, stderr, code = await loop.run_in_executor(
            None,
            lambda: self._exec(
                f"sudo python3 {self.DUMP_MCU_SCRIPT} --save-bin {remote_bin_path} -o /tmp/mcu_dump_test.txt",
                timeout=30,
            )
        )
        if code != 0:
            raise RuntimeError(f"dump_mcu failed (code={code}): {stderr.strip()}")
        # 尝试从 stdout 解析实际保存路径（脚本输出 "原始二进制已保存: <path>"）
        for line in stdout.splitlines():
            if "原始二进制已保存" in line:
                return line.split(":")[-1].strip()
        return remote_bin_path

    async def download_mcu_bin(self, remote_path: str, local_path: str) -> None:
        """通过 SFTP 将树莓派上的 .bin 文件下载到本地。
        
        Args:
            remote_path: 树莓派上的文件路径（如 /tmp/mcu_test.bin）
            local_path:  本地保存路径（如 C:/tmp/mcu_test.bin）
        """
        loop = asyncio.get_event_loop()

        def _download():
            self._ensure_connected()
            sftp = self._client.open_sftp()
            try:
                sftp.get(remote_path, local_path)
            finally:
                sftp.close()

        await loop.run_in_executor(None, _download)

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
