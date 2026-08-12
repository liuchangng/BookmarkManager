"""
webapp.py - 收藏夹管理工具 Web 版入口 (FastAPI)

启动: uv run python webapp.py  →  http://127.0.0.1:8989
功能:
  - 单页前端 (web/static/)：上传 → 处理(SSE 进度) → 结果 → 导出
  - API: 上传解析 / 启动流水线(SSE) / 取消 / 书签查询 / 审核修改 / 导出 / 设置
"""

import asyncio
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from modules.config_manager import ConfigManager
from modules.secure_store import SecureStore
from modules.proxy import ProxyManager
from modules.pipeline import Pipeline
from modules.html_builder import build_and_save

logger = logging.getLogger("web")

PROJECT_ROOT = Path(__file__).resolve().parent

# ──────────────────────────────────────────────
#  全局状态（单任务互斥）
# ──────────────────────────────────────────────

config = ConfigManager(PROJECT_ROOT / "config.yaml")
config.load()

secure_store = SecureStore(PROJECT_ROOT / "data" / ".secure")
proxy_manager = ProxyManager(config, secure_store)

pipeline = Pipeline(config, secure_store, proxy_manager)

# 事件广播: {subscriber_id: queue.Queue}
_subscribers: dict[int, queue.Queue] = {}
_sub_lock = threading.Lock()
_next_sub_id = 0


def _broadcast(event: dict):
    """把流水线事件广播给所有 SSE 订阅者。
    慢消费者（队列满）时：瞬时事件（进度/日志/item）直接丢弃，
    重要事件（done/error/cancelled/snapshot）最多等 5 秒，避免阻塞流水线线程。
    """
    etype = event.get("type")
    important = etype in ("done", "error", "cancelled", "snapshot", "bookmarks_updated")
    with _sub_lock:
        for q in list(_subscribers.values()):
            if important:
                try:
                    q.put(event, timeout=5)
                except queue.Full:
                    pass
            else:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass


pipeline.set_event_callback(_broadcast)


def _serialize_bookmark(bm) -> dict:
    return {
        "id": bm.id,
        "title": bm.title,
        "url": bm.url,
        "domain": bm.domain,
        "folder": bm.folder,
        "root_folder": bm.root_folder,
        "add_date": bm.add_date,
        "category_l1": bm.category_l1 or "📁 其他",
        "category_l2": bm.category_l2 or "未分类",
        "classify_method": bm.classify_method or "",
        "confidence": bm.confidence,
        "status": bm.status,
        "http_status": bm.http_status,
        "probe_error": bm.probe_error or "",
        "page_summary": bm.page_summary or "",
        "tags": list(bm.tags or []),
        "user_confirmed": bm.user_confirmed,
        "user_deleted": bm.user_deleted,
    }


app = FastAPI(title="收藏夹管理工具", version="2.0.0")

UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
EXPORT_DIR = PROJECT_ROOT / "data" / "exports"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
#  前端
# ──────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(PROJECT_ROOT / "web" / "static" / "index.html")


# ──────────────────────────────────────────────
#  上传 & 解析
# ──────────────────────────────────────────────

@app.post("/api/upload")
async def upload_bookmarks(file: UploadFile = File(...)):
    """上传书签 HTML/JSON → 解析去重 → 返回书签列表"""
    if pipeline.is_running():
        raise HTTPException(409, "流水线正在运行中，请等待完成或取消")

    filename = Path(file.filename or "bookmarks.html").name
    if not filename.lower().endswith((".html", ".htm", ".json")):
        raise HTTPException(400, "仅支持 HTML/JSON 书签文件")

    save_path = UPLOAD_DIR / f"{int(time.time())}_{filename}"
    content = await file.read()
    save_path.write_bytes(content)

    try:
        bookmarks = pipeline.parse_file(str(save_path))
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(422, f"解析失败: {type(e).__name__}: {e}")

    return {
        "ok": True,
        "count": len(bookmarks),
        "filename": filename,
        "bookmarks": [_serialize_bookmark(b) for b in bookmarks],
        "stats": pipeline._collect_stats(),
    }


# ──────────────────────────────────────────────
#  流水线 (SSE)
# ──────────────────────────────────────────────

@app.post("/api/process")
async def start_process():
    """启动流水线（后台线程），事件通过 /api/events SSE 推送"""
    if not pipeline.bookmarks:
        raise HTTPException(400, "请先上传书签文件")
    if pipeline.is_running():
        raise HTTPException(409, "流水线已在运行中")

    try:
        pipeline.start()
    except RuntimeError as e:
        raise HTTPException(409, str(e))

    return {"ok": True, "message": "流水线已启动"}


@app.post("/api/cancel")
async def cancel_process():
    pipeline.cancel()
    return {"ok": True}


