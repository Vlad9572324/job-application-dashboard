"""Conservative checks for concrete applicant claims before a questionnaire POST."""

import re


_NUMBER_WORDS = {"один": 1, "одна": 1, "одну": 1, "два": 2, "две": 2,
                 "три": 3, "четыре": 4, "пять": 5, "шесть": 6}
_COUNT = r"\d+|один|одна|одну|два|две|три|четыре|пять|шесть"
_DURATION = re.compile(rf"\b({_COUNT})\s*(дн(?:я|ей|ь)|недел[июьиь]*|месяц(?:а|ев)?|мес\.?|лет|года?|год|г\.|л\.)(?=\s|$|[,.;])", re.I)
_MONEY = re.compile(r"(?<!\d)(\d[\d\s\u00a0]{3,}\d|\d{2,3})\s*(тыс(?:яч)?\.?|₽|руб(?:лей|ля|ль)?\b|р\.)?", re.I)
_DOMAIN_TERMS = {
    "desktop": r"десктоп|desktop|настольн\w*\s+(?:приложени|по)",
    "mobile": r"мобил\w*\s+(?:приложени|тестирован)|\b(?:ios|android)\b",
    "fintech": r"финтех|fintech|плат[её]жн\w*\s+(?:систем|операци)",
    "web": r"веб[-\s]?(?:сайт|приложени)|\bweb[-\s]?(?:site|app)\b|фронтенд",
    "rest_api": r"\bREST(?:ful)?\b|\bAPI\b|апи\b",
}


def _count(value: str) -> int:
    return int(value) if value.isdigit() else _NUMBER_WORDS[value.lower()]


def _durations(text: str) -> set[tuple[int, str]]:
    values = set()
    for match in _DURATION.finditer(text):
        unit = match.group(2).lower()
        kind = "days" if unit.startswith("дн") else "weeks" if unit.startswith("недел") else (
            "months" if unit.startswith(("мес", "месяц")) else "years")
        values.add((_count(match.group(1)), kind))
    return values


def _money_amounts(text: str) -> set[int]:
    amounts = set()
    for match in _MONEY.finditer(text):
        raw, unit = match.groups()
        amount = int(re.sub(r"\s", "", raw))
        if unit and unit.lower().startswith("тыс"):
            amount *= 1000
        # A bare small number is likely a date, experience, or question number.
        if amount >= 1000 or unit:
            amounts.add(amount)
    return amounts


def unsupported_questionnaire_claims(questions: list[dict], answers: dict,
                                     sources: dict, resume_text: str,
                                     saved_prompt: str) -> list[dict]:
    """Return field and reason codes for unsupported concrete claims in LLM text.

    This is intentionally narrow: it catches known costly assertions, but it is
    not a general fact checker. The caller must stop the POST when any item exists.
    """
    source = f"{resume_text or ''}\n{saved_prompt or ''}"
    source_durations = _durations(source)
    source_money = _money_amounts(source)
    by_field = {q.get("field"): q for q in questions}
    issues = []
    for field, answer in answers.items():
        if sources.get(field) != "llm" or not isinstance(answer, str):
            continue
        question = by_field.get(field) or {}
        if question.get("type") != "textarea":
            continue
        qtext = str(question.get("text") or "").lower()
        value = answer.lower()
        reasons = []

        salary_question = bool(re.search(
            r"зарплат|заработн.{0,20}плат|оклад|доход|компенсац|вознагражден", qtext))
        if salary_question or re.search(r"₽|\bруб(?:лей|ля|ль)?\b", value):
            if _money_amounts(value) - source_money:
                reasons.append("salary_amount")
        if salary_question:
            if re.search(r"\b(?:преми[яиюе]|бонус\w*)\b", value) and not re.search(
                    r"\b(?:преми[яиюе]|бонус\w*)\b", source.lower()):
                reasons.append("salary_bonus")

        if re.search(r"как скоро|когда.{0,30}(?:приступ|выйт|начать)|срок.{0,15}выход|дата.{0,15}выход", qtext):
            if _durations(value) - source_durations:
                reasons.append("start_delay")
            if re.search(r"\b(?:сразу|немедленно|незамедлительно)\b", value) and not re.search(
                    r"\b(?:сразу|немедленно|незамедлительно)\b", source.lower()):
                reasons.append("start_immediate")

        if re.search(r"опыт|стаж", qtext) or re.search(r"\bопыт\s+(?:работы\s+)?(?:более\s+)?\d+\s*(?:лет|года|год)\b", value):
            answer_years = {n for n, unit in _durations(value) if unit == "years"}
            source_years = {n for n, unit in source_durations if unit == "years"}
            if answer_years and (not source_years or max(answer_years) > max(source_years)):
                reasons.append("experience_years")

        # Questions often list example products. Listing an example in an
        # affirmative answer must not turn it into the applicant's experience.
        if re.search(r"опыт|сталкивал|работал|тестиров|продукт|проект", qtext):
            for domain, pattern in _DOMAIN_TERMS.items():
                for match in re.finditer(pattern, value, re.I):
                    prefix = value[max(0, match.start() - 55):match.start()]
                    if re.search(r"(?:нет|не было|не имею|без)\s+(?:практического\s+)?опыта\s+(?:с|в|по)?\s*$", prefix):
                        continue
                    if not re.search(pattern, source, re.I):
                        reasons.append(f"unsupported_domain_{domain}")
                    break

        if reasons:
            issues.append({"field": field, "reasons": reasons})
    return issues
