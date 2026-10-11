"""Catch clear first-person gender conflicts before automated text is sent."""

import re

from app.config import CONFIG


_MASCULINE = (
    "готов", "работал", "тестировал", "проводил", "участвовал", "занимался",
    "сталкивался", "использовал", "получил", "написал", "сделал", "согласен",
    "заинтересован", "открыт", "рад", "уверен", "закончил", "учился",
    "начал", "помогал", "разработал", "внедрил", "ознакомился",
    "откликнулся", "специализировался", "руководил", "создал", "настроил",
)
_FEMININE = (
    "готова", "работала", "тестировала", "проводила", "участвовала", "занималась",
    "сталкивалась", "использовала", "получила", "написала", "сделала", "согласна",
    "заинтересована", "открыта", "рада", "уверена", "закончила", "училась",
    "начала", "помогала", "разработала", "внедрила", "ознакомилась",
    "откликнулась", "специализировалась", "руководила", "создала", "настроила",
)
_WORDS = re.compile(r"(?iu)\b(?:" + "|".join(_MASCULINE + _FEMININE) + r")\b")


def configured_gender() -> str:
    value = str(getattr(CONFIG, "llm_applicant_gender", "female") or "female").strip().lower()
    if value in ("male", "m", "masculine", "мужской"):
        return "male"
    if value in ("neutral", "n", "неважно", "нейтральный"):
        return "neutral"
    return "female"


def conflicting_gender_words(text: str, gender: str | None = None) -> list[str]:
    """Return high-confidence gendered words incompatible with the setting.

    The guard is deliberately conservative about morphology: uncertain wording
    is left alone, while a detected conflict blocks automatic sending.
    """
    selected = gender or configured_gender()
    forbidden = (set(_MASCULINE) if selected == "female" else
                 set(_FEMININE) if selected == "male" else
                 set(_MASCULINE + _FEMININE))
    return list(dict.fromkeys(match.group().lower() for match in _WORDS.finditer(text or "")
                              if match.group().lower() in forbidden))
