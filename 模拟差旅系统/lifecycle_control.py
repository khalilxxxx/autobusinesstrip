"""管理生命周期 V2 的独立本地服务、网关与隧道；只操作本工作树记录的进程。"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import yaml

BASE = Path(__file__).resolve().parent
REPO = BASE.parent
LOCAL = BASE / ".local"
STATE = LOCAL / "lifecycle-processes.json"
DIFY = LOCAL / "lifecycle-dify.json"
BRIDGE = LOCAL / "lifecycle-bridge.json"
RUNTIME_DSL = LOCAL / "差旅助手-单据生命周期-V2-本机运行.yml"
SOURCE_DSL = REPO / "交付物" / "单据生命周期_Dify" / "差旅助手-单据生命周期-V2-可导入.yml"
APP_NAME = "差旅助手-单据生命周期-V2"
OLD_APP_ID = "9f14a8eb-d849-41cb-8dbd-b66829b17edb"
SERVER_PORT = 8876
GATEWAY_PORT = 8877
HTTP = build_opener(ProxyHandler({}))


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RuntimeError(f"无法读取独立配置：{path}") from None
    if not isinstance(value, dict):
        raise RuntimeError(f"独立配置必须是 JSON 对象：{path}")
    return value


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary.replace(path)
    os.chmod(path, 0o600)


def _private(path):
    if Path(path).stat().st_mode & 0o077:
        raise RuntimeError(f"私密配置权限过宽，请执行 chmod 600：{path}")


def _https_url(value, label):
    try:
        parsed = urlsplit(value)
        parsed.port
    except (TypeError, ValueError):
        raise RuntimeError(f"{label} 格式无效。") from None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError(f"{label} 必须是无账号、查询参数和片段的 HTTPS 地址。")


def load_runtime_config(local=LOCAL):
    local = Path(local)
    dify_path, bridge_path = local / "lifecycle-dify.json", local / "lifecycle-bridge.json"
    dify, bridge = read_json(dify_path), read_json(bridge_path)
    _private(dify_path); _private(bridge_path)
    app_id = dify.get("app_id")
    if not isinstance(app_id, str) or not app_id.strip():
        raise RuntimeError("lifecycle-dify.json 缺少新 app_id。")
    if app_id == OLD_APP_ID or bridge.get("app_id") == OLD_APP_ID:
        raise RuntimeError("拒绝使用旧 Dify 应用 ID；生命周期 V2 必须绑定独立新应用。")
    if dify.get("expected_app_name") != APP_NAME:
        raise RuntimeError(f"新 Dify 应用名必须是「{APP_NAME}」。")
    if bridge.get("app_id") != app_id:
        raise RuntimeError("Dify 与网关配置的 app_id 不一致。")
    if not isinstance(dify.get("api_key"), str) or not dify["api_key"].strip():
        raise RuntimeError("lifecycle-dify.json 尚未填写新应用 api_key。")
    token = bridge.get("token")
    if not isinstance(token, str) or not token or not token.isascii() or not token.isprintable():
        raise RuntimeError("lifecycle-bridge.json 缺少有效独立 token。")
    if bridge.get("upstream_url") != f"http://127.0.0.1:{SERVER_PORT}":
        raise RuntimeError(f"生命周期网关 upstream_url 必须指向 127.0.0.1:{SERVER_PORT}。")
    public_url = bridge.get("public_url", "")
    if not isinstance(public_url, str):
        raise RuntimeError("生命周期隧道 public_url 格式无效。")
    if public_url:
        _https_url(public_url, "生命周期隧道 public_url")
    return dify, bridge


def write_runtime_dsl(source, output, public_url, token):
    source, output = Path(source), Path(output)
    if not source.is_file():
        raise RuntimeError(f"找不到生命周期 V2 可导入 DSL：{source}")
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raise RuntimeError("生命周期 V2 DSL 不是有效 YAML。") from None
    if document.get("app", {}).get("name") != APP_NAME:
        raise RuntimeError("DSL 应用名不符合生命周期 V2 约定。")
    variables = document.get("workflow", {}).get("environment_variables")
    if not isinstance(variables, list):
        raise RuntimeError("DSL 缺少环境变量定义。")
    values = {"DEMO_API_BASE_URL": public_url, "DEMO_API_TOKEN": token}
    seen = set()
    for variable in variables:
        name = variable.get("name") if isinstance(variable, dict) else None
        if name in values:
            variable["value"] = values[name]
            seen.add(name)
    if seen != set(values):
        raise RuntimeError("DSL 缺少网关地址或 token 环境变量。")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    with open(temporary, "w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        yaml.safe_dump(document, stream, allow_unicode=True, sort_keys=False, width=1000)
    temporary.replace(output)
    os.chmod(output, 0o600)


def runtime_environment(base=BASE):
    base = Path(base)
    return {
        **os.environ,
        "MOCK_TRAVEL_DB": str(base / "data/lifecycle.sqlite3"),
        "MOCK_TRAVEL_DIFY_CONFIG": str(base / ".local/lifecycle-dify.json"),
        "MOCK_TRAVEL_BRIDGE_CONFIG": str(base / ".local/lifecycle-bridge.json"),
    }


def runtime_commands(base=BASE, python=None):
    base = Path(base); python = Path(python or base / ".venv/bin/python")
    return {
        "server": [str(python), "-m", "uvicorn", "mock_travel.app:create_app", "--factory", "--host", "127.0.0.1",
                   "--port", str(SERVER_PORT), "--no-access-log", "--workers", "1"],
        "gateway": [str(python), "-m", "uvicorn", "mock_travel.gateway:create_gateway", "--factory", "--host", "127.0.0.1",
                    "--no-access-log", "--port", str(GATEWAY_PORT)],
    }


def identity(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart=", "-o", "args="], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def running(entry):
    try:
        return bool(entry and entry.get("identity") and identity(int(entry["pid"])) == entry["identity"])
    except (TypeError, ValueError):
        return False


def occupied(port):
    with socket.socket() as client:
        client.settimeout(0.3)
        return client.connect_ex(("127.0.0.1", port)) == 0


def preflight_ports(state):
    for name, port in (("server", SERVER_PORT), ("gateway", GATEWAY_PORT)):
        if not running(state.get(name)) and occupied(port):
            raise RuntimeError(f"端口 {port} 已被非本控制器进程占用；不会启动隧道或停止该进程，请先核对。")


def spawn(name, command, state, *, port=None, env=None):
    if running(state.get(name)):
        return False
    if port and occupied(port):
        raise RuntimeError(f"端口 {port} 已被非本控制器进程占用；不会停止该进程，请先核对。")
    log_path = LOCAL / f"lifecycle-{name}.log"
    with open(log_path, "ab", buffering=0) as log:
        os.chmod(log_path, 0o600)
        child = subprocess.Popen(command, cwd=BASE, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    time.sleep(0.15)
    process_identity = identity(child.pid)
    if child.poll() is not None or not process_identity:
        raise RuntimeError(f"{name} 未能启动，请检查 {log_path}。")
    state[name] = {"pid": child.pid, "identity": process_identity, "startedAt": time.time()}
    save_json(STATE, state)
    return True


def request_local(path, *, gateway=False):
    port = GATEWAY_PORT if gateway else SERVER_PORT
    headers = {"Authorization": "Bearer " + read_json(BRIDGE)["token"]} if gateway else {}
    with HTTP.open(Request(f"http://127.0.0.1:{port}{path}", headers=headers), timeout=3) as response:
        return json.load(response)


def wait_ready(name, path, state, *, gateway=False):
    for _ in range(40):
        if not running(state.get(name)):
            break
        try:
            request_local(path, gateway=gateway); return
        except (URLError, TimeoutError, ValueError):
            time.sleep(0.2)
    raise RuntimeError(f"{name} 尚未就绪，请检查 .local/lifecycle-{name}.log。")


def ensure_tunnel(state, bridge):
    binary = LOCAL / "bin/cloudflared"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError("缺少本工作树可执行的 .local/bin/cloudflared。")
    if running(state.get("tunnel")):
        expected = f"--url http://127.0.0.1:{GATEWAY_PORT}"
        if str(binary) not in state["tunnel"]["identity"] or expected not in state["tunnel"]["identity"]:
            raise RuntimeError("现有 tunnel 身份与生命周期 V2 不符，拒绝沿用。")
        if not bridge.get("public_url"):
            raise RuntimeError("现有 tunnel 缺少已记录的公网地址；请核对生命周期私密配置。")
        _https_url(bridge["public_url"], "生命周期隧道 public_url")
        return bridge
    bridge["public_url"] = ""
    save_json(BRIDGE, bridge)
    log_path = LOCAL / "lifecycle-tunnel.log"
    log_path.write_text("", encoding="utf-8"); os.chmod(log_path, 0o600)
    spawn("tunnel", [str(binary), "tunnel", "--url", f"http://127.0.0.1:{GATEWAY_PORT}",
                     "--no-autoupdate", "--protocol", "http2"], state)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline and running(state.get("tunnel")):
        match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", log_path.read_text(encoding="utf-8", errors="replace"))
        if match:
            bridge["public_url"] = match.group(0); save_json(BRIDGE, bridge); return bridge
        time.sleep(0.5)
    raise RuntimeError("生命周期隧道未取得公网地址，请检查 .local/lifecycle-tunnel.log。")


def start(state):
    python = BASE / ".venv/bin/python"
    if not python.is_file():
        raise RuntimeError("缺少本工作树 .venv，请先运行 ./run-lifecycle.sh 安装依赖。")
    if not (BASE / "frontend/dist/index.html").is_file():
        raise RuntimeError("缺少本工作树 frontend/dist，请先构建前端。")
    if not SOURCE_DSL.is_file():
        raise RuntimeError("缺少生命周期 V2 DSL 源文件。")
    preflight_ports(state)
    dify, bridge = load_runtime_config()
    bridge = ensure_tunnel(state, bridge)
    commands, env = runtime_commands(BASE, python), runtime_environment(BASE)
    spawn("server", commands["server"], state, port=SERVER_PORT, env=env)
    wait_ready("server", "/health", state)
    spawn("gateway", commands["gateway"], state, port=GATEWAY_PORT, env=env)
    wait_ready("gateway", "/workflow/v1/lifecycle/context?user=lifecycle-runtime-check", state, gateway=True)
    write_runtime_dsl(SOURCE_DSL, RUNTIME_DSL, bridge["public_url"], bridge["token"])
    show_status(state, dify, bridge)


def stop(state):
    for name in ("gateway", "server", "tunnel"):
        entry = state.get(name)
        if running(entry):
            os.kill(entry["pid"], signal.SIGTERM)
            deadline = time.monotonic() + 10
            while running(entry) and time.monotonic() < deadline:
                time.sleep(0.1)
            if running(entry):
                raise RuntimeError(f"{name} 尚未退出；保留身份记录，未强制终止。")
            print(f"已停止生命周期 {name}。")
        state.pop(name, None)
    save_json(STATE, state)


def show_status(state, dify=None, bridge=None):
    print(f"生命周期助手：http://127.0.0.1:{SERVER_PORT}/assistant（{'运行中' if running(state.get('server')) else '未运行'}）")
    print(f"模拟控制台：http://127.0.0.1:{SERVER_PORT}/simulator")
    print(f"生命周期网关：127.0.0.1:{GATEWAY_PORT}（{'运行中' if running(state.get('gateway')) else '未运行'}）")
    print(f"独立隧道：{'运行中' if running(state.get('tunnel')) else '未运行'}")
    if bridge and bridge.get("public_url"):
        print("Dify 网关地址：" + bridge["public_url"])
    if dify:
        print("Dify 应用：" + dify.get("expected_app_name", "未配置"))
    print("进程身份记录：" + str(STATE))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    args = parser.parse_args(argv)
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    lock_path = LOCAL / "lifecycle-processes.lock"
    with open(lock_path, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = read_json(STATE) if STATE.exists() else {}
            if args.action == "start": start(state)
            elif args.action == "stop": stop(state)
            else:
                dify, bridge = load_runtime_config(); show_status(state, dify, bridge)
        except (RuntimeError, OSError, ValueError) as error:
            print(str(error), file=sys.stderr); return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
