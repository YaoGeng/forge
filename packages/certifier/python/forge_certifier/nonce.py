"""nonce 客户端（C6：服务端一次性存储、TTL 5 分钟、全局唯一属主）。"""


def fetch_nonce(http, server_base: str, device_fp: str) -> dict:
    """领取 nonce；返回 {nonce, expires_at, device_id}。"""
    r = http.post(
        f"{server_base}/api/v1/certifications/nonce", json={"device_fp": device_fp}
    )
    if r.status_code != 201:
        raise RuntimeError(f"nonce 领取失败：{r.status_code} {r.text}")
    return r.json()