@app.get("/api/events")
async def sse_events(request: Request):
    """SSE 事件流：推送流水线进度/日志/结果"""
    global _next_sub_id
    with _sub_lock:
        _next_sub_id += 1
        sub_id = _next_sub_id
        q: queue.Queue = queue.Queue(maxsize=200)
        _subscribers[sub_id] = q

    async def gen():
        try:
            # 连接即推送当前快照
            yield "event: snapshot\ndata: " + _json_snapshot() + "\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = q.get(timeout=1.0)
                except queue.Empty:
                    # 心跳，保持连接
                    yield ": ping\n\n"
                    continue
                data = _json_dumps(event)
                yield f"data: {data}\n\n"
        finally:
            with _sub_lock:
                _subscribers.pop(sub_id, None)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


def _json_snapshot() -> str:
    """当前状态快照（书签 + 分布 + 统计）"""
    return _json_dumps({
        "type": "snapshot",
        "bookmarks": [_serialize_bookmark(b) for b in pipeline.bookmarks],
        "distribution": pipeline.get_distribution(),
        "stats": pipeline._collect_stats(),
        "running": pipeline.is_running(),
    })


# ──────────────────────────────────────────────
#  结果查询 & 审核
# ──────────────────────────────────────────────

@app.get("/api/bookmarks")
async def get_bookmarks(filter: str = "all"):
    """书签列表（filter: all/dead/local/unclassified）"""
    return {
        "bookmarks": [_serialize_bookmark(b) for b in pipeline.bookmarks
                      if not b.user_deleted and
                      (filter == "all" or
                       (filter == "dead" and b.status == "dead") or
                       (filter == "local" and b.status == "local") or
                       (filter == "unclassified" and
                        (not b.category_l1 or b.category_l1 in ("其他", "📁 其他"))))],
    }


@app.get("/api/distribution")
async def get_distribution():
    return {"distribution": pipeline.get_distribution()}


@app.post("/api/bookmarks/{index}/classify")
async def set_classify(index: int, body: dict):
    """手动修改分类（审核）: body = {l1, l2}"""
    bookmarks = [b for b in pipeline.bookmarks if not b.user_deleted]
    if index < 0 or index >= len(bookmarks):
        raise HTTPException(404, "书签不存在")
    bm = bookmarks[index]
    l1 = str(body.get("l1", "")).strip()
    l2 = str(body.get("l2", "")).strip()
    if not l1:
        raise HTTPException(400, "分类不能为空")
    bm.category_l1 = l1
    bm.category_l2 = l2 or "未分类"
    bm.classify_method = "manual"
    bm.confidence = 1.0
    bm.user_confirmed = True
    return {"ok": True, "bookmark": _serialize_bookmark(bm)}


@app.post("/api/bookmarks/{index}/delete")
async def delete_bookmark(index: int):
    """标记删除单条书签"""
    bookmarks = [b for b in pipeline.bookmarks if not b.user_deleted]
    if index < 0 or index >= len(bookmarks):
        raise HTTPException(404, "书签不存在")
    bookmarks[index].user_deleted = True
    return {"ok": True}


@app.post("/api/bookmarks/delete-dead")
async def delete_all_dead():
    """一键删除所有失效书签"""
    count = pipeline.delete_dead()
    return {"ok": True, "deleted": count}


@app.post("/api/remap")
async def remap_categories():
    """把现有 l1 收敛到固定 8 类体系（关键词映射，未命中归「其他」）"""
    remapped = pipeline.remap_to_taxonomy()
    return {"ok": True, "old_categories_merged": len(remapped), "detail": remapped}


@app.post("/api/merge")
async def merge_categories(body: dict = {}):
    """合并小分类: body = {min_count: int}（默认 2），l1 下 ≤min_count 条的 l2 归并到「其他」"""
    min_count = int(body.get("min_count", 2))
    merged = pipeline.merge_small_categories(min_count=min_count)
    total_merged = sum(sum(subs.values()) for subs in merged.values())
    return {"ok": True, "merged_l2": len(merged), "bookmarks_moved": total_merged, "detail": merged}


# ──────────────────────────────────────────────
#  导出
# ──────────────────────────────────────────────

@app.post("/api/export")
async def export_html(body: dict = None):
    """生成标准 Netscape HTML → 返回下载路径"""
    if not pipeline.bookmarks:
        raise HTTPException(400, "没有书签数据")

    body = body or {}
    include_dead = bool(body.get("include_dead", config.get("output.export_include_dead", False)))
    include_local = bool(body.get("include_local", config.get("output.export_include_local", True)))

    ts = time.strftime("%Y%m%d_%H%M%S")
    output_path = EXPORT_DIR / f"bookmark-{ts}.html"

    result = build_and_save(
        bookmarks=pipeline.bookmarks,
        output_path=str(output_path),
        include_dead=include_dead,
        include_local=include_local,
    )

    if not result["success"]:
        raise HTTPException(500, f"HTML 生成失败: {result['validation']['errors']}")

    return {
        "ok": True,
        "path": f"/api/export/download?name={output_path.name}",
        "stats": result["stats"],
        "validation": result["validation"],
    }


