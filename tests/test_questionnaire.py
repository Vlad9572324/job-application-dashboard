"""Тесты на _parse_questionnaire_rich — фикс M2.

До фикса label_map keyed by input id, lookup by value → для radio
'да/нет' могло отдать "да" вместо реальной метки.
"""
from app.config import CONFIG
from app.questionnaire import (_parse_questionnaire_fields, _parse_questionnaire_rich,
                               get_questionnaire_answer, questionnaire_preset_previews,
                               resolve_questionnaire_option)


def test_saved_preset_answer_follows_applicant_gender(monkeypatch):
    original = "Да, работала с CRM-системами и 1С."
    monkeypatch.setattr(CONFIG, "questionnaire_templates", [
        {"keywords": ["crm"], "answer": original},
        {"keywords": ["особый"], "answer": "Я работала с особой системой."},
    ])

    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "male")
    assert get_questionnaire_answer("Есть опыт с CRM?") == "Да, работал с CRM-системами и 1С."
    assert questionnaire_preset_previews()[original] == "Да, работал с CRM-системами и 1С."

    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "neutral")
    assert get_questionnaire_answer("Есть опыт с CRM?") == "Да, есть опыт работы с CRM-системами и 1С."
    assert get_questionnaire_answer("Особый опыт?") == "Я работала с особой системой."


def test_preset_with_mixed_gender_words_is_fully_inflected(monkeypatch):
    monkeypatch.setattr(CONFIG, "questionnaire_templates", [{
        "keywords": ["о себе"],
        "answer": ("Ответственный и целеустремлённый специалист с опытом работы. "
                   "Быстро обучаюсь, умею работать в команде и самостоятельно. "
                   "Готова к новым задачам и развитию."),
    }])
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "female")
    assert get_questionnaire_answer("Расскажите о себе").startswith("Ответственная и целеустремлённая")
    monkeypatch.setattr(CONFIG, "llm_applicant_gender", "neutral")
    answer = get_questionnaire_answer("Расскажите о себе")
    assert "Готова" not in answer and "Ответственный" not in answer


def test_textarea_extracted():
    html = '''
    <div data-qa="task-question">Расскажите о себе</div>
    <textarea name="task_1_text"></textarea>
    '''
    result = _parse_questionnaire_rich(html)
    assert len(result) == 1
    assert result[0]["field"] == "task_1_text"
    assert result[0]["type"] == "textarea"


def test_radio_yes_no_labels_match_values():
    """Самый частый кейс: yes/no radio."""
    html = '''
    <div data-qa="task-question">Готовы ли вы к командировкам?</div>
    <input type="radio" name="task_2" value="1" id="r_yes">
    <label for="r_yes">Да, готов</label>
    <input type="radio" name="task_2" value="0" id="r_no">
    <label for="r_no">Нет, не готов</label>
    '''
    result = _parse_questionnaire_rich(html)
    assert len(result) == 1
    q = result[0]
    assert q["type"] == "radio"
    assert q["field"] == "task_2"
    labels = {opt["value"]: opt["label"] for opt in q["options"]}
    assert labels == {"1": "Да, готов", "0": "Нет, не готов"}


def test_radio_label_with_id_different_from_value():
    """Регресс-кейс M2: input id="custom_id_X", value="actual_value".
    До фикса label_map keyed by id, options lookup by value → mismatch."""
    html = '''
    <div data-qa="task-question">Опыт в Python?</div>
    <input type="radio" name="task_5" value="junior" id="opt_a_uniq">
    <label for="opt_a_uniq">Junior (до 1 года)</label>
    <input type="radio" name="task_5" value="middle" id="opt_b_uniq">
    <label for="opt_b_uniq">Middle (1-3 года)</label>
    <input type="radio" name="task_5" value="senior" id="opt_c_uniq">
    <label for="opt_c_uniq">Senior (3+)</label>
    '''
    result = _parse_questionnaire_rich(html)
    q = next(r for r in result if r["field"] == "task_5")
    labels = {opt["value"]: opt["label"] for opt in q["options"]}
    assert labels == {
        "junior": "Junior (до 1 года)",
        "middle": "Middle (1-3 года)",
        "senior": "Senior (3+)",
    }, "Labels must align with their actual radio value, not yes/no defaults"


def test_checkbox_extracted():
    html = '''
    <div data-qa="task-question">Какие фреймворки знаете?</div>
    <input type="checkbox" name="task_3" value="django">
    <input type="checkbox" name="task_3" value="flask">
    <input type="checkbox" name="task_3" value="fastapi">
    '''
    result = _parse_questionnaire_rich(html)
    q = next(r for r in result if r["field"] == "task_3")
    assert q["type"] == "checkbox"
    values = [o["value"] for o in q["options"]]
    assert values == ["django", "flask", "fastapi"]


def test_select_extracted():
    html = '''
    <div data-qa="task-question">Гражданство?</div>
    <select name="task_4">
      <option value="RU">Российское</option>
      <option value="BY">Беларусь</option>
    </select>
    '''
    result = _parse_questionnaire_rich(html)
    q = next(r for r in result if r["field"] == "task_4")
    assert q["type"] == "select"
    labels = {o["value"]: o["label"] for o in q["options"]}
    assert labels == {"RU": "Российское", "BY": "Беларусь"}


def test_empty_html_returns_empty_list():
    assert _parse_questionnaire_rich("") == []
    assert _parse_questionnaire_rich("<div>nothing here</div>") == []


def test_nested_labels_and_mixed_question_order():
    """HH wraps radio inputs in labels and can put choice questions before text."""
    html = '''
    <div data-qa="task-question">Какой язык используете?</div>
    <label><input type="radio" name="task_1" value="17">Python</label>
    <label><input type="radio" name="task_1" value="18">Kotlin</label>
    <div data-qa="task-question">Расскажите об опыте</div>
    <textarea name="task_2_text"></textarea>
    <div data-qa="task-question">Какие инструменты знаете?</div>
    <label><input type="checkbox" name="task_3" value="91">Docker</label>
    <label><input type="checkbox" name="task_3" value="92">Kubernetes</label>
    '''
    parsed = _parse_questionnaire_rich(html)
    assert [(q["field"], q["text"]) for q in parsed] == [
        ("task_1", "Какой язык используете?"),
        ("task_2_text", "Расскажите об опыте"),
        ("task_3", "Какие инструменты знаете?"),
    ]
    assert parsed[0]["options"] == [
        {"value": "17", "label": "Python"}, {"value": "18", "label": "Kotlin"}]
    assert parsed[2]["options"][0] == {"value": "91", "label": "Docker"}
    questions, answers = _parse_questionnaire_fields(html)
    assert questions == [q["text"] for q in parsed]
    assert set(answers) == {"task_1", "task_2_text", "task_3"}


def test_llm_choice_can_use_unique_visible_label():
    options = [{"value": "101", "label": "Да"}, {"value": "102", "label": "Нет"}]
    assert resolve_questionnaire_option("нет", options) == "102"
    assert resolve_questionnaire_option("Да.", options) == "101"
    assert resolve_questionnaire_option(["Да", "Нет"], options, multiple=True) == ["101", "102"]
    assert resolve_questionnaire_option("Возможно", options) is None
    ambiguous = [{"value": "1", "label": "Да"}, {"value": "2", "label": "Да"}]
    assert resolve_questionnaire_option("Да", ambiguous) is None
