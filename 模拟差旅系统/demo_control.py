"""启动、检查和停止本 Demo 自己管理的进程；不停止未知的端口占用者。"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

BASE = Path(__file__).resolve().parent
LOCAL = BASE / ".local"
STATE = LOCAL / "processes.json"
BRIDGE = LOCAL / "bridge.json"
LOCAL_HTTP = build_opener(ProxyHandler({}))


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save_json(path, data):
    temporary = path.with_suffix(".tmp")
    with open(temporary, "w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary.replace(path)


def identity(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart=", "-o", "args="],
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def running(entry):
    return bool(entry and entry.get("identity") and identity(entry["pid"]) == entry["identity"])


def occupied(port):
    with socket.socket() as client:
        client.settimeout(0.3)
        return client.connect_ex(("127.0.0.1", port)) == 0


def spawn(name, command, state, port=None):
    if running(state.get(name)):
        return False
    if port and occupied(port):
        raise RuntimeError(f"端口 {port} 已被其他进程占用，请先检查并自行停止原服务。")
    log_path = LOCAL / f"{name}.log"
    with open(log_path, "ab", buffering=0) as log:
        os.chmod(log_path, 0o600)
        child = subprocess.Popen(command, cwd=BASE, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, start_new_session=True)
    time.sleep(0.15)
    process_identity = identity(child.pid)
    if child.poll() is not None or not process_identity:
        raise RuntimeError(f"{name} 未能启动，请检查 {log_path.name}。")
    state[name] = {"pid": child.pid, "identity": process_identity, "startedAt": time.time()}
    save_json(STATE, state)
    return True


def get_local(path, *, gateway=False):
    port = 8767 if gateway else 8766
    headers = {"Authorization": "Bearer " + read_json(BRIDGE)["token"]} if gateway else {}
    with LOCAL_HTTP.open(Request(f"http://127.0.0.1:{port}{path}", headers=headers), timeout=3) as response:
        return json.load(response)


def wait_ready(name, path, state, *, gateway=False):
    for _ in range(40):
        if not running(state.get(name)):
            break
        try:
            get_local(path, gateway=gateway)
            return
        except (URLError, TimeoutError, ValueError):
            time.sleep(0.2)
    raise RuntimeError(f"{name} 尚未就绪，请检查 .local/{name}.log。")


def start(state, with_bridge):
    python = BASE / ".venv" / "bin" / "python"
    if not python.is_file():
        raise RuntimeError("请先执行 ./run.sh 完成 Python 依赖安装。")
    if not (BASE / "frontend/dist/index.html").is_file():
        raise RuntimeError("请先在 frontend 目录执行 npm ci 和 npm run build。")
    config = read_json(BRIDGE)
    if not config.get("token"):
        config.update(token=secrets.token_urlsafe(36), public_url="", upstream_url="http://127.0.0.1:8766")
        save_json(BRIDGE, config)
    spawn("server", [str(python), "-m", "uvicorn", "mock_travel.app:create_app", "--factory",
                     "--host", "127.0.0.1", "--port", "8766", "--no-access-log"], state, 8766)
    wait_ready("server", "/health", state)
    spawn("gateway", [str(python), "-m", "mock_travel.gateway"], state, 8767)
    wait_ready("gateway", "/workflow/v1/context", state, gateway=True)
    if with_bridge:
        binary = LOCAL / "bin/cloudflared"
        if not binary.is_file():
            raise RuntimeError("缺少 cloudflared。请按完整 Demo 说明安装官方工具后重试。")
        if not running(state.get("tunnel")):
            # 每次新通道单独清空日志，避免读到上次已经失效的 URL。
            (LOCAL / "tunnel.log").write_text("", encoding="utf-8")
            config.update(public_url="", configured_at="")
            save_json(BRIDGE, config)
            spawn("tunnel", [str(binary), "tunnel", "--url", "http://127.0.0.1:8767",
                             "--no-autoupdate", "--protocol", "http2"], state)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if not running(state.get("tunnel")):
                break
            log = (LOCAL / "tunnel.log").read_text(encoding="utf-8", errors="replace")
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", log)
            if match:
                config = read_json(BRIDGE)
                config["public_url"] = match.group(0)
                save_json(BRIDGE, config)
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("通道尚未取得地址，请检查 .local/tunnel.log，再执行 status。")
        if not read_json(BRIDGE).get("public_url"):
            raise RuntimeError("通道启动失败，请检查 .local/tunnel.log。")
    show_status(state)


def stop(state, only_bridge=False, local_only=False):
    names = ["gateway", "server"] if local_only else (["tunnel"] if only_bridge else ["tunnel", "gateway", "server"])
    for name in names:
        entry = state.get(name)
        if running(entry):
            os.kill(entry["pid"], signal.SIGTERM)
            deadline = time.monotonic() + 10
            while running(entry) and time.monotonic() < deadline:
                time.sleep(0.1)
            if running(entry):
                raise RuntimeError(f"{name} 尚未退出；保留进程记录，请稍后再停止。")
            print(f"已停止 {name}。")
        state.pop(name, None)
    save_json(STATE, state)
    config = read_json(BRIDGE)
    if config and not local_only:
        config.update(public_url="", configured_at="")
        save_json(BRIDGE, config)


def show_status(state):
    for name, label in [("server", "本地页面与接口"), ("gateway", "接口网关"), ("tunnel", "Dify 接口通道")]:
        print(f"{label}：{'运行中' if running(state.get(name)) else '未运行'}")
    if running(state.get("server")):
        print("助手：http://127.0.0.1:8766/assistant")
        print("模拟系统：http://127.0.0.1:8766/simulator")
    config = read_json(BRIDGE)
    if running(state.get("tunnel")) and config.get("public_url"):
        print("Dify 环境变量 DEMO_API_BASE_URL：" + config["public_url"])
        print("通道重启后地址会改变；需同步此 Dify 变量并重新发布。凭证保存在 .local/bridge.json。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status", "stop-bridge", "restart-local"])
    parser.add_argument("--bridge", action="store_true", help="同时启动只通向接口网关的临时 HTTPS 通道")
    args = parser.parse_args()
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    with open(LOCAL / "processes.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_json(STATE)
        try:
            if args.action == "start":
                start(state, args.bridge)
            elif args.action == "restart-local":
                stop(state, local_only=True)
                start(state, False)
            elif args.action.startswith("stop"):
                stop(state, args.action == "stop-bridge")
            else:
                show_status(state)
        except (RuntimeError, OSError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
