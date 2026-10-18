"""Per-task Gemini tiers (backend/evals): config resolution, the intake cascade trigger, guard prompt trimming."""
from app.agents import guard, intake
from app.config import Settings
from app.llm import task_config
from app.models import Extraction


def test_task_model_defaults_aliases_and_env(monkeypatch):
    s = Settings()
    assert s.task_model("guard") == s.gemini_lite_model
    assert s.task_model("intake") == "gemini-3.1-flash-lite" and s.task_model("intake_escalate") == s.gemini_model
    monkeypatch.setenv("GEMINI_MODEL_COPILOT", "pro")
    monkeypatch.setenv("GEMINI_THINKING_COPILOT", "low")
    monkeypatch.setenv("GEMINI_MAX_OUTPUT_COPILOT", "777")
    s = Settings()
    assert s.task_model("copilot") == s.gemini_pro_model
    cfg = task_config(s, "copilot")
    assert cfg["max_output_tokens"] == 777 and cfg["thinking_config"].thinking_level.value == "LOW"
    monkeypatch.setenv("GEMINI_THINKING_COPILOT", "0")
    assert task_config(Settings(), "copilot")["thinking_config"].thinking_budget == 0
    assert Settings().task_fallback("guard") == "gemini-3.1-flash-lite"


def test_intake_escalates_only_on_missing_or_low_confidence_key_fields():
    good = Extraction(reference_id="612345678901", amount=100, beneficiary={"account_or_vpa": "a@okdemo"},
                      confidence={"reference_id": 0.9, "amount": 0.9, "beneficiary.account_or_vpa": 0.9})
    ev = [{"type": "image"}]
    assert intake.needs_escalation(good, ev) is None
    assert intake.needs_escalation(good.model_copy(update={"reference_id": None}), ev) == "missing:reference_id"
    low = good.model_copy(update={"confidence": {**good.confidence, "amount": 0.4}})
    assert intake.needs_escalation(low, ev) == "low_confidence:amount"
    assert intake.needs_escalation(good.model_copy(update={"reference_id": None}), [{"type": "audio"}]) is None


def test_guard_prompt_drops_route_label_when_gemma_is_off(monkeypatch):
    monkeypatch.setenv("CHAT_LIGHT_MODEL", "")
    from app.config import reset_settings_cache
    reset_settings_cache()
    assert "route" not in guard.system_prompt() and guard.schema().__name__ == "GuardVerdict"
    monkeypatch.setenv("CHAT_LIGHT_MODEL", "gemma-x")
    reset_settings_cache()
    assert '"route"' in guard.system_prompt() and guard.schema().__name__ == "GuardResult"
    reset_settings_cache()
