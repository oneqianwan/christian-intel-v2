import sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')

import urllib.request
import urllib.error
import json
import time
from datetime import datetime

API_BASE = "http://localhost:8000/api"


class AcceptanceTest:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def log(self, msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def call_api(self, method, path, data=None, params=None):
        url = f"{API_BASE}{path}"
        if params:
            url += "?" + "&".join(f"{k}={urllib.request.quote(v)}" for k, v in params.items())
        req = urllib.request.Request(
            url,
            data=json.dumps(data, ensure_ascii=False).encode('utf-8') if data else None,
            headers={'Content-Type': 'application/json; charset=utf-8'},
            method=method
        )
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            return resp.status, json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read()
            return e.code, json.loads(body.decode('utf-8')) if body else {}
        except Exception as e:
            return 0, {"error": str(e)}

    def test_knowledge_lookup(self, query, expected_intent="knowledge_lookup"):
        """测试知识问答路径"""
        conv_status, conv = self.call_api("POST", "/conversations", {"title": f"测试-{query[:10]}"})
        conv_id = conv.get("id", "test")

        # 发送流式请求
        req = urllib.request.Request(
            f"{API_BASE}/chat/stream",
            data=json.dumps({"message": query, "conversation_id": conv_id}, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json; charset=utf-8'},
            method='POST'
        )

        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = resp.read().decode('utf-8')

            # 检查关键事件
            has_route = "route_decided" in data
            has_delivery = "delivery_emitted" in data
            has_done = "event: done" in data
            intent_correct = f'"intent": "{expected_intent}"' in data

            if has_route and has_delivery and has_done and intent_correct:
                self.passed += 1
                self.log(f"✅ 知识问答: '{query[:20]}' | intent={expected_intent}")
                return True
            else:
                self.failed += 1
                self.errors.append(f"知识问答失败: {query} | route={has_route} delivery={has_delivery} done={has_done} intent={intent_correct}")
                self.log(f"❌ 知识问答: '{query[:20]}' | 事件不完整")
                return False

        except Exception as e:
            self.failed += 1
            self.errors.append(f"知识问答异常: {query} | {str(e)}")
            self.log(f"❌ 知识问答: '{query[:20]}' | {str(e)[:60]}")
            return False

    def test_collection_request(self, query, expected_intent="collection_request"):
        """测试采集请求路径"""
        conv_status, conv = self.call_api("POST", "/conversations", {"title": f"采集-{query[:10]}"})
        conv_id = conv.get("id", "test")

        req = urllib.request.Request(
            f"{API_BASE}/chat/stream",
            data=json.dumps({"message": query, "conversation_id": conv_id}, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json; charset=utf-8'},
            method='POST'
        )

        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = resp.read().decode('utf-8')

            has_route = "route_decided" in data
            has_delivery = "delivery_emitted" in data
            has_done = "event: done" in data
            intent_correct = f'"intent": "{expected_intent}"' in data

            if has_route and has_delivery and has_done and intent_correct:
                self.passed += 1
                self.log(f"✅ 采集路由: '{query[:20]}' | intent={expected_intent}")
                return True
            else:
                self.failed += 1
                self.errors.append(f"采集路由失败: {query}")
                self.log(f"❌ 采集路由: '{query[:20]}'")
                return False

        except Exception as e:
            self.failed += 1
            self.errors.append(f"采集路由异常: {query} | {str(e)}")
            self.log(f"❌ 采集路由: '{query[:20]}' | {str(e)[:60]}")
            return False

    def test_collection_task(self):
        """测试采集任务创建和执行"""
        status, result = self.call_api("POST", "/missions", params={"query": "菲律宾验收测试", "country": "菲律宾"})

        if status != 200 or "mission_id" not in result:
            self.failed += 1
            self.errors.append(f"任务创建失败: {status} {result}")
            self.log(f"❌ 任务创建失败")
            return False

        mission_id = result["mission_id"]
        self.log(f"⏳ 任务创建: {mission_id}")

        # 轮询等待完成
        for i in range(30):  # 最多等60秒
            time.sleep(2)
            status, result = self.call_api("GET", f"/missions/{mission_id}")
            if result.get("mission", {}).get("status") in ["done", "failed"]:
                final_status = result["mission"]["status"]
                self.passed += 1
                self.log(f"✅ 任务完成: {mission_id} | status={final_status} | items={result.get('intelligence_count', 0)}")
                return True

        self.failed += 1
        self.errors.append(f"任务超时: {mission_id}")
        self.log(f"❌ 任务超时: {mission_id}")
        return False

    def run(self):
        self.log("=" * 50)
        self.log("开始验收测试")
        self.log("=" * 50)

        # 30次知识问答
        knowledge_queries = [
            "菲律宾有哪些教会", "菲律宾教会联盟", "菲律宾基督教历史",
            "Victory Philippines", "PCEC是什么", "CCF菲律宾",
            "菲律宾福音派", "菲律宾大型教会", "菲律宾教会统计",
            "菲律宾基督教", "菲律宾信仰", "菲律宾宗教",
            "菲律宾神学院", "菲律宾宣教", "菲律宾基督教组织",
            "菲律宾教会网络", "菲律宾基督教动态", "菲律宾基督教新闻",
            "菲律宾差会", "菲律宾圣经",
            "菲律宾有哪些教会联盟", "菲律宾福音派教会", "菲律宾基督教历史",
            "菲律宾教会增长", "菲律宾基督教人口", "菲律宾宗教自由",
            "菲律宾教会合作", "菲律宾基督教媒体", "菲律宾基督教基金会",
            "菲律宾信仰状况"
        ]

        for q in knowledge_queries:
            self.test_knowledge_lookup(q)
            time.sleep(0.3)

        # 10次采集路由
        collection_queries = [
            "菲律宾基督教最新动态", "菲律宾最近有什么新闻",
            "菲律宾教会最新消息", "菲律宾基督教最新情况",
            "采集菲律宾教会动态", "菲律宾近7天新闻",
            "菲律宾近30天动态", "菲律宾基督教近一周",
            "搜集菲律宾教会信息", "菲律宾最新教会活动"
        ]

        for q in collection_queries:
            self.test_collection_request(q)
            time.sleep(0.3)

        # 5次采集任务
        for i in range(5):
            self.test_collection_task()
            time.sleep(1)

        # 总结
        self.log("=" * 50)
        self.log("验收测试完成")
        self.log(f"总计: {self.passed + self.failed} | 通过: {self.passed} | 失败: {self.failed}")
        self.log(f"通过率: {self.passed / (self.passed + self.failed) * 100:.1f}%")

        if self.errors:
            self.log(f"\n失败详情 ({len(self.errors)}条):")
            for e in self.errors[:10]:
                self.log(f"  - {e}")


if __name__ == "__main__":
    test = AcceptanceTest()
    test.run()
