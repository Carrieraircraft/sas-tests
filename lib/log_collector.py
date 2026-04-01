"""测试失败时自动抓取后端日志并附加到报告"""
from typing import Optional


class LogCollector:
    """测试失败时自动抓取后端日志"""
    
    def __init__(self, remote):
        self._remote = remote
    
    async def capture(self, lines: int = 50) -> str:
        """抓取后端日志最后 N 行"""
        try:
            return await self._remote.get_backend_log(lines=lines)
        except Exception as e:
            return f"[LogCollector] Failed to capture log: {e}"
    
    def format_for_report(self, log_content: str) -> str:
        """格式化日志内容用于报告展示"""
        separator = "=" * 60
        return f"\n{separator}\nBACKEND LOG (last 50 lines)\n{separator}\n{log_content}\n{separator}"
