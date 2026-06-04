"""爬虫脚本运行器：用子进程跑登记的爬虫命令，记录运行状态与日志。

MVP 用后台线程执行，足够单人/小团队使用；并发量大时再换队列。
"""
import logging
import shlex
import subprocess
import threading
from datetime import datetime

from ..config import BASE_DIR
from ..database import SessionLocal
from .. import models

log = logging.getLogger(__name__)

# 仓库根（backend 的上一级），脚本默认在此目录下执行
REPO_ROOT = BASE_DIR.parent
_MAX_LOG = 50_000  # 日志最多保存的字符数


def _run(run_id: int, command: str):
    db = SessionLocal()
    try:
        run = db.get(models.CrawlRun, run_id)
        try:
            proc = subprocess.run(
                shlex.split(command),
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=60 * 30,
            )
            out = (proc.stdout or "") + ("\n--- STDERR ---\n" + proc.stderr if proc.stderr else "")
            run.exit_code = proc.returncode
            run.status = "success" if proc.returncode == 0 else "failed"
            run.log = out[-_MAX_LOG:]
        except Exception as e:  # noqa: BLE001
            run.status = "failed"
            run.exit_code = -1
            run.log = f"运行异常：{e}"
            log.exception("爬虫运行失败 run_id=%s", run_id)
        run.finished_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def start_run(db, script: models.CrawlScript) -> models.CrawlRun:
    """登记一次运行并在后台线程启动。"""
    run = models.CrawlRun(script_id=script.id, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    threading.Thread(target=_run, args=(run.id, script.command), daemon=True).start()
    return run
