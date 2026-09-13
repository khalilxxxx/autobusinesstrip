import json
from pathlib import Path

import pytest

import lifecycle_control


def private_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def test_runtime_rejects_old_dify_app_and_wrong_gateway_upstream(tmp_path):
    private_json(tmp_path / "lifecycle-dify.json", {
        "app_id": lifecycle_control.OLD_APP_ID,
        "expected_app_name": lifecycle_control.APP_NAME,
        "api_key": "app-new-secret", "base_url": "https://api.dify.ai/v1", "inputs": {},
    })
    private_json(tmp_path / "lifecycle-bridge.json", {
        "app_id": lifecycle_control.OLD_APP_ID, "token": "bridge-new-secret",
        "public_url": "https://new.trycloudflare.com", "upstream_url": "http://127.0.0.1:8876",
    })
    with pytest.raises(RuntimeError, match="旧 Dify 应用"):
        lifecycle_control.load_runtime_config(tmp_path)

    dify = json.loads((tmp_path / "lifecycle-dify.json").read_text())
    dify["app_id"] = "new-app-id"
    private_json(tmp_path / "lifecycle-dify.json", dify)
    bridge = json.loads((tmp_path / "lifecycle-bridge.json").read_text())
    bridge.update(app_id="new-app-id", upstream_url="http://127.0.0.1:8766")
    private_json(tmp_path / "lifecycle-bridge.json", bridge)
    with pytest.raises(RuntimeError, match="8876"):
        lifecycle_control.load_runtime_config(tmp_path)


def test_fresh_runtime_config_allows_tunnel_to_fill_initial_public_url(tmp_path):
    private_json(tmp_path / "lifecycle-dify.json", {
        "app_id": "new-app-id", "expected_app_name": lifecycle_control.APP_NAME,
        "api_key": "app-new-secret", "base_url": "https://api.dify.ai/v1", "inputs": {},
    })
    private_json(tmp_path / "lifecycle-bridge.json", {
        "app_id": "new-app-id", "token": "bridge-new-secret",
        "public_url": "", "upstream_url": "http://127.0.0.1:8876",
    })

    _, bridge = lifecycle_control.load_runtime_config(tmp_path)

    assert bridge["public_url"] == ""


def test_runtime_dsl_is_private_and_only_fills_gateway_environment(tmp_path):
    source = tmp_path / "source.yml"
    source.write_text("""app:\n  name: 差旅助手-单据生命周期-V2\nworkflow:\n  environment_variables:\n  - name: DEMO_API_BASE_URL\n    value_type: string\n    value: ''\n  - name: DEMO_API_TOKEN\n    value_type: secret\n    value: ''\n""", encoding="utf-8")
    output = tmp_path / "runtime.yml"
    lifecycle_control.write_runtime_dsl(source, output, "https://new.trycloudflare.com", "bridge-secret")

    text = output.read_text(encoding="utf-8")
    assert "https://new.trycloudflare.com" in text
    assert "bridge-secret" in text
    assert "app-new-secret" not in text
    assert output.stat().st_mode & 0o777 == 0o600


def test_server_and_gateway_commands_are_single_worker_and_use_lifecycle_paths(tmp_path):
    base = tmp_path / "模拟差旅系统"
    python = base / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    commands = lifecycle_control.runtime_commands(base, python)

    assert commands["server"][-2:] == ["--workers", "1"]
    assert "8876" in commands["server"]
    assert commands["gateway"][-1] == "8877"
    env = lifecycle_control.runtime_environment(base)
    assert env["MOCK_TRAVEL_DB"] == str(base / "data/lifecycle.sqlite3")
    assert env["MOCK_TRAVEL_DIFY_CONFIG"] == str(base / ".local/lifecycle-dify.json")
    assert env["MOCK_TRAVEL_BRIDGE_CONFIG"] == str(base / ".local/lifecycle-bridge.json")


@pytest.mark.parametrize("occupied_port", [lifecycle_control.SERVER_PORT, lifecycle_control.GATEWAY_PORT])
def test_start_checks_both_ports_before_starting_or_reusing_tunnel(tmp_path, monkeypatch, occupied_port):
    base = tmp_path / "模拟差旅系统"
    (base / ".venv/bin").mkdir(parents=True)
    (base / ".venv/bin/python").write_text("", encoding="utf-8")
    (base / "frontend/dist").mkdir(parents=True)
    (base / "frontend/dist/index.html").write_text("", encoding="utf-8")
    source = tmp_path / "source.yml"
    source.write_text("app: {}", encoding="utf-8")
    tunnel_calls = []

    monkeypatch.setattr(lifecycle_control, "BASE", base)
    monkeypatch.setattr(lifecycle_control, "LOCAL", base / ".local")
    monkeypatch.setattr(lifecycle_control, "STATE", base / ".local/lifecycle-processes.json")
    monkeypatch.setattr(lifecycle_control, "BRIDGE", base / ".local/lifecycle-bridge.json")
    monkeypatch.setattr(lifecycle_control, "SOURCE_DSL", source)
    monkeypatch.setattr(lifecycle_control, "load_runtime_config", lambda: ({}, {"public_url": ""}))
    monkeypatch.setattr(lifecycle_control, "occupied", lambda port: port == occupied_port)
    monkeypatch.setattr(lifecycle_control, "ensure_tunnel", lambda state, bridge: tunnel_calls.append(True) or bridge)

    with pytest.raises(RuntimeError, match=str(occupied_port)):
        lifecycle_control.start({})

    assert tunnel_calls == []


def test_port_preflight_accepts_ports_owned_by_matching_recorded_processes(monkeypatch):
    state = {"server": {"pid": 1}, "gateway": {"pid": 2}}
    monkeypatch.setattr(lifecycle_control, "running", lambda entry: entry in state.values())
    monkeypatch.setattr(lifecycle_control, "occupied", lambda _port: True)

    lifecycle_control.preflight_ports(state)
