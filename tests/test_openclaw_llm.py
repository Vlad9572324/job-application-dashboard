import json
import subprocess

from app import llm
from app.config import CONFIG, applicant_gender_forms, questionnaire_default_answer


def test_parse_openclaw_json_direct_payload():
    raw = json.dumps({"payloads": [{"text": "ok"}]})
    assert llm._parse_openclaw_json(raw)["payloads"][0]["text"] == "ok"


def test_parse_openclaw_json_with_log_prefix():
    raw = "warning line\n" + json.dumps({"result": {"payloads": [{"text": "ok"}]}}) + "\ntrace"
    assert llm._parse_openclaw_json(raw)["result"]["payloads"][0]["text"] == "ok"


def test_openclaw_command_prefers_path_executable(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda name: "C:/bin/openclaw.cmd" if name == "openclaw" else None)
    assert llm._openclaw_command() == ["C:/bin/openclaw.cmd"]


def test_openclaw_command_falls_back_to_powershell_shim(monkeypatch):
    def fake_which(name):
        if name == "pwsh":
            return "C:/Program Files/PowerShell/7/pwsh.exe"
        return None

    monkeypatch.setattr(llm.shutil, "which", fake_which)
    monkeypatch.setattr(llm.os.path, "expanduser", lambda _: "C:/Users/test")
    monkeypatch.setattr(llm.os.path, "exists", lambda path: path.endswith("openclaw.ps1"))

    cmd = llm._openclaw_command()
    assert cmd[:3] == ["C:/Program Files/PowerShell/7/pwsh.exe", "-NoProfile", "-ExecutionPolicy"]
    assert cmd[-1].endswith("openclaw.ps1")


def test_generate_openclaw_reply_extracts_result_payload(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_openclaw_agent", "main")
    monkeypatch.setattr(CONFIG, "llm_openclaw_model", "")
    monkeypatch.setattr(CONFIG, "llm_openclaw_timeout", 30)
    monkeypatch.setattr(llm, "_openclaw_command", lambda: ["openclaw"])
    monkeypatch.setattr(llm, "_track_usage", lambda account_key, kind: None)

    def fake_run(cmd, **kwargs):
        assert cmd[:4] == ["openclaw", "agent", "--agent", "main"]
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"result": {"payloads": [{"text": "Здравствуйте! Готов созвониться."}]}}),
            stderr="",
        )

    monkeypatch.setattr(llm.subprocess, "run", fake_run)

    result = llm._generate_openclaw_reply(
        [
            {"role": "system", "content": "Отвечай кратко."},
            {"role": "user", "content": "Здравствуйте, удобно созвониться?"},
        ],
        account_key="test",
    )

    # Reply passes _looks_like_direct_answer: ≥12 chars, matches question with an answer marker.
    assert result == "Здравствуйте! Готов созвониться."


def test_generate_openclaw_reply_accepts_plain_text(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_openclaw_agent", "main")
    monkeypatch.setattr(CONFIG, "llm_openclaw_model", "")
    monkeypatch.setattr(CONFIG, "llm_openclaw_timeout", 30)
    monkeypatch.setattr(llm, "_openclaw_command", lambda: ["openclaw"])
    monkeypatch.setattr(llm, "_track_usage", lambda account_key, kind: None)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="Готов обсудить детали.", stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)

    result = llm._generate_openclaw_reply(
        [{"role": "user", "content": "Здравствуйте"}],
        account_key="test",
    )

    assert result == "Готов обсудить детали."


def test_build_openclaw_reply_prompt_compacts_long_inputs():
    messages = [
        {"role": "system", "content": "S" * 8000},
        {"role": "assistant", "content": "A" * 3000},
        {"role": "user", "content": "U1" * 2500},
        {"role": "assistant", "content": "B" * 3000},
        {"role": "user", "content": "U2" * 2500},
        {"role": "assistant", "content": "C" * 3000},
        {"role": "user", "content": "U3" * 2500},
    ]

    prompt = llm._build_openclaw_prompt(messages, "Тестовое интро.", "test")

    assert len(prompt) <= llm._OPENCLAW_PROMPT_MAX_CHARS
    assert "Сообщение работодателя:" in prompt
    assert "[conversation]" in prompt
    assert "...[truncated]..." in prompt


def test_generate_openclaw_reply_uses_compacted_prompt(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_openclaw_agent", "main")
    monkeypatch.setattr(CONFIG, "llm_openclaw_model", "")
    monkeypatch.setattr(CONFIG, "llm_openclaw_timeout", 30)
    monkeypatch.setattr(llm, "_openclaw_command", lambda: ["openclaw"])
    monkeypatch.setattr(llm, "_track_usage", lambda account_key, kind: None)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["prompt"] = cmd[cmd.index("--message") + 1]
        return subprocess.CompletedProcess(cmd, 0, stdout="Короткий ответ, готов обсудить.", stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)

    result = llm._generate_openclaw_reply(
        [
            {"role": "system", "content": "S" * 9000},
            {"role": "user", "content": "Готовы обсудить условия работы? Пожалуйста, расскажите об опыте."},
        ],
        account_key="test",
    )

    # _looks_like_direct_answer требует минимум 12 символов и answer-marker для question-ответа.
    assert result == "Короткий ответ, готов обсудить."
    assert len(captured["prompt"]) <= llm._OPENCLAW_PROMPT_MAX_CHARS
    assert "...[truncated]..." in captured["prompt"]


def test_applicant_gender_forms_default_female(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "female")
    forms = applicant_gender_forms()
    assert forms["responded"] == "соискательница откликнулась"
    assert forms["consistency"] == "будь последовательна"
    assert forms["default_questionnaire_answer"] == "Готова рассказать подробнее на собеседовании."


def test_applicant_gender_forms_male(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "male")
    forms = applicant_gender_forms()
    assert forms["responded"] == "соискатель откликнулся"
    assert forms["consistency"] == "будь последователен"
    assert forms["default_questionnaire_answer"] == "Готов рассказать подробнее на собеседовании."


def test_questionnaire_default_answer_uses_gender_until_customized(monkeypatch):
    monkeypatch.setattr(CONFIG, "questionnaire_default_answer", "Готова рассказать подробнее на собеседовании.")
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "male")
    assert questionnaire_default_answer() == "Готов рассказать подробнее на собеседовании."

    monkeypatch.setattr(CONFIG, "questionnaire_default_answer", "Мой кастомный ответ.")
    assert questionnaire_default_answer() == "Мой кастомный ответ."


def test_saved_builtin_default_still_follows_gender(monkeypatch):
    monkeypatch.setattr(CONFIG, "questionnaire_default_answer", "Готов рассказать подробнее на собеседовании.")
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "neutral")
    assert questionnaire_default_answer() == "Подробнее расскажу на собеседовании."
