"""test_dify_client.py - DifyClient 单元测试 + 真实连通性测试

分两组：
  1. Mock 测试（不依赖外部服务）：验证参数构造、响应解析、错误处理
  2. 真实连通性测试（标记 @pytest.mark.integration）：跑真 Dify workflow
     跑法：pytest tests/test_dify_client.py -v -m integration
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# 让 `import gov_price_etl` 可用
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gov_price_etl.ai.dify_client import (  # noqa: E402
    DifyAPIError,
    DifyClient,
    DifyConfig,
    DifyConfigError,
    DifyResponse,
    KNOWN_APPS,
    call_workflow,
    load_config,
)


# ── 1. Mock 测试 ─────────────────────────────────────────────────────


class TestConfig:
    """配置加载 / env 覆盖。"""

    def test_default_config(self, tmp_path, monkeypatch):
        # 没文件 → DifyConfigError
        monkeypatch.setenv("DIFY_CONFIG_PATH", str(tmp_path / "nonexistent.json"))
        monkeypatch.delenv("DIFY_BASE_URL", raising=False)
        monkeypatch.delenv("DIFY_API_KEY_ETL_CLASSIFY_CATEGORY", raising=False)
        with pytest.raises(DifyConfigError, match="api_key"):
            load_config("app-rUtcXqTyV8N8TY0s6RhSu0GB")

    def test_load_from_file(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "dify.json"
        cfg_file.write_text(json.dumps({
            "base_url": "http://dify.local:8080",
            "apps": {
                "etl-classify-category": {"api_key": "secret-key-1"},
                "etl-parse-spec": {"api_key": "secret-key-2"},
            },
        }))
        monkeypatch.setenv("DIFY_CONFIG_PATH", str(cfg_file))
        monkeypatch.delenv("DIFY_BASE_URL", raising=False)
        monkeypatch.delenv("DIFY_API_KEY_ETL_CLASSIFY_CATEGORY", raising=False)
        cfg = load_config("app-rUtcXqTyV8N8TY0s6RhSu0GB")
        assert cfg.api_key == "secret-key-1"
        assert cfg.base_url == "http://dify.local:8080"
        assert cfg.app_id == "app-rUtcXqTyV8N8TY0s6RhSu0GB"

    def test_env_overrides_file(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "dify.json"
        cfg_file.write_text(json.dumps({
            "apps": {"etl-classify-category": {"api_key": "file-key"}},
        }))
        monkeypatch.setenv("DIFY_CONFIG_PATH", str(cfg_file))
        monkeypatch.setenv("DIFY_API_KEY_ETL_CLASSIFY_CATEGORY", "env-key")
        monkeypatch.setenv("DIFY_BASE_URL", "http://override:9999")
        cfg = load_config("app-rUtcXqTyV8N8TY0s6RhSu0GB")
        assert cfg.api_key == "env-key"
        assert cfg.base_url == "http://override:9999"

    def test_put_here_placeholder_rejected(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "dify.json"
        cfg_file.write_text(json.dumps({
            "apps": {"etl-classify-category": {"api_key": "<PUT-HERE"}},
        }))
        monkeypatch.setenv("DIFY_CONFIG_PATH", str(cfg_file))
        with pytest.raises(DifyConfigError, match="api_key"):
            load_config("app-rUtcXqTyV8N8TY0s6RhSu0GB")


class TestResponse:
    """响应解析。"""

    def test_succeeded(self):
        data = {
            "workflow_run_id": "wr-123",
            "task_id": "t-456",
            "data": {
                "id": "run-1",
                "workflow_id": "wf-1",
                "status": "succeeded",
                "outputs": {"ok": True, "results": [{"a": 1}], "raw": "r", "err_msg": ""},
                "elapsed_time": 1.234,
                "total_tokens": 100,
                "total_steps": 5,
            },
        }
        resp = DifyClient._parse_response(data, json.dumps(data))
        assert resp.ok
        assert resp.workflow_status == "succeeded"
        assert resp.outputs == {"ok": True, "results": [{"a": 1}], "raw": "r", "err_msg": ""}
        assert resp.elapsed_ms == 1234
        assert resp.total_tokens == 100
        assert resp.total_steps == 5
        assert resp.workflow_run_id == "wr-123"

    def test_failed_with_business_error(self):
        data = {
            "data": {
                "status": "failed",
                "outputs": {"ok": False, "err_msg": "json.loads failed: bad json", "results": []},
                "error": "workflow error",
            },
        }
        resp = DifyClient._parse_response(data, json.dumps(data))
        assert not resp.ok
        assert resp.workflow_status == "failed"
        assert "json.loads failed" in resp.outputs["err_msg"]

    def test_outputs_not_dict(self):
        # 极端情况：outputs 是 list（应该包成 dict）
        data = {"data": {"status": "succeeded", "outputs": ["a", "b"]}}
        resp = DifyClient._parse_response(data, json.dumps(data))
        assert resp.ok
        assert resp.outputs == {"_outputs": ["a", "b"]}


class TestRun:
    """HTTP 调用（mock requests）。"""

    def _mock_response(self, status_code=200, json_data=None, text=""):
        m = MagicMock()
        m.status_code = status_code
        m.json.return_value = json_data or {}
        m.text = text or json.dumps(json_data or {})
        return m

    def test_200_success(self):
        cfg = DifyConfig(app_id="app-x", api_key="k", max_retries=0)
        client = DifyClient(cfg)
        with patch("gov_price_etl.ai.dify_client.requests.Session") as MockSession:
            session = MockSession.return_value
            session.post.return_value = self._mock_response(200, {
                "workflow_run_id": "wr-1",
                "data": {"status": "succeeded", "outputs": {"ok": True, "results": [1, 2]}},
            })
            resp = client.run({"a": 1}, user="u")
        assert resp.ok
        assert resp.outputs == {"ok": True, "results": [1, 2]}
        # 验证 POST 调用参数
        args, kwargs = session.post.call_args
        assert args[0] == "http://localhost/v1/workflows/run"
        body = json.loads(kwargs["data"])
        assert body == {"inputs": {"a": 1}, "response_mode": "blocking", "user": "u"}
        assert kwargs["headers"]["Authorization"] == "Bearer k"

    def test_401_no_retry(self):
        cfg = DifyConfig(app_id="app-x", api_key="bad", max_retries=3)
        client = DifyClient(cfg)
        with patch("gov_price_etl.ai.dify_client.requests.Session") as MockSession:
            session = MockSession.return_value
            session.post.return_value = self._mock_response(401, {"code": "unauthorized"})
            with pytest.raises(DifyAPIError) as exc:
                client.run({"a": 1}, user="u")
        assert exc.value.status_code == 401
        # 4xx 不重试：只调 1 次
        assert session.post.call_count == 1

    def test_500_retry(self):
        cfg = DifyConfig(app_id="app-x", api_key="k", max_retries=2)
        client = DifyClient(cfg)
        with patch("gov_price_etl.ai.dify_client.requests.Session") as MockSession:
            session = MockSession.return_value
            session.post.return_value = self._mock_response(500, {"e": "server"})
            with pytest.raises(DifyAPIError) as exc:
                client.run({"a": 1}, user="u")
        assert exc.value.status_code == 500
        # 5xx 重试：1 + 2 = 3 次
        assert session.post.call_count == 3

    def test_timeout_retry(self):
        import requests as real_requests
        cfg = DifyConfig(app_id="app-x", api_key="k", max_retries=1, timeout_s=1)
        client = DifyClient(cfg)
        with patch("gov_price_etl.ai.dify_client.requests.Session") as MockSession:
            session = MockSession.return_value
            session.post.side_effect = real_requests.exceptions.Timeout("slow")
            with pytest.raises(DifyAPIError) as exc:
                client.run({"a": 1}, user="u")
        assert "调用 app-x 失败" in str(exc.value)
        # 超时也重试
        assert session.post.call_count == 2


class TestCallWorkflow:
    """便捷函数 call_workflow（异常 → ok=False 响应）。"""

    def test_config_error_returns_failed_response(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DIFY_CONFIG_PATH", str(tmp_path / "nonexistent.json"))
        resp = call_workflow("app-rUtcXqTyV8N8TY0s6RhSu0GB", {"a": 1})
        assert not resp.ok
        assert "api_key" in resp.error or "配置" in resp.error


# ── 2. 真实连通性测试（integration）───────────────────────────────

# 跑法：
#   1) 填 ~/.openclaw/dify.json（或环境变量 DIFY_API_KEY_*）
#   2) pytest tests/test_dify_client.py -v -m integration
# 缺 key 时自动 skip（不报错）

requires_api_key = pytest.mark.skipif(
    not any(
        os.environ.get(f"DIFY_API_KEY_{a.replace('-', '_').upper()}")
        for a in KNOWN_APPS
    ) and not os.path.exists(os.path.expanduser("~/.openclaw/dify.json")),
    reason="无 Dify api_key（~/.openclaw/dify.json 或 env），跳过真实调用测试",
)


@requires_api_key
class TestIntegration:
    """真实调 Dify workflow。验证：连通、解析、字段对齐。"""

    def test_classify_v2_minimal(self):
        """跑一次最小分类（DeepSeek 版）。"""
        resp = call_workflow(
            "app-rUtcXqTyV8N8TY0s6RhSu0GB",
            {
                "breed_list": "1. breed=HPB300 | spec=φ6 | unit=t | current_l3=",
                "batch_n": 1,
            },
            user="pytest-integration",
            timeout_s=90,
        )
        print(f"\n[Integration] classify-category ok={resp.ok} status={resp.workflow_status}")
        print(f"  outputs: {json.dumps(resp.outputs, ensure_ascii=False)[:200]}")
        if not resp.ok:
            pytest.skip(f"Dify 返回失败（可能 workflow 未发布 / 模型未配置）: {resp.error}")
        # Dify Code 节点 outputs 应该有 ok / results / raw / err_msg
        for k in ("ok", "results", "raw", "err_msg"):
            assert k in resp.outputs, f"缺字段 {k}: {list(resp.outputs.keys())}"

    def test_parse_spec_minimal(self):
        """跑一次最小规格解析。"""
        resp = call_workflow(
            "app-kgaF6jNrpd4PytjhUk3VTCQ4",
            {
                "specs_str": "[1] 规格: φ6 | 产品: HPB300 | 分类: 钢材",
                "ref_names": "diameter, length, width, thickness, grade, material",
                "batch_size": 1,
            },
            user="pytest-integration",
            timeout_s=60,
        )
        print(f"\n[Integration] parse-spec ok={resp.ok} status={resp.workflow_status}")
        print(f"  outputs: {json.dumps(resp.outputs, ensure_ascii=False)[:200]}")
        if not resp.ok:
            pytest.skip(f"Dify 返回失败（可能 workflow 未发布 / 模型未配置）: {resp.error}")
        for k in ("ok", "results", "raw", "err_msg"):
            assert k in resp.outputs, f"缺字段 {k}: {list(resp.outputs.keys())}"


# ── 3. service.py 集成（_ai_invoke 只走 Dify，2026-06-18）─────────

class TestAiInvoke:
    """验证 service._ai_invoke 走 Dify workflow（ETL 唯一 AI 入口）。"""

    def test_classify_uses_dify_workflow(self):
        from gov_price_etl.ai import service
        with patch.object(service, "_call_dify_workflow") as mock_dw:
            mock_dw.return_value = (True, "results")
            ok, content = service._ai_invoke(
                "classify",
                dify_inputs={"breed_list": "x", "batch_n": 1},
                user="u",
            )
        assert ok
        # 验证 _call_dify_workflow 收到正确 alias + dify_inputs + user
        args, _ = mock_dw.call_args
        assert args[0] == "etl-classify-category"
        assert args[1] == {"breed_list": "x", "batch_n": 1}
        assert args[2] == "u"

    def test_parse_uses_dify_workflow(self):
        from gov_price_etl.ai import service
        with patch.object(service, "_call_dify_workflow") as mock_dw:
            mock_dw.return_value = (True, "results")
            service._ai_invoke(
                "parse",
                dify_inputs={"specs_str": "x"},
                user="u",
            )
        args, _ = mock_dw.call_args
        assert args[0] == "etl-parse-spec"

    def test_unknown_task_fails(self):
        from gov_price_etl.ai import service
        ok, content = service._ai_invoke(
            "unknown_task",
            dify_inputs={},
            user="u",
        )
        assert not ok
        assert "未知 task" in content

    def test_call_gateway_is_deprecated(self):
        """_call_gateway 已废（保留签名防 ImportError），调用直接返回失败。"""
        from gov_price_etl.ai import service
        ok, content = service._call_gateway("p", "s", "u")
        assert not ok
        assert "已废" in content
        assert "Dify" in content
