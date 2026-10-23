"""arxiv_search：arXiv Atom API 查询（s5 公开 API 数据拉取；standard 档——公开学术 API 无反爬声明）。"""


def browse(port) -> dict:
    import time

    port.goto("https://export.arxiv.org/api/query?search_query=all:electron&max_results=5")
    port.wait_selector("body", 15_000)
    time.sleep(1.2)
    xml = port.inner_text("body")  # Chromium XML viewer：body inner_text 即源文本
    entries = []
    for chunk in xml.split("<entry>")[1:6]:
        title = chunk.split("<title>", 1)[1].split("</title>", 1)[0]
        eid = chunk.split("<id>", 1)[1].split("</id>", 1)[0]
        entries.append({"title": " ".join(title.split()), "id": eid})
    return {"entries": entries}
