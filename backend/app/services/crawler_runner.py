"""爬虫脚本运行器：用子进程跑登记的爬虫命令，记录运行状态与日志。

MVP 用后台线程执行，足够单人/小团队使用；并发量大时再换队列。
"""
import logging
import shlex
import subprocess
import sys
import threading
from datetime import datetime

from ..config import BASE_DIR
from ..database import SessionLocal
from .. import models

log = logging.getLogger(__name__)

# 仓库根（backend 的上一级），脚本默认在此目录下执行
REPO_ROOT = BASE_DIR.parent
_MAX_LOG = 50_000  # 日志最多保存的字符数

# 下载类脚本可能跑数小时
_TIMEOUT_SCRAPE = 60 * 30
_TIMEOUT_DOWNLOAD = 60 * 60 * 24


def command_timeout(command: str) -> int:
    lower = command.lower()
    if "downloader" in lower or "download" in lower.split():
        return _TIMEOUT_DOWNLOAD
    return _TIMEOUT_SCRAPE


def _command_args(command: str) -> list[str]:
    """Use the backend interpreter for registered Python scraper commands."""
    args = shlex.split(command)
    if args and args[0] in {"python", "python3"}:
        args[0] = sys.executable
    return args


def _run(run_id: int, command: str):
    db = SessionLocal()
    try:
        run = db.get(models.CrawlRun, run_id)
        timeout = command_timeout(command)
        try:
            proc = subprocess.run(
                _command_args(command),
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = (proc.stdout or "") + ("\n--- STDERR ---\n" + proc.stderr if proc.stderr else "")
            run.exit_code = proc.returncode
            run.status = models.RUN_SUCCESS if proc.returncode == 0 else models.RUN_FAILED
            run.log = out[-_MAX_LOG:]
        except subprocess.TimeoutExpired as e:
            run.status = models.RUN_FAILED
            run.exit_code = -1
            partial = ""
            if e.stdout:
                partial += e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout
            if e.stderr:
                partial += e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr
            run.log = (partial + f"\n--- 超时（>{timeout // 60} 分钟）---")[-_MAX_LOG:]
        except Exception as e:  # noqa: BLE001
            run.status = models.RUN_FAILED
            run.exit_code = -1
            run.log = f"运行异常：{e}"
            log.exception("爬虫运行失败 run_id=%s", run_id)
        run.finished_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def start_run(db, script: models.CrawlScript) -> models.CrawlRun:
    """登记一次运行并在后台线程启动。"""
    run = models.CrawlRun(script_id=script.id, status=models.RUN_RUNNING)
    db.add(run)
    db.commit()
    db.refresh(run)
    threading.Thread(target=_run, args=(run.id, script.command), daemon=True).start()
    return run
