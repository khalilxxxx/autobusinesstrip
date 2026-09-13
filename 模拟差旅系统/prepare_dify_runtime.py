"""为本机导入生成私密 DSL；公共交付文件始终保持无凭证。"""
import hashlib
import json
import os
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent
SOURCE = BASE.parent / "交付物/完整Demo_Dify接入/差旅申请助手-完整Demo-可导入.yml"
TARGET = BASE / ".local/差旅申请助手-完整Demo-本机运行.yml"


def main():
    config = json.loads((BASE / ".local/bridge.json").read_text(encoding="utf-8"))
    if not config.get("public_url", "").startswith("https://") or not config.get("token"):
        raise SystemExit("请先启动本机接口通道，再生成运行文件。")
    doc = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    values = {"DEMO_API_BASE_URL": config["public_url"].rstrip("/"), "DEMO_API_TOKEN": config["token"]}
    for variable in doc["workflow"]["environment_variables"]:
        variable["value"] = values[variable["name"]]
    with TARGET.open("w", encoding="utf-8") as output:
        os.chmod(TARGET, 0o600)
        yaml.safe_dump(doc, output, allow_unicode=True, sort_keys=False, width=100000)
    print("已生成本机私密运行文件：" + str(TARGET))
    print("公开 DSL SHA256：" + hashlib.sha256(SOURCE.read_bytes()).hexdigest())
    print("该运行文件包含网关凭证，请仅用于当前 Dify 测试应用导入。")


if __name__ == "__main__":
    main()
