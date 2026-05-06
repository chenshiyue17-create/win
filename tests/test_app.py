from fastapi.testclient import TestClient
from io import BytesIO
from PIL import Image
from uuid import uuid4

from customer_context_assistant.app import create_app


def test_health_and_analyze() -> None:
    client = TestClient(create_app())
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    overlay = client.get("/overlay")
    assert overlay.status_code == 200
    assert "门窗售前提示" in overlay.text

    trainer = client.get("/kb-trainer")
    assert trainer.status_code == 200
    assert "门窗知识库训练台" in trainer.text

    search = client.post("/api/kb/search", json={"query": "临街系统窗玻璃隔音", "limit": 3})
    assert search.status_code == 200
    assert search.json()["matches"]

    status = client.get("/api/kb/status")
    assert status.status_code == 200
    assert status.json()["entries"] >= 1

    github_status = client.get("/api/kb/github/status")
    assert github_status.status_code == 200
    assert "archive_dir" in github_status.json()

    learning = client.post(
        "/api/learning/ingest",
        json={"source": "test", "messages": [{"id": "m1", "sender": "customer", "text": "窄边框极简门怎么配系统窗？"}]},
    )
    assert learning.status_code == 200
    assert "candidates" in learning.json()

    interactions = client.get("/api/interactions")
    assert interactions.status_code == 200
    assert "total" in interactions.json()

    export = client.post("/api/interactions/export")
    assert export.status_code == 200
    assert export.json()["output_path"].endswith("interactions_distill.jsonl")

    response = client.post(
        "/api/analyze",
        json={
            "messages": [
                {"id": "m1", "sender": "customer", "text": "临街想换系统窗，玻璃怎么选，隔音好一点"}
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["hints"]
    assert data["hints"][0]["matched_entries"]
    assert data["hints"][0]["interaction_analysis"]


def test_risky_input_gets_warning() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/analyze",
        json={
            "messages": [
                {"id": "m1", "sender": "customer", "text": "你能不能承诺绝对隔音，我的验证码是 123456"}
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["hints"][0]["warnings"]


def test_interaction_analysis_is_separated_from_copyable_reply() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/analyze",
        json={
            "messages": [
                {"id": "m1", "sender": "customer", "text": "别人家便宜很多，你们为什么贵？"}
            ]
        },
    )

    assert response.status_code == 200
    hint = response.json()["hints"][0]
    assert hint["interaction_analysis"]
    assert hint["suggested_reply"]
    assert hint["interaction_analysis"] != hint["suggested_reply"]


def test_analyze_only_uses_latest_customer_message() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/analyze",
        json={
            "messages": [
                {"id": "old", "sender": "customer", "text": "临街想换系统窗，玻璃怎么选"},
                {"id": "reply", "sender": "agent", "text": "先确认楼层和噪音源"},
                {"id": "latest", "sender": "customer", "text": "封阳台大概多少钱一平方"},
            ]
        },
    )

    assert response.status_code == 200
    hints = response.json()["hints"]
    assert len(hints) == 1
    assert hints[0]["message_id"] == "latest"
    assert "封阳台" in hints[0]["suggested_reply"] or hints[0]["matched_entries"]


def test_analyze_records_session_context_without_cross_mixing() -> None:
    client = TestClient(create_app())
    suffix = uuid4().hex[:8]
    session_a = f"测试客户A-{suffix}"
    session_b = f"测试客户B-{suffix}"
    first = client.post(
        "/api/analyze",
        json={
            "session_id": session_a,
            "messages": [{"id": "a1", "sender": "customer", "text": "我家临街，想先看隔音玻璃"}],
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/api/analyze",
        json={
            "session_id": session_a,
            "messages": [{"id": "a2", "sender": "customer", "text": "那三玻两腔有必要吗？"}],
        },
    )
    assert second.status_code == 200
    assert "结合本客户最近" in second.json()["hints"][0]["summary"]

    isolated = client.post(
        "/api/analyze",
        json={
            "session_id": session_b,
            "messages": [{"id": "b1", "sender": "customer", "text": "封阳台多少钱一平方？"}],
        },
    )
    assert isolated.status_code == 200
    assert "结合本客户最近" not in isolated.json()["hints"][0]["summary"]


def test_analyze_can_infer_session_from_nickname() -> None:
    client = TestClient(create_app())
    suffix = uuid4().hex[:8]
    nickname = f"王姐封阳台{suffix}"
    response = client.post(
        "/api/analyze",
        json={
            "session_id": "default",
            "messages": [
                {"id": "name", "sender": "customer", "text": f"昵称：{nickname}"},
                {"id": "latest", "sender": "customer", "text": "系统窗多少钱一平方？"},
            ],
        },
    )

    assert response.status_code == 200
    sessions = client.get("/api/conversations")
    assert sessions.status_code == 200
    assert any(item["id"] == nickname for item in sessions.json())


def test_conversation_api_returns_customer_radar() -> None:
    client = TestClient(create_app())
    suffix = uuid4().hex[:8]
    session_id = f"雷达客户-{suffix}"
    response = client.post(
        "/api/analyze",
        json={
            "session_id": session_id,
            "messages": [{"id": "m1", "sender": "customer", "text": "临街隔音，预算有限，近期想约测量"}],
        },
    )
    assert response.status_code == 200

    sessions = client.get("/api/conversations")
    radar = next(item["radar"] for item in sessions.json() if item["id"] == session_id)

    assert radar["需求清晰"] > 0
    assert radar["预算敏感"] > 0
    assert radar["成交紧迫"] > 0


def test_feed_knowledge_and_vision_image_endpoint() -> None:
    client = TestClient(create_app())
    feed = client.post(
        "/api/kb/feed",
        data={
            "title": "测试截面投喂",
            "content": "玻扇压线可拆、隔热条连续、需要追问五金和胶条品牌。",
            "tags": "截面,压线,隔热条",
            "reply_template": "这款先看压线和隔热条路径，再谈价格。",
            "source_note": "unit-test",
        },
    )
    assert feed.status_code == 200
    assert feed.json()["entry"]["title"] == "测试截面投喂"

    image = Image.new("RGB", (64, 48), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    response = client.post(
        "/api/vision/analyze",
        data={"question": "帮我看这个门窗截面结构怎么样", "session_id": "vision-test"},
        files={"file": ("section.png", buffer.getvalue(), "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis"]["hints"]
    assert payload["upload_path"].endswith(".png")
    assert "knowledge_status" in payload
    assert payload["local_only"] is True
    assert "Codex" in payload["codex_handoff"]


def test_structure_identify_endpoint_returns_brand_candidates() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/structure/identify",
        json={"description": "截面能看到主框两个腔体，不能满注胶，超大玻璃承重比较差"},
    )
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert candidates
    assert candidates[0]["brand"] == "新豪轩"
    assert "主框两个腔体" in candidates[0]["features"]


def test_analyze_uses_specific_structural_reply_from_distilled_knowledge() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/analyze",
        json={
            "messages": [
                {
                    "id": "m1",
                    "sender": "customer",
                    "text": "帮忙看一下这款怎么样？作者说有点像讴铂，内置铰链，外小冷腔，保温隔热会更好一些",
                }
            ]
        },
    )
    assert response.status_code == 200
    hint = response.json()["hints"][0]
    assert "讴铂" in hint["suggested_reply"]
    assert "内置铰链" in hint["suggested_reply"]
    assert "命中的具体判断" in hint["interaction_analysis"]


def test_analyze_uses_specific_brand_price_warranty_reply_from_comments() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/analyze",
        json={
            "messages": [
                {
                    "id": "m1",
                    "sender": "customer",
                    "text": "帮看这款，新豪轩，799一个平方，包含安装费，开扇1280，五金质保一年能买吗",
                }
            ]
        },
    )
    assert response.status_code == 200
    hint = response.json()["hints"][0]
    assert "新豪轩" in hint["suggested_reply"]
    assert "799" in hint["suggested_reply"]
    assert "1280" in hint["suggested_reply"]
    assert "五金质保" in hint["suggested_reply"]


def test_analyze_answers_brand_from_structure_fingerprint() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/analyze",
        json={
            "messages": [
                {
                    "id": "m1",
                    "sender": "customer",
                    "text": "截面看着主框两个腔体，不能满注胶，超大玻璃承重比较差，这个像什么品牌？",
                }
            ]
        },
    )
    assert response.status_code == 200
    hint = response.json()["hints"][0]
    assert "截面结构" in hint["suggested_reply"] or "结构看" in hint["suggested_reply"]
    assert "新豪轩" in hint["suggested_reply"]
    assert "疑似" in hint["suggested_reply"]
    assert "品牌结构指纹命中" in hint["interaction_analysis"]
