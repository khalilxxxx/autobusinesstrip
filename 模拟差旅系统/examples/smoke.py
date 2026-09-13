"""对已启动服务执行一条成功、一条失败并恢复原场景；保留生成的模拟单。"""
import argparse
import json
from pathlib import Path
from uuid import uuid4

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8766")
    args = parser.parse_args()
    payload = json.loads(Path(__file__).with_name("create-application.json").read_text())
    request_id = "smoke-" + uuid4().hex
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=15, trust_env=False) as client:
        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        assert call("GET", "/health")["status"] == "ok"
        assert call("GET", "/mock/v1/employee-context")["data"]["employee"]["employeeId"] == "DEMO_EMP_001"
        assert len(call("GET", "/mock/v1/transport-options")["data"]) == 21
        cities = call("POST", "/mock/v1/cities/query", files={"filter": (None, "桐庐")})
        assert cities["data"][0]["cityId"] == "330122"
        original = call("GET", "/mock/v1/scenario")["data"]
        try:
            call("PUT", "/mock/v1/scenario", json={"submissionResult": "SUCCESS"})
            headers = {"X-Client-Request-Id": request_id}
            created = call("POST", "/mock/v1/travel/applications", json=payload, headers=headers)
            assert created["code"] == "SUCCESS"
            assert call("POST", "/mock/v1/travel/applications", json=payload, headers=headers) == created
            detail = call("GET", "/mock/v1/travel/applications/" + created["data"]["applicationId"])
            assert detail["data"]["request"] == payload
            receipt = call("GET", "/mock/v1/submissions/" + request_id)
            assert receipt["data"]["result"] == created
            total_before_failure = call("GET", "/mock/v1/travel/applications")["data"]["total"]
            call("PUT", "/mock/v1/scenario", json={"submissionResult": "FAILURE", "failureMessage": "冒烟测试预设失败"})
            failed = call("POST", "/mock/v1/travel/applications", json=payload,
                          headers={"X-Client-Request-Id": request_id + "-failure"})
            assert failed["code"] == "MOCK_SUBMIT_FAILED"
            assert call("GET", "/mock/v1/travel/applications")["data"]["total"] == total_before_failure
            print("真实 HTTP 冒烟通过：上下文、21 项交通、multipart 城市查询、成功创建、重放、详情、回执和预设失败。")
            print("已保留模拟单：" + created["data"]["applicationNo"])
            print("请求标识：" + request_id)
        finally:
            call("PUT", "/mock/v1/scenario", json=original)
            print("已恢复冒烟前的场景配置。")


if __name__ == "__main__":
    main()
