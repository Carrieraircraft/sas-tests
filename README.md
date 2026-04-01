# SAS 自动化测试

Python 3 + pytest + websockets。默认后端地址见 `lib/constants.py` 中的 `DEFAULT_WS_URL`。

## 安装与运行

在 Windows 上若直接执行 `pytest` 提示找不到命令，请始终使用 **`python -m pytest`**（不依赖 `Scripts` 是否加入 PATH）。

```bash
pip install -r requirements.txt
cd tests
python -m pytest smoke/ -v
python -m pytest spec128/ smoke/ -v -m "not persistence and not destructive"
```

- 树莓派 SSH（持久化 / 断电 / 日志抓取）：`python -m pytest --ssh-host=192.168.x.x --ssh-user=pi ...`
- 首航迁移占位：设置 `SAS_LEGACY_DB_PATH` 后启用 `test_migration`

## 目录

- `smoke/`：部署后冒烟
- `spec128/`：128 组螺丝与统一模组（P0–P3 markers）
- `lib/`：WS 客户端、SSH、数据工厂等公共库
