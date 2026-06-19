"""dify_client.py - 通用 Dify Workflow API 客户端

调用 Dify 自建的 ETL workflow：
  - etl-classify-deepseek  (app id: app-rUtcXqTyV8N8TY0s6RhSu0GB)
  - etl-parse-spec         (app id: app-kgaF6jNrpd4PytjhUk3VTCQ4)

Dify API 端点：
  POST {base_url}/v1/workflows/run
  Headers: Authorization: Bearer {api_key}
  Body:    {
             "inputs": {...},         # workflow start 节点变量
             "response_mode": "blocking",  # 同步返回
             "user": "<identifier>"   # 用于 Dify 端会话统计
           }
  Response: {
              "workflow_run_id": "...",
              "task_id": "...",
              "data": {
                "id": "...",
                "workflow_id": "...",
                "status": "succeeded" | "failed" | "stopped",
                "outputs": {...},        # workflow end 节点 outputs
                "error": "...",          # 失败时
                "elapsed_time": ...,
                "total_tokens": ...,
                "total_steps": ...,
                "created_at": ...,
                "finished_at": ...
              }
            }

配置加载顺序（后者覆盖前者）：
  1. ~/.openclaw/dify.json  - 全局默认（不进 git）
  2. 环境变量 DIFY_BASE_URL / DIFY_API_KEY_<APP>  - 临时覆盖

设计：
  - DifyConfig：base_url、api_key、timeout
  - DifyClient：低层 HTTP 调用（一次 workflow run）
  - call_workflow(inputs, user, ...) -> DifyResponse：上层业务包装
  - 自测入口：python3 -m gov_price_etl.ai.dify_client <app_alias> [test]

替代路径：原 _call_gateway (OpenClaw chat/completions) 保留兼容
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import requests

# ── 默认配置 ────────────────────────────────────────────────────────
DEFAULT_BASE_URL = "http://localhost"  # Dify Docker 默认端口 80
DEFAULT_TIMEOUT_S = 120

# 路径：dify/dify.config.local.json（不进 git，存 api_key）
# 优先级：env (DIFY_CONFIG_PATH) > 本地 (dify/dify.config.local.json) > 全局 (~/.openclaw/dify.json，向后兼容)
# 注意：函数内动态读 env（不锁定为 module-level），便于测试 / 热切换。
def _resolve_config_path() -> Path:
    env_path = os.environ.get("DIFY_CONFIG_PATH")
    if env_path:
        return Path(env_path).expanduser()
    # 本地优先（skill 目录下，gitignore）
    project_root = Path(__file__).resolve().parents[2]  # gov_price_etl/ai/dify_client.py → ../../..
    local_path = project_root / "dify" / "dify.config.local.json"
    if local_path.exists():
        return local_path
    # 向后兼容：全局
    return Path("~/.openclaw/dify.json").expanduser()

# 兼容旧用法（list 子命令会 print 这个路径）
DIFY_CONFIG_PATH = _resolve_config_path()

# 已知的 ETL workflow app id 映射
KNOWN_APPS: Dict[str, Dict[str, str]] = {

    "etl-classify-deepseek": {
        "app_id": "app-rUtcXqTyV8N8TY0s6RhSu0GB",
        "purpose": "DeepSeek 版建材分类（含内置 L3 知识库）",
    },
    "etl-parse-spec": {
        "app_id": "app-kgaF6jNrpd4PytjhUk3VTCQ4",
        "purpose": "建材规格解析（diameter / length / thickness 等）",
    },

}


# ── 异常类型 ────────────────────────────────────────────────────────
class DifyError(Exception):
    """Dify workflow 调用错误基类。"""


class DifyConfigError(DifyError):
    """配置缺失或非法（找不到 api_key、base_url 不可达等）。"""


class DifyAPIError(DifyError):
    """Dify API 返回错误（含 HTTP 4xx/5xx、status=failed）。"""

    def __init__(self, message: str, status_code: Optional[int] = None,
                 workflow_status: Optional[str] = None, raw: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.workflow_status = workflow_status
        self.raw = raw or {}


# ── 配置对象 ────────────────────────────────────────────────────────
@dataclass
class DifyConfig:
    """单个 Dify app 的连接配置。"""

    app_id: str
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout_s: int = DEFAULT_TIMEOUT_S
    max_retries: int = 1  # 失败重试次数（不含首次）

    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


# ── 配置加载 ────────────────────────────────────────────────────────
def _load_global_config() -> Dict[str, Any]:
    """从 dify config 文件读默认配置（本地 > 全局，env 覆盖）。

    返回 {"base_url": "...", "apps": {"<app_id>": {"api_key": "..."}, ...}}
    找不到文件 / 解析失败 → 返回空 dict（让 env / 调用方覆盖）
    """
    cfg_path = _resolve_config_path()
    if not cfg_path.exists():
        return {}
    try:
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Dify config {cfg_path} 解析失败: {e}", file=sys.stderr)
        return {}


def load_config(app_id: str) -> DifyConfig:
    """根据 app_id 加载配置（优先级：env > ~/.openclaw/dify.json > 默认）。

    环境变量覆盖：
      DIFY_BASE_URL               - 全局 base URL
      DIFY_API_KEY_<APP_ALIAS>    - 按 alias 的 api key
        例：DIFY_API_KEY_ETL_CLASSIFY_V2=app-xxx
    """
    global_cfg = _load_global_config()
    apps_cfg = global_cfg.get("apps", {})

    # 找 alias（app id 短名，如 "etl-classify-v2"）
    alias = next((a for a, info in KNOWN_APPS.items() if info["app_id"] == app_id), None)

    # 1. 从全局配置拿 api_key
    api_key = ""
    if alias and alias in apps_cfg:
        api_key = apps_cfg[alias].get("api_key", "")
    if app_id in apps_cfg:
        api_key = apps_cfg[app_id].get("api_key", "") or api_key

    # 2. env 覆盖
    if alias:
        env_key = f"DIFY_API_KEY_{alias.replace('-', '_').upper()}"
        api_key = os.environ.get(env_key, api_key)

    base_url = os.environ.get("DIFY_BASE_URL") or global_cfg.get("base_url") or DEFAULT_BASE_URL
    timeout_s = int(os.environ.get("DIFY_TIMEOUT_S", str(DEFAULT_TIMEOUT_S)))

    if not api_key or api_key.startswith("<PUT-HERE"):
        raise DifyConfigError(
            f"❌ 找不到 app {app_id!r} 的 api_key\n"
            f"   1) 填到 {_resolve_config_path()} 的 apps.{alias or app_id}.api_key\n"
            f"   2) 或环境变量 DIFY_API_KEY_{alias.replace('-', '_').upper() if alias else '<APP>'}\n"
            f"   3) Dify 控制台 → App → API Access 复制"
        )

    return DifyConfig(app_id=app_id, api_key=api_key, base_url=base_url, timeout_s=timeout_s)


# ── 响应对象 ────────────────────────────────────────────────────────
@dataclass
class DifyResponse:
    """Dify workflow run 响应的业务对象（统一封装 success/failure）。"""

    ok: bool
    outputs: Dict[str, Any] = field(default_factory=dict)  # workflow end 节点 outputs
    raw: str = ""                                          # 调试用：原始返回
    error: str = ""                                        # 错误描述
    workflow_run_id: str = ""
    elapsed_ms: int = 0
    total_tokens: int = 0
    total_steps: int = 0
    workflow_status: str = ""                              # succeeded/failed/stopped

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "outputs": self.outputs,
            "raw": self.raw,
            "error": self.error,
            "workflow_run_id": self.workflow_run_id,
            "elapsed_ms": self.elapsed_ms,
            "total_tokens": self.total_tokens,
            "total_steps": self.total_steps,
            "workflow_status": self.workflow_status,
        }


# ── 客户端 ──────────────────────────────────────────────────────────
class DifyClient:
    """Dify workflow 同步调用客户端。"""

    def __init__(self, cfg: DifyConfig):
        self.cfg = cfg

    def run(self, inputs: Dict[str, Any], user: str = "etl-service",
            response_mode: str = "blocking") -> DifyResponse:
        """调用一次 workflow run，blocking 模式同步等待结果。

        Args:
            inputs: workflow start 节点声明的输入变量
            user:   调用方标识（Dify 用于统计/会话隔离，建议带任务前缀）
            response_mode: "blocking" 同步 / "streaming" 流式（本客户端只支持 blocking）

        Returns:
            DifyResponse（成功 ok=True，outputs 含 workflow end 节点的输出）
        """
        url = f"{self.cfg.base_url}/v1/workflows/run"
        body = json.dumps({
            "inputs": inputs,
            "response_mode": response_mode,
            "user": user,
        }).encode("utf-8")

        last_err: Optional[DifyAPIError] = None
        for attempt in range(self.cfg.max_retries + 1):
            try:
                s = requests.Session()
                s.trust_env = False
                r = s.post(
                    url,
                    data=body,
                    headers=self.cfg.headers(),
                    timeout=self.cfg.timeout_s,
                )
            except requests.exceptions.Timeout as e:
                last_err = DifyAPIError(
                    f"timeout after {self.cfg.timeout_s}s: {e}",
                )
            except requests.exceptions.RequestException as e:
                last_err = DifyAPIError(
                    f"connection error: {e}",
                )
            else:
                if r.status_code == 200:
                    return self._parse_response(r.json(), r.text)
                # 4xx 不重试（鉴权 / 业务错），5xx 重试
                if 400 <= r.status_code < 500:
                    raise DifyAPIError(
                        f"HTTP {r.status_code}: {r.text[:300]}",
                        status_code=r.status_code,
                        raw={"text": r.text[:500]},
                    )
                last_err = DifyAPIError(
                    f"HTTP {r.status_code}: {r.text[:200]}",
                    status_code=r.status_code,
                )

            # 重试前 sleep
            if attempt < self.cfg.max_retries:
                sleep_s = 2 ** attempt
                time.sleep(sleep_s)

        # 全部重试失败
        if last_err is not None:
            # 保留最后一次的 status_code
            raise DifyAPIError(
                f"调用 {self.cfg.app_id} 失败（{self.cfg.max_retries + 1} 次）: {last_err}",
                status_code=last_err.status_code,
                raw=last_err.raw,
            )
        raise DifyAPIError(f"调用 {self.cfg.app_id} 失败：未知原因")

    @staticmethod
    def _parse_response(data: dict, raw_text: str) -> DifyResponse:
        """解析 Dify /v1/workflows/run 的 200 响应。"""
        run_id = data.get("workflow_run_id", "")
        d = data.get("data") or {}
        status = d.get("status", "")
        outputs = d.get("outputs") or {}
        wf_err = d.get("error", "")

        ok = (status == "succeeded") and not wf_err
        # 兼容：把 ok/err_msg/results/raw 一并塞到 outputs（方便 ETL 端读）
        # Dify 的 workflow end 节点本身就声明了这 4 个变量 → outputs 里已有

        return DifyResponse(
            ok=ok,
            outputs=outputs if isinstance(outputs, dict) else {"_outputs": outputs},
            raw=raw_text,
            error=wf_err or "",
            workflow_run_id=run_id,
            elapsed_ms=int((d.get("elapsed_time") or 0) * 1000),
            total_tokens=int(d.get("total_tokens") or 0),
            total_steps=int(d.get("total_steps") or 0),
            workflow_status=status,
        )


# ── 便捷入口（业务层用）─────────────────────────────────────────────
def call_workflow(app_id: str, inputs: Dict[str, Any], user: str = "etl-service",
                  timeout_s: Optional[int] = None) -> DifyResponse:
    """便捷函数：加载 config + 创建 client + run。

    失败时返回 ok=False 的 DifyResponse（不抛异常），便于上层统一处理。
    """
    try:
        cfg = load_config(app_id)
    except DifyConfigError as e:
        return DifyResponse(ok=False, error=str(e))

    if timeout_s:
        cfg.timeout_s = timeout_s

    client = DifyClient(cfg)
    try:
        return client.run(inputs, user=user)
    except DifyAPIError as e:
        return DifyResponse(ok=False, error=str(e), raw=json.dumps(e.raw) if e.raw else "")
    except Exception as e:
        return DifyResponse(ok=False, error=f"unexpected: {e}")


# ── 自测 ────────────────────────────────────────────────────────────
def _self_test(app_id: str) -> int:
    """跑一次最小 workflow 验证连通性。"""
    print(f"─" * 60)
    print(f"🧪 Dify workflow 联通测试")
    print(f"   app_id : {app_id}")
    print(f"   用途   : {KNOWN_APPS.get(_alias_of(app_id), {}).get('purpose', '?')}")
    print(f"─" * 60)

    # 最小测试输入（每个 app 给一条样例）
    if "classify" in app_id:
        inputs = {
            "breed_list": "1. breed=HPB300 | spec=φ6 | unit=t | current_l3=",
            "batch_n": 1,
        }
    elif "parse" in app_id:
        inputs = {
            "specs_str": "[1] 规格: φ6 | 产品: HPB300 | 分类: 钢材",
            "ref_names": "diameter, length, width, thickness, grade, material",
            "batch_size": 1,
        }
    else:
        inputs = {}

    t0 = time.time()
    resp = call_workflow(app_id, inputs, user="dify-client-self-test", timeout_s=60)
    dt = time.time() - t0

    print(f"\n   耗时     : {dt:.2f}s")
    print(f"   workflow_run_id: {resp.workflow_run_id or '(空)'}")
    print(f"   status   : {resp.workflow_status or '(空)'}")
    print(f"   ok       : {resp.ok}")
    print(f"   total_tokens: {resp.total_tokens}")
    print(f"   total_steps : {resp.total_steps}")
    print(f"   error    : {resp.error or '(无)'}")
    print(f"\n   outputs  :")
    print(json.dumps(resp.outputs, ensure_ascii=False, indent=4))
    print(f"─" * 60)

    if resp.ok:
        print("✅ 联通成功")
        return 0
    else:
        print(f"❌ 失败（见上方 error / outputs.err_msg）")
        return 1


def _alias_of(app_id: str) -> Optional[str]:
    for alias, info in KNOWN_APPS.items():
        if info["app_id"] == app_id:
            return alias
    return None


def main() -> int:
    """CLI 入口。

    用法：
      python3 -m gov_price_etl.ai.dify_client list
      python3 -m gov_price_etl.ai.dify_client test <alias_or_app_id>
    """
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd = sys.argv[1]

    if cmd == "list":
        print("─" * 60)
        print("📋 已注册的 ETL workflow app")
        print("─" * 60)
        for alias, info in KNOWN_APPS.items():
            print(f"  {alias}")
            print(f"    app_id : {info['app_id']}")
            print(f"    用途    : {info['purpose']}")
        print(f"\n  配置路径: {DIFY_CONFIG_PATH}")
        return 0

    if cmd == "test":
        if len(sys.argv) < 3:
            print("用法: python3 -m gov_price_etl.ai.dify_client test <alias_or_app_id>")
            print(f"  已知: {list(KNOWN_APPS.keys())}")
            return 1
        target = sys.argv[2]
        # 支持 alias 简写
        if target in KNOWN_APPS:
            target = KNOWN_APPS[target]["app_id"]
        return _self_test(target)

    print(f"未知子命令: {cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
