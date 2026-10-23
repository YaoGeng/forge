"""hn.algolia.com 两连搜索（s1 搜索聚合读取；medium 档）。

MS-1E 遗留录制（?q=python → ?q=nodejs）补结构化脚本（T1.72）：导航与已认证
录制步严格一致，抽取走快照切片——输出能力不影响既有认证/注册。
"""


def browse(port) -> dict:
    import time

    port.goto("https://hn.algolia.com/?q=python")
    port.wait_selector("body", 15_000)
    time.sleep(1.2)
    port.goto("https://hn.algolia.com/?q=nodejs")
    port.wait_selector("body", 15_000)
    time.sleep(1.2)
    html = port.snapshot_html()
    hits = []
    for chunk in html.split('class="story_title"')[1:3]:
        a = chunk.split("<a ", 1)[1]
        hits.append({"title": a.split(">", 1)[1].split("<", 1)[0].strip(),
                     "url": a.split('href="', 1)[1].split('"', 1)[0]})
    return {"hits": hits}
