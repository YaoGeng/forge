"""T0.1b Browser-Use Agent 冒烟（记录型，不阻塞 MS-0 gate）。

用法：python spikes/agent_smoke.py <outcome_json_path>
产出 JSON 契约：{"used_executable": str|null, "done": bool, "top_title": str, "screenshot": str}
无 OPENAI_API_KEY → 打印原因并退出码 3（EVIDENCE 记结论 C）。

带 Key 分支按安装版本（browser-use 0.13.11）文档接入：模型经 OPENAI_BASE_URL +
M0_AGENT_MODEL（默认 gpt-4.1-mini）选择；该分支在首次具备 Key 的运行中验证。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# 让 `python spikes/agent_smoke.py` 可导入 spikes/common
sys.path.insert(0, str(Path(__file__).resolve().parent))

TASK_TEMPLATE = (
    "打开 {url} ，读取排名第一的帖子标题，"
    "把页面截图保存到 {shot}，最后只输出该标题文本。"
)


def _chromium_executable():
    try:
        from common.browser import resolve_chromium_executable

        return str(resolve_chromium_executable())
    except RuntimeError:
        return None


def run_agent(outcome: dict) -> dict:
    from browser_use import Agent, BrowserProfile

    live_front = "https://hn.algolia.com/"  # 与 T0.1a 同一 live 目标（裁定见台账）

    try:
        from browser_use.llm.openai import ChatOpenAI
    except ImportError:  # 版本差异兜底：0.13 前置版本在 llm 顶层导出
        from browser_use.llm import ChatOpenAI  # type: ignore[no-redef]

    executable = outcome["used_executable"]
    profile_kwargs = {"headless": True}
    if executable:
        profile_kwargs["executable_path"] = executable
    llm = ChatOpenAI(
        model=os.environ.get("M0_AGENT_MODEL", "gpt-4.1-mini"),
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
    )
    shot_path = Path(outcome["screenshot"])
    agent = Agent(
        task=TASK_TEMPLATE.format(url=live_front, shot=shot_path),
        llm=llm,
        browser_profile=BrowserProfile(**profile_kwargs),
    )
    result = asyncio.run(agent.run(max_steps=15))
    final = getattr(result, "final_result", None)
    outcome["top_title"] = (final() if callable(final) else final) or ""
    outcome["done"] = bool(outcome["top_title"]) and shot_path.exists()
    return outcome


def main() -> int:
    out_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path("spikes/evidence/t0.1_agent_smoke.json")
    )
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "SKIP: OPENAI_API_KEY 未配置——Agent 冒烟属记录型检查，"
            "记结论 C（登记选型风险，不阻塞 gate；gate 由 T0.1a/T0.2/T0.3 承载）"
        )
        return 3

    outcome = {
        "used_executable": _chromium_executable(),
        "done": False,
        "top_title": "",
        "screenshot": str(out_path.with_suffix(".png")),
    }
    try:
        outcome = run_agent(outcome)
    except Exception as exc:  # 记录型检查：失败即记录，不抛给调用方
        outcome["top_title"] = f"ERROR: {type(exc).__name__}: {exc}"
    out_path.write_text(
        json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    if outcome["used_executable"]:
        print("结论 A：Agent 使用 Patchright Chromium，选型全链成立")
    else:
        print("结论 B：Agent 用自带 Chromium 完成；Patchright 组合登记为 M06-a 首个验证项")
    return 0 if outcome["done"] else 2


if __name__ == "__main__":
    sys.exit(main())
