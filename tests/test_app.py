from fastapi.testclient import TestClient
from io import BytesIO
from PIL import Image
from types import SimpleNamespace
from uuid import uuid4

from customer_context_assistant.app import create_app, _apply_direct_visual_reply
from customer_context_assistant.assistant_engine import build_direct_visual_reply
from customer_context_assistant.models import AnalyzeResponse, Hint


def test_health_and_analyze() -> None:
    client = TestClient(create_app())
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert "visual_entries" in health.json()

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
    assert "visual_matches" in payload
    assert payload["local_only"] is True
    assert "Codex" in payload["codex_handoff"]


def test_vision_match_endpoint_accepts_image() -> None:
    client = TestClient(create_app())
    image = Image.new("RGB", (64, 48), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    response = client.post(
        "/api/vision/match",
        data={"limit": "3"},
        files={"file": ("section.png", buffer.getvalue(), "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "matches" in payload
    assert "visual_entries" in payload
    assert "图库视觉指纹" in payload["rule"]


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
    assert "知识库原文" not in hint["suggested_reply"]


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
    assert "知识库原文" not in hint["suggested_reply"]
    assert "证据原文" not in hint["suggested_reply"]
    assert "品牌结构指纹命中" in hint["interaction_analysis"]


def test_brand_structure_reply_is_customer_ready_not_raw_evidence() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/analyze",
        json={
            "messages": [
                {
                    "id": "m1",
                    "sender": "customer",
                    "text": "这款玻扇只有两个腔体，压线是不可拆卸的，不会注胶也不会刷端面胶，45度拼接缝气密弱，像什么品牌？",
                }
            ]
        },
    )
    assert response.status_code == 200
    reply = response.json()["hints"][0]["suggested_reply"]
    assert "这张先别按品牌名下结论" in reply
    assert "玻扇只有两个腔体" in reply
    assert "压线不可拆" in reply
    assert "知识库原文" not in reply
    assert "证据原文" not in reply
    assert "满天窗" not in reply


def test_general_knowledge_reply_is_not_raw_comment_splice() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/analyze",
        json={
            "messages": [
                {
                    "id": "m1",
                    "sender": "customer",
                    "text": "这个价格有大玻璃，标准双内开结构，胶条隔热条要问什么？",
                }
            ]
        },
    )
    assert response.status_code == 200
    reply = response.json()["hints"][0]["suggested_reply"]
    assert "双内开" in reply
    assert "胶条" in reply
    assert "隔热条" in reply
    assert "参考知识库相似判断" not in reply
    assert "满天窗" not in reply
    assert "作者" not in reply
    assert "赞 回复" not in reply


def test_analysis_summary_does_not_show_raw_comment_noise() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/analyze",
        json={
            "messages": [
                {
                    "id": "m1",
                    "sender": "customer",
                    "text": "两款主框都是四腔体，左边卡面宽一点，右边副框套里面安全性更好，选哪个？",
                }
            ]
        },
    )
    assert response.status_code == 200
    hint = response.json()["hints"][0]
    combined = hint["suggested_reply"] + hint["interaction_analysis"]
    assert "右边" in hint["suggested_reply"] or "副框" in hint["suggested_reply"]
    assert "满天窗" not in combined
    assert "门窗砍价官" not in combined
    assert "作者" not in combined
    assert "赞 回复" not in combined
    assert "湖北 赞" not in combined


def test_direct_visual_reply_uses_matched_comment_before_brand_template() -> None:
    author_replies = [
        "满天窗(帮看门窗结构) 作者 新豪轩的内开窗做的很一般，我记得他主框两个腔体是不能满注胶的，超大玻璃的承重比较差，如果价格是799包含安装并且能参加85折的国补的话是可以选择的，不然就不如一些北方品牌的产品 2025-05-15浙江 1 回复",
        "满天窗(帮看门窗结构) 作者 京港亚结构有吗？ 2025-05-15浙江 赞 回复",
    ]

    reply = build_direct_visual_reply(author_replies, ["新豪轩", "京港亚"])

    assert "主框两个腔体" in reply
    assert "不能满注胶" in reply or "满注胶" in reply
    assert "大玻璃" in reply
    assert "799" not in reply or "报价" in reply
    assert "满天窗" not in reply
    assert "作者" not in reply
    assert "京港亚结构有吗" not in reply


def test_high_score_visual_match_overrides_brand_structure_reply() -> None:
    response = AnalyzeResponse(
        hints=[
            Hint(
                message_id="image-1",
                intent="窗型选择",
                confidence=0.96,
                summary="命中品牌结构",
                interaction_analysis="品牌结构指纹命中：京港亚。",
                suggested_reply="这张先别按品牌名下结论，要从截面结构看。它和知识库里“疑似 京港亚”的结构线索比较接近。",
                matched_entries=[],
            )
        ]
    )
    visual_match = SimpleNamespace(
        score=0.93,
        entry=SimpleNamespace(
            title="图库样本",
            brand_clues=["新豪轩", "京港亚"],
            author_replies=[
                "满天窗(帮看门窗结构) 作者 新豪轩的内开窗做的很一般，我记得他主框两个腔体是不能满注胶的，超大玻璃的承重比较差，如果价格是799包含安装并且能参加85折的国补的话是可以选择的，不然就不如一些北方品牌的产品 2025-05-15浙江 1 回复"
            ],
        ),
    )

    updated = _apply_direct_visual_reply(response, [visual_match])
    reply = updated.hints[0].suggested_reply

    assert "疑似 京港亚" not in reply
    assert "主框两个腔体" in reply
    assert "图库高相似样本直接命中" in updated.hints[0].interaction_analysis
