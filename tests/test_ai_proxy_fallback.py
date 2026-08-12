"""
test_ai_proxy_fallback.py - AI 请求代理 fallback 策略测试

策略（用户需求）:
  1. 先直接请求（不走代理）
  2. 直连失败 → 用配置的代理再请求
  3. 仍失败 → 外层重试 3 次
  4. 全部失败 → 归为未分类 (result.success=False)

运行:
    uv run pytest tests/test_ai_proxy_fallback.py
    uv run python tests/test_ai_proxy_fallback.py
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.ai_client import DeepSeekClient

CFG = {
    "ai": {
        "base_url": "https://api.agnes-ai.cn/v1",
        "model": "agnes-2.5-flash",
        "timeout": 5,
        "max_retries": 3,
        "max_cost_yuan": 10.0,
        "api_key": "test-key",  # 构造函数从 config 读 key
    },
    "classification": {"cache_dir": "data/cache"},
}


def _fake_proxy_adapter():
    """构造一个启用了代理的 ProxyAdapter 替身"""
    pa = MagicMock()
    pa.get_proxies.return_value = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
    return pa


def _ok_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": '{"l1": "开发技术", "l2": "文档教程", "confidence": 0.9, "reason": "x"}'}}]
    }
    return resp


def _http_error_response(status: int = 500):
    resp = MagicMock()
    resp.status_code = status
    resp.text = "boom"
    return resp


def _make_client(proxy=None):
    client = DeepSeekClient(config=CFG, categories=[], proxy_adapter=proxy, api_key="test-key")
    client.cache = MagicMock()          # 关闭真实缓存
    client.cache.get.return_value = None
    return client


# ──────────────────────────────────────────────
#  1. 直连成功 → 不再走代理
# ──────────────────────────────────────────────

def test_direct_success_does_not_use_proxy():
    client = _make_client(proxy=_fake_proxy_adapter())
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs.get("proxies"))
        return _ok_response()

    with patch("modules.ai_client.requests.post", side_effect=fake_post):
        content = client._call_api("sys", "user")

    assert "开发技术" in content
    # 只请求了一次，且是直连 (proxies=None)
    assert len(calls) == 1
    assert calls[0] is None


# ──────────────────────────────────────────────
#  2. 直连失败 → 走代理成功
# ──────────────────────────────────────────────

def test_direct_fail_then_proxy_success():
    client = _make_client(proxy=_fake_proxy_adapter())
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs.get("proxies"))
        # 第一次直连失败，第二次（代理）成功
        if len(calls) == 1:
            raise ConnectionError("direct refused")
        return _ok_response()

    with patch("modules.ai_client.requests.post", side_effect=fake_post):
        content = client._call_api("sys", "user")

    assert "开发技术" in content
    assert len(calls) == 2
    assert calls[0] is None                    # 先直连
    assert calls[1]["http"] == "http://127.0.0.1:7890"  # 后代理


# ──────────────────────────────────────────────
#  3. HTTP 错误也算失败 → 切代理
# ──────────────────────────────────────────────

def test_direct_http_error_then_proxy():
    client = _make_client(proxy=_fake_proxy_adapter())
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs.get("proxies"))
        if len(calls) == 1:
            return _http_error_response(500)
        return _ok_response()

    with patch("modules.ai_client.requests.post", side_effect=fake_post):
        content = client._call_api("sys", "user")

    assert len(calls) == 2
    assert calls[0] is None
    assert calls[1] is not None


# ──────────────────────────────────────────────
#  4. 无代理配置 → 只直连，失败即抛
# ──────────────────────────────────────────────

def test_no_proxy_only_direct():
    client = _make_client(proxy=None)
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs.get("proxies"))
        raise ConnectionError("refused")

    with patch("modules.ai_client.requests.post", side_effect=fake_post):
        try:
            client._call_api("sys", "user")
            assert False, "应抛出异常"
        except ConnectionError:
            pass

    assert len(calls) == 1
    assert calls[0] is None


# ──────────────────────────────────────────────
#  5. 全部失败 → classify_one 归为未分类
# ──────────────────────────────────────────────

def test_all_fail_classifies_as_unclassified():
    client = _make_client(proxy=None)

    def fake_post(url, **kwargs):
        raise ConnectionError("refused")

    with patch("modules.ai_client.requests.post", side_effect=fake_post):
        result = client.classify_one({
            "url": "https://example.com/a",
            "title": "测试页",
            "domain": "example.com",
            "description": "",
            "keywords": [],
        })

    assert result.success is False
    assert result.error, "应有失败原因"
    assert not result.category_l1, "失败书签不设置分类 → 前端显示未分类"
    assert client.get_stats()["failed"] >= 1
    assert client.get_stats()["retries"] >= 2  # 重试多次后放弃


# ──────────────────────────────────────────────
#  6. 代理也可能失败 → 重试后仍归未分类（带代理场景）
# ──────────────────────────────────────────────

def test_both_channels_fail_then_unclassified():
    client = _make_client(proxy=_fake_proxy_adapter())
    call_count = [0]

    def fake_post(url, **kwargs):
        call_count[0] += 1
        raise ConnectionError("all refused")

    with patch("modules.ai_client.requests.post", side_effect=fake_post):
        result = client.classify_one({
            "url": "https://example.com/b",
            "title": "测试页2",
            "domain": "example.com",
            "description": "",
            "keywords": [],
        })

    assert result.success is False
    assert not result.category_l1
    # 每次尝试先直连再代理 → 多次尝试后放弃
    assert call_count[0] >= 2
    assert client.get_stats()["failed"] >= 1


# ──────────────────────────────────────────────
#  内置 runner
# ──────────────────────────────────────────────

def _run_all():
    tests = [
        (name, fn) for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{'=' * 50}\n{len(tests)} tests, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
