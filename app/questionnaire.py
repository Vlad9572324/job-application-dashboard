"""
Questionnaire parsing and template-based answer generation.
"""

import re
import unicodedata

from bs4 import BeautifulSoup

from app.config import CONFIG, questionnaire_default_answer
from app.logging_utils import log_debug


# Exact answers from the built-in UI presets. Older installations have already
# saved these strings in config.json, so matching the whole answer keeps custom
# wording untouched while making those presets follow the applicant's gender.
_PRESET_NEUTRAL = {
    "Да, готова к командировкам.": "Да, могу ездить в командировки.",
    "Да, готова к переработкам при необходимости.": "Да, могу задерживаться при необходимости.",
    "Да, готова работать в выходные при необходимости.": "Да, могу работать в выходные при необходимости.",
    "Ответственный и целеустремлённый специалист с опытом работы. Быстро обучаюсь, умею работать в команде и самостоятельно. Готова к новым задачам и развитию.":
        "Есть опыт работы. Быстро обучаюсь, умею работать в команде и самостоятельно. Интересуют новые задачи и развитие.",
    "Имею опыт работы в данной сфере более 2 лет. Готова рассказать подробнее на собеседовании.":
        "Имею опыт работы в данной сфере более 2 лет. Подробнее расскажу на собеседовании.",
    "От 70 000 рублей. Готова обсудить на собеседовании.": "От 70 000 рублей. Можем обсудить на собеседовании.",
    "Готова приступить в течение 2 недель.": "Могу приступить в течение 2 недель.",
    "Готова рассмотреть предложение.": "Могу рассмотреть предложение.",
    "Да, готова к обучению и развитию.": "Да, интересно обучение и развитие.",
    "Да, готова.": "Да, могу.",
    "Да, работала с CRM-системами и 1С.": "Да, есть опыт работы с CRM-системами и 1С.",
    "Стрессоустойчива, умею работать со сложными клиентами и находить компромисс.":
        "Умею работать со сложными клиентами, сохранять спокойствие и находить компромисс.",
    "Готова приступить в течение недели.": "Могу приступить в течение недели.",
    "Да, готова к обучению.": "Да, могу учиться.",
    "В исключительных случаях готова.": "В исключительных случаях могу.",
    "Уверенный пользователь MS Office: Word, Excel, Outlook.":
        "Уверенно пользуюсь MS Office: Word, Excel, Outlook.",
    "Да, при необходимости готова.": "Да, при необходимости могу.",
    "Да, есть базовые знания. Готова развиваться.": "Да, есть базовые знания. Хочу развиваться.",
    "Да, работала с Google-сервисами, Notion, Trello.":
        "Да, есть опыт работы с Google-сервисами, Notion, Trello.",
    "Да, готова к обучению за счёт компании.": "Да, могу пройти обучение за счёт компании.",
}


def _applicant_gender() -> str:
    value = (getattr(CONFIG, "llm_applicant_gender", "") or "female").strip().lower()
    if value in ("male", "m", "masculine", "мужской"):
        return "male"
    if value in ("neutral", "n", "неважно", "нейтральный"):
        return "neutral"
    return "female"


def questionnaire_preset_previews() -> dict[str, str]:
    """Current-gender display and send text for the original built-in presets."""
    gender = _applicant_gender()
    if gender == "neutral":
        return _PRESET_NEUTRAL
    if gender == "male":
        return {
            original: original.replace("Готова", "Готов").replace("готова", "готов")
                .replace("работала", "работал").replace("Стрессоустойчива", "Стрессоустойчив")
            for original in _PRESET_NEUTRAL
        }
    return {
        original: original.replace("Ответственный и целеустремлённый специалист", "Ответственная и целеустремлённая специалистка")
            .replace("Уверенный пользователь", "Уверенно пользуюсь")
        for original in _PRESET_NEUTRAL
    }


def resolve_questionnaire_template_answer(answer: str) -> str:
    """Inflect only exact built-in preset answers; custom answers stay literal."""
    return questionnaire_preset_previews().get(answer, answer)