@app.get("/api/export/download")
async def export_download(name: str):
    """下载生成的 HTML 文件"""
    file_path = EXPORT_DIR / Path(name).name
    if not file_path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(
        str(file_path),
        media_type="text/html",
        filename=file_path.name,
    )


# ──────────────────────────────────────────────
#  设置
# ──────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    """读取设置（AI Key 只回显尾 4 位）"""
    key = secure_store.load("deepseek")
    ai_cfg = config.get("ai", {})
    return {
        "proxy": {
            "enabled": proxy_manager.is_enabled(),
            "custom_enabled": config.get("proxy.custom.enabled", False),
            "host": config.get("proxy.custom.host", ""),
            "port": config.get("proxy.custom.port", 0),
            "username": config.get("proxy.custom.username", ""),
            "use_for_ai": config.get("proxy.use_for.ai_api", False),
        },
        "ai": {
            "configured": bool(key),
            "key_tail": key[-4:] if key else "",
            "provider": ai_cfg.get("provider", "deepseek"),
            "model": ai_cfg.get("model", ""),
            "base_url": ai_cfg.get("base_url", ""),
            "max_cost_yuan": ai_cfg.get("max_cost_yuan", 5.0),
        },
        "export": {
            "include_dead": config.get("output.export_include_dead", False),
            "include_local": config.get("output.export_include_local", True),
        },
    }


@app.post("/api/settings")
async def update_settings(body: dict):
    """保存设置"""
    # 代理
    proxy_cfg = body.get("proxy")
    if isinstance(proxy_cfg, dict):
        config.set("proxy.enabled", bool(proxy_cfg.get("enabled", config.get("proxy.enabled", False))))
        config.set("proxy.custom.enabled", bool(proxy_cfg.get("custom_enabled", False)))
        config.set("proxy.custom.host", str(proxy_cfg.get("host", "")))
        config.set("proxy.custom.port", int(proxy_cfg.get("port", 0)))
        config.set("proxy.custom.username", str(proxy_cfg.get("username", "")))
        config.set("proxy.use_for.ai_api", bool(proxy_cfg.get("use_for_ai", False)))
        proxy_manager.save_config()
        proxy_manager.load_config()

    # AI
    ai_cfg = body.get("ai")
    if isinstance(ai_cfg, dict):
        if ai_cfg.get("api_key"):
            secure_store.save("deepseek", str(ai_cfg["api_key"]))
        if ai_cfg.get("max_cost_yuan") is not None:
            config.set("ai.max_cost_yuan", float(ai_cfg["max_cost_yuan"]))
        config.set("ai.model", str(ai_cfg.get("model", config.get("ai.model", ""))))
        config.set("ai.base_url", str(ai_cfg.get("base_url", config.get("ai.base_url", ""))))
        config.save()

    # 导出默认
    export_cfg = body.get("export")
    if isinstance(export_cfg, dict):
        config.set("output.export_include_dead", bool(export_cfg.get("include_dead", False)))
        config.set("output.export_include_local", bool(export_cfg.get("include_local", True)))
        config.save()

    return {"ok": True}


@app.post("/api/settings/proxy-test")
async def test_proxy():
    """测试代理连通性"""
    result = proxy_manager.test_connection()
    return result


@app.post("/api/settings/ai-test")
async def test_ai(body: dict = None):
    """测试 AI API Key"""
    from modules.ai_client import test_api_key
    body = body or {}
    api_key = body.get("api_key") or secure_store.load("deepseek")
    if not api_key:
        return {"ok": False, "error": "未配置 API Key"}
    result = test_api_key(
        api_key,
        base_url=config.get("ai.base_url", ""),
        model=config.get("ai.model", ""),
    )
    return {"ok": result.get("success", False), "message": result.get("error") or "连接成功"}


# 静态资源（前端）
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "web" / "static"), name="static")


# ──────────────────────────────────────────────
#  入口
# ──────────────────────────────────────────────

def main():
    import uvicorn
    import webbrowser
    import threading
    import logging

    # 日志落盘: data/logs/webapp.log（同时保留控制台输出）
    log_dir = PROJECT_ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "webapp.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )

    host = config.get("web.host", "127.0.0.1")
    port = int(config.get("web.port", 8989))

    if config.get("web.auto_open_browser", True):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    print(f"🌐 收藏夹管理工具 Web 版已启动: http://{host}:{port}")
    print("按 Ctrl+C 停止服务")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
