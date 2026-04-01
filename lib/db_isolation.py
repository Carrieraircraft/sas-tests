"""数据库快照与恢复，实现测试环境隔离"""


class DatabaseIsolation:
    """数据库快照与恢复
    
    在测试套件开始前备份 SAS.db，结束后恢复，防止测试间数据污染。
    """
    
    def __init__(self, remote):
        self._remote = remote
        self._snapshot_taken = False
    
    async def snapshot(self):
        """备份当前数据库"""
        await self._remote.backup_database()
        self._snapshot_taken = True
    
    async def restore(self):
        """恢复数据库到快照状态（需要重启后端）"""
        if not self._snapshot_taken:
            return
        await self._remote.stop_backend()
        await self._remote.restore_database()
        await self._remote.start_backend()
    
    async def use_clean_db(self, ws_url: str):
        """删除数据库并重启后端（后端启动时自动初始化 128 条记录）"""
        from .ssh_utils import RemoteBackend
        await self._remote.stop_backend()
        loop = __import__('asyncio').get_event_loop()
        await loop.run_in_executor(None, lambda: self._remote._exec(
            f"rm -f {RemoteBackend.DB_PATH}"
        ))
        await self._remote.start_backend()
        await self._remote.wait_until_ready(ws_url)
