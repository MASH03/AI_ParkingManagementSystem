from app.extensions import db
from app.models import AIRecommendation, FactoryRun
from app.services.ai.schemas import (
    Finding,
    OperationsAnalysis,
    Priority,
    PriorityIssue,
    Recommendation,
    RecommendationBatch,
    TrafficStatus,
)


class FakeProvider:
    def generate(self, *, instructions, payload, schema):
        if schema is OperationsAnalysis:
            return OperationsAnalysis(
                traffic_status=TrafficStatus.normal,
                congested_zones=[],
                facility_concerns=[],
                maintenance_patterns=[],
                incident_patterns=[],
                feedback_patterns=[],
                reservation_patterns=[],
                priority_issues=[
                    PriorityIssue(title="Review entrance flow", priority=Priority.medium, reason="Entry totals require routine review.")
                ],
                data_gaps=[],
                summary="Operations are within the supplied normal range.",
            )
        return RecommendationBatch(
            needs_additional_analysis=False,
            recommendations=[
                Recommendation(
                    title="Review entrance workflow",
                    category="Visitor Management",
                    priority=Priority.medium,
                    priority_reason="Current visitor totals merit routine review.",
                    reason="The supplied aggregate includes today's entry total.",
                    recommended_action="Review staffing before the next operating period.",
                    related_zone="Main Entrance",
                )
            ],
            summary="One evidence-based recommendation generated.",
        )


class FailingRecommendationProvider(FakeProvider):
    def generate(self, *, instructions, payload, schema):
        if schema is RecommendationBatch:
            raise RuntimeError("simulated provider failure")
        return super().generate(instructions=instructions, payload=payload, schema=schema)


class FeedbackLoopProvider(FakeProvider):
    def __init__(self):
        self.recommendation_calls = 0

    def generate(self, *, instructions, payload, schema):
        if schema is RecommendationBatch:
            self.recommendation_calls += 1
            if self.recommendation_calls == 1:
                return RecommendationBatch(
                    needs_additional_analysis=True,
                    additional_analysis_request="Check whether any supplied zone is above 80 percent capacity.",
                    recommendations=[],
                    summary="A focused capacity check is required.",
                )
        return super().generate(instructions=instructions, payload=payload, schema=schema)


def test_agent_schema_rejects_invalid_priority():
    try:
        Recommendation(
            title="Test recommendation",
            category="Safety",
            priority="Unsupported",
            priority_reason="Test reason",
            reason="Test evidence",
            recommended_action="Test action",
        )
    except Exception as exc:
        assert "priority" in str(exc)
    else:
        raise AssertionError("Invalid priority was accepted")


def test_factory_orchestration_and_approval(app, admin_client):
    app.config["AI_PROVIDER"] = FakeProvider()
    response = admin_client.post("/api/factory/start", json={})
    assert response.status_code == 202
    run = response.get_json()["run"]
    assert run["status"] == "Completed"
    assert run["recommendation_count"] == 1
    recommendation = admin_client.get("/api/recommendations").get_json()["items"][0]
    approved = admin_client.post(
        f"/api/recommendations/{recommendation['id']}/approve",
        json={"admin_note": "Reviewed by administrator."},
    )
    assert approved.get_json()["item"]["status"] == "Approved"
    implemented = admin_client.post(
        f"/api/recommendations/{recommendation['id']}/implement",
        json={"admin_note": "Completed after field verification."},
    )
    assert implemented.get_json()["item"]["status"] == "Implemented"


def test_agent_two_failure_is_partial_and_retryable(app, admin_client):
    app.config["AI_PROVIDER"] = FailingRecommendationProvider()
    response = admin_client.post("/api/factory/start", json={})
    run = response.get_json()["run"]
    assert run["status"] == "Partial Failure"
    app.config["AI_PROVIDER"] = FakeProvider()
    retry = admin_client.post(f"/api/factory/{run['id']}/retry-agent-2", json={})
    assert retry.status_code == 202
    assert retry.get_json()["run"]["status"] == "Completed"


def test_feedback_loop_runs_at_most_one_additional_iteration(app, admin_client):
    provider = FeedbackLoopProvider()
    app.config["AI_PROVIDER"] = provider
    response = admin_client.post("/api/factory/start", json={})
    run = response.get_json()["run"]
    assert run["status"] == "Completed"
    assert run["iteration_count"] == 2
    assert len(run["agents"]) == 4
    assert provider.recommendation_calls == 2


def test_openai_provider_fallback_on_failure(app, monkeypatch):
    from unittest.mock import MagicMock
    from app.services.ai.provider import OpenAIProvider

    with app.app_context():
        app.config["OPENAI_API_KEY"] = "sk-fake-primary"
        app.config["OPENAI_BACKUP_API_KEY"] = "sk-fake-backup"
        app.config["OPENAI_MODEL"] = "gpt-5-mini"
        app.config["OPENAI_FALLBACK_MODEL"] = "gpt-4o-mini"

        provider = OpenAIProvider()
        assert len(provider.candidates) == 4  # 2 keys x 2 models

        call_history = []
        fake_parsed = MagicMock()

        def mock_parse(model, **kwargs):
            call_history.append(model)
            if len(call_history) == 1:
                raise RuntimeError("Rate limit or token quota exceeded")
            mock_response = MagicMock()
            mock_response.output_parsed = fake_parsed
            return mock_response

        for candidate in provider.candidates:
            monkeypatch.setattr(candidate["client"].responses, "parse", mock_parse)

        result = provider.generate(
            instructions="test",
            payload={"sample": "data"},
            schema=OperationsAnalysis,
        )
        assert result == fake_parsed
        assert len(call_history) == 2
        assert call_history[0] == "gpt-5-mini"
        assert call_history[1] == "gpt-4o-mini"


def test_openrouter_provider_fallback_support(app, monkeypatch):
    from unittest.mock import MagicMock
    from app.services.ai.provider import OpenAIProvider

    with app.app_context():
        app.config["OPENAI_API_KEY"] = "sk-fake-openai"
        app.config["OPENAI_BACKUP_API_KEY"] = ""
        app.config["OPENROUTER_API_KEY"] = "sk-fake-openrouter"
        app.config["OPENROUTER_MODEL"] = "openai/gpt-4o-mini"
        app.config["OPENROUTER_FALLBACK_MODEL"] = "google/gemini-2.0-flash-001"

        provider = OpenAIProvider()
        openrouter_candidates = [c for c in provider.candidates if "OpenRouter" in c["label"]]
        assert len(openrouter_candidates) == 2

        fake_parsed = MagicMock()
        mock_chat_response = MagicMock()
        mock_chat_response.choices = [MagicMock(message=MagicMock(parsed=fake_parsed))]

        # OpenAI direct fails, OpenRouter succeeds
        monkeypatch.setattr(
            provider.candidates[0]["client"].responses,
            "parse",
            MagicMock(side_effect=RuntimeError("OpenAI out of quota")),
        )
        monkeypatch.setattr(
            provider.candidates[1]["client"].responses,
            "parse",
            MagicMock(side_effect=RuntimeError("OpenAI out of quota")),
        )
        monkeypatch.setattr(
            openrouter_candidates[0]["client"].beta.chat.completions,
            "parse",
            MagicMock(return_value=mock_chat_response),
        )

        result = provider.generate(
            instructions="test",
            payload={"sample": "data"},
            schema=OperationsAnalysis,
        )
        assert result == fake_parsed


