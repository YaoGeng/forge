"""demo_block 入口：按 interface 输入抓取笔记标题列表（演示用，全部经 runtime 外观）。"""
from forge_block_sdk import runtime


def run(params: dict) -> dict:
    runtime.browser.open("https://www.xiaohongshu.com/search_result?keyword=" + params["topic"])
    titles = runtime.browser.extract(".note-list .title", limit=params.get("limit", 10))
    summary = runtime.ai.generate_text(f"总结以下笔记标题：{titles}")
    return {"titles": titles, "summary": summary}