def get_questionnaire_answer(question_text: str) -> str:
    """Найти подходящий шаблонный ответ по ключевым словам вопроса."""
    q_lower = question_text.lower()
    for tmpl in CONFIG.questionnaire_templates:
        keywords = tmpl.get("keywords", [])
        if not keywords:
            continue
        if any(kw.lower() in q_lower for kw in keywords):
            return resolve_questionnaire_template_answer(tmpl["answer"])
    return questionnaire_default_answer()


def _parse_questionnaire_fields(html: str) -> tuple:
    """
    Парсит форму опросника. Возвращает (questions, field_answers):
      questions: list of str (тексты вопросов по порядку)
      field_answers: dict {field_name: answer_value} — готовые значения для POST
    Поддерживает textarea, radio, checkbox.
    """
    rich = _parse_questionnaire_rich(html)
    answers = {}
    negative = ("нет", "no", "не готов", "не готова", "не могу")
    for question in rich:
        field, kind = question["field"], question["type"]
        template = get_questionnaire_answer(question["text"])
        if kind == "textarea":
            answers[field] = template
            continue
        options = [o for o in question["options"] if o["value"] != ""]
        if not options:
            continue
        chosen = options[0]
        if kind == "radio" and any(word in template.lower() for word in negative):
            chosen = next((o for o in options if any(word in o["label"].lower() for word in negative)),
                          options[min(1, len(options) - 1)])
        elif kind in ("checkbox", "select"):
            words = [word for word in template.lower().split() if len(word) > 2]
            chosen = next((o for o in options if any(word in o["label"].lower() for word in words)),
                          options[0])
        answers[field] = chosen["value"]
    return [q["text"] for q in rich], answers


def _parse_questionnaire_rich(html: str) -> list:
    """Парсит форму опросника и возвращает богатую структуру для LLM:
    list of {field, type, text, options: [{value, label}]}
    """
    soup = BeautifulSoup(html, "html.parser")

    result = []
    by_field = {}
    q_texts = [node.get_text(separator=" ", strip=True)
               for node in soup.find_all(attrs={"data-qa": "task-question"})]
    for control in soup.find_all(("textarea", "input", "select")):
        name = control.get("name") or ""
        if not re.fullmatch(r"task_\d+(?:_text)?", name):
            continue
        kind = (control.get("type") or "text").lower() if control.name == "input" else control.name
        if kind in ("text", "textarea"):
            kind = "textarea"
        if kind not in ("textarea", "radio", "checkbox", "select"):
            continue
        if name not in by_field:
            question_node = control.find_previous(attrs={"data-qa": "task-question"})
            text = (question_node.get_text(separator=" ", strip=True) if question_node else
                    q_texts[len(result)] if len(result) < len(q_texts) else "")
            by_field[name] = {"field": name, "type": kind, "text": text, "options": []}
            result.append(by_field[name])
        question = by_field[name]
        if kind in ("radio", "checkbox"):
            value = control.get("value")
            if value is None:
                continue
            label = control.find_parent("label")
            if label is None and control.get("id"):
                label = soup.find("label", attrs={"for": control["id"]})
            label_text = label.get_text(separator=" ", strip=True) if label else ""
            question["options"].append({"value": value, "label": label_text or value})
        elif kind == "select":
            question["options"] = [{"value": opt.get("value", ""),
                                    "label": opt.get_text(separator=" ", strip=True)}
                                   for opt in control.find_all("option")]
    return result


def resolve_questionnaire_option(value, options: list[dict], *, multiple: bool = False):
    """Match an LLM choice to an HH value or a unique visible option label."""
    if isinstance(value, list):
        if not multiple or not value:
            return None
        resolved = [resolve_questionnaire_option(item, options) for item in value]
        if any(item is None for item in resolved):
            return None
        return list(dict.fromkeys(resolved))
    if not isinstance(value, (str, int, float, bool)):
        return None
    answer = str(value).strip()
    if not answer:
        return None
    for option in options:
        if answer == str(option.get("value", "")):
            return answer
    normalized = unicodedata.normalize("NFKC", answer).casefold().strip(" \t\n\r.!?:")
    matches = [str(option["value"]) for option in options
               if unicodedata.normalize("NFKC", str(option.get("label", ""))).casefold()
               .strip(" \t\n\r.!?:") == normalized]
    return matches[0] if len(matches) == 1 else None
