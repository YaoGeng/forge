"""stats_summary：数值序列统计（s10 数值计算；本地计算块）。"""


def run(params: dict) -> dict:
    nums = [float(x) for x in str(params.get("nums", "")).split(",") if x.strip()]
    if not nums:
        return {"ok": False, "error": "空序列"}
    return {"ok": True, "n": len(nums), "mean": round(sum(nums) / len(nums), 4),
            "min": min(nums), "max": max(nums)}
