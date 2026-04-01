"""SSH 远程控制树莓派后端服务"""
import asyncio
import time
from typing import Optional
import paramiko


class RemoteBackend:
    """通过 SSH 控制树莓派上的后端服务"""
    
    SERVICE_NAME = "asa-backend"
    DB_PATH = "/home/pi/backend/releases/current/data/SAS.db"
    LOG_PATH = "/home/pi/backend/releases/current/logs/asa_backend_sm.log"
    BACKUP_PATH = "/tmp/SAS_test_backup.db"
    
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
    
    def close(self):
        if self._client:
            self._client.close()
            self._client = None
