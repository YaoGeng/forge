"""CLI 命令层（docs/17 T2.10）：login / logout / library / run。

run 的执行流（下载→验签→执行→上报）在 T2.12 装配；本层先立护栏：
未登录一律退出码 2 + 中文提示。CliError = 用户可读错误（exit 1）。
"""
from __future__ import annotations

import getpass
import sys

from . import state as state_mod


class CliError(Exception):
    """用户可读错误（打印后退出码 1）。"""


def _require_token(home=None) -> str:
    st = state_mod.load()
    token = st.get("token")
    if not token:
        print("未登录——请先执行 forge-runner login <邮箱>", file=sys.stderr)
        raise SystemExit(2)
    return token


def cmd_login(email: str, password: str | None, client, home=None) -> None:
    from .client import ClientError

    password = password or getpass.getpass("密码：")
    try:
        status, body = client.post_json(
            "/api/v1/auth/login", {"email": email, "password": password})
    except ClientError as exc:
        raise CliError(str(exc)) from exc
    if status != 200 or not isinstance(body, dict) or "token" not in body:
        detail = (body or {}).get("detail") if isinstance(body, dict) else None
        raise CliError(detail or f"登录失败（HTTP {status}）")
    st = state_mod.load()
    st.update({"token": body["token"], "user_id": body.get("user_id"),
               "email": email})
    state_mod.save(st)
    print(f"已登录：{email}")


def cmd_logout(client) -> None:
    st = state_mod.load()
    if st.get("token"):
        try:
            client.post_json("/api/v1/auth/logout", {}, token=st["token"])
        except Exception:  # noqa: BLE001 —— 登出以本地清理为准
            pass
    st.pop("token", None)
    state_mod.save(st)
    print("已退出登录")


def cmd_library(client, home=None) -> None:
    token = _require_token()
    status, body = client.get("/api/v1/me/entitlements", token=token)
    if status != 200 or not isinstance(body, list):
        detail = (body or {}).get("detail") if isinstance(body, dict) else None
        raise CliError(detail or f"获取清单失败（HTTP {status}）")
    if not body:
        print("（还没有获取任何应用——去商店看看：/store）")
        return
    for row in body:
        activated = row.get("activated_at") or "未激活"
        print(f"{row['app']:<24} v{row['version']:<10} 获取于 {row['acquired_at']}"
              f"  {activated}")


def cmd_run(app_name: str, client, home=None) -> None:
    """完整执行流（T2.12）：acquire→下载验签→激活→执行→上报。"""
    token = _require_token()
    from . import run as run_mod
    from .blocks import BlockExecutionError
    from .browser import BrowserUnavailable
    from .pkg import PkgError

    try:
        result = run_mod.app_run(app_name, client, token)
    except BrowserUnavailable as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(3) from exc
    except (run_mod.RunFlowError, PkgError, BlockExecutionError) as exc:
        raise CliError(str(exc)) from exc
    print_run_result(app_name, result)


def print_run_result(app_name: str, result: dict) -> None:
    for step in result["steps"]:
        mark = "✓" if step.get("ok") else "✗"
        extra = step.get("failure_class") or ""
        print(f"  {mark} 步骤 {step['index'] + 1}：{step['block']} {extra}")
    if result["ok"]:
        print(f"运行成功：{app_name}")
        for block, out in result["context"].items():
            if out:
                print(f"  输出（{block}）：{out}")
        if result.get("report_queued"):
            print("  注意：结果上报暂存本地（网络恢复后下次运行自动补报）")
    else:
        print(f"运行失败：{app_name}")
        raise SystemExit(1)
    if result.get("first_run"):
        print("  （本次为首跑，已计入应用成功率统计）")


def main(argv: list[str] | None = None) -> int:
    import argparse

    from .client import Client, ClientError

    parser = argparse.ArgumentParser(
        prog="forge-runner", description="Forge 买家运行器（MS-2）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_login = sub.add_parser("login", help="登录买家账号")
    p_login.add_argument("email")
    p_login.add_argument("--password", default=None,
                         help="缺省交互式输入（不回显）")
    sub.add_parser("logout", help="退出登录")
    sub.add_parser("library", help="我的应用清单")
    p_run = sub.add_parser("run", help="运行一个已获取的应用")
    p_run.add_argument("app_name")

    args = parser.parse_args(argv)
    client = Client()
    try:
        if args.cmd == "login":
            cmd_login(args.email, args.password, client)
        elif args.cmd == "logout":
            cmd_logout(client)
        elif args.cmd == "library":
            cmd_library(client)
        elif args.cmd == "run":
            cmd_run(args.app_name, client)
    except CliError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except ClientError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0
