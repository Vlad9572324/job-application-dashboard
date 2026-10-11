"""AST-guard миграции Phase 3.5: все hot-path callers идут через factory.

Phase 3.5 мигрирует прямые вызовы функций web-flow модулей (app/hh_chat.py,
app/hh_apply.py, app/hh_negotiations.py, app/hh_resume.py) на
`get_client(acc).<method>()` из app/hh_client_factory.py.

Тест статически проверяет (модуль ast, без импорта app во время парсинга):

1. внешние файлы (всё под app/ рекурсивно + web_app.py, кроме web-flow
   реализации и клиентного слоя) НЕ импортируют из 4 модулей имена вне
   whitelist'а немигрируемых имён;
2. во внешних файлах НЕТ вызовов/обращений к мигрированным функциям —
   ни по имени из from-import, ни по атрибуту модуля-алиаса
   (`import app.hh_X` / `from app import hh_X`);
3. все файлы, включённые в миграцию callers Phase 3.5/3.6, покрыты guard;
   файлы с вызовом get_client импортируют его из app.hh_client_factory;
4. app/hh_client_web.py по-прежнему импортирует из всех 4 модулей —
   guard от случайного удаления делегатов web-flow реализации.

Исключения (прямые вызовы легитимны): hh_client_web.py (адаптер web-flow),
сами 4 модуля (внутренние взаимовызовы — часть web-flow), клиентный слой
(hh_client.py / hh_client_mobile.py / hh_client_fallback.py) и factory.

Whitelist немигрируемых имён (нет в HHClient и не должно быть):
- parse_hh_lux_ssr — чистый SSR-парсер без acc;
- _check_chat_locked, _build_thread_from_chat_item — чистые функции
  по chat-item, без acc и без сети;
- ChatikWSClient — класс WebSocket-клиента chatik.hh.ru;
- _resume_cache, _RESUME_CACHE_TTL — внутренний кэш web-модуля резюме;
- _JOB_SEARCH_STATUSES — константа-справочник статусов;
- fetch_similar_vacancies — публичный api.hh.ru, сигнатура без acc.

Полный маппинг call-site: scratchpad/deepdive/phase35_analysis.md.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Модули, чьи acc-функции мигрированы на HHClient, и сами мигрированные
# функции (имена, под которыми они определены в модулях).
MIGRATED_FUNCTIONS = {
    "app.hh_chat": {
        "fetch_negotiation_thread",
        "send_negotiation_message",
        "_fetch_chat_list",
        "_fetch_chat_history",
        "fetch_quick_replies",
        "send_participant_action",
        "mark_chat_read",
    },
    "app.hh_apply": {
        "send_response_async",
        "fill_and_submit_questionnaire",
        "_check_vacancy_before_apply",
        "check_limit",
        "touch_resume",
        "fetch_related_vacancies",
    },
    "app.hh_negotiations": {
        "fetch_hh_negotiations_stats",
        "fetch_hh_possible_offers",
        "auto_decline_discards",
        "fetch_negotiations_metadata",
        "fetch_employer_rating",
        "fetch_employer_id_for_vacancy",
        "fetch_vacancy_owner_hr_hhid",
        "fetch_rating_by_vacancy",
    },
    "app.hh_resume": {
        "fetch_resume_stats",
        "fetch_resume_text",
        "fetch_resume_view_history",
        "fetch_resume_views_aggregate",
        "_analyze_resume",
        "_edit_resume_field",
        "set_job_search_status",
        "fetch_account_diagnostics",
    },
}

# Имена, которые внешние файлы впредь могут импортировать из 4 модулей
# (чистые функции без acc / класс WS-клиента / внутренний кэш и константы).
NON_MIGRATABLE = {
    "parse_hh_lux_ssr",
    "_check_chat_locked",
    "_build_thread_from_chat_item",
    "ChatikWSClient",
    "_resume_cache",
    "_RESUME_CACHE_TTL",
    "_JOB_SEARCH_STATUSES",
    "fetch_similar_vacancies",
}

# Короткие имена модулей (для `from app import hh_X`).
_MODULE_SHORT_NAMES = {name.rsplit(".", 1)[1] for name in MIGRATED_FUNCTIONS}

# Файлы, где прямые вызовы легитимны (web-flow реализация и клиентный
# слой); пути относительно корня репозитория.
EXCLUDED_FILES = {
    "app/hh_client_web.py",
    "app/mobile_questionnaire.py",  # APK has no native questionnaire endpoint
    "app/hh_chat.py",
    "app/hh_apply.py",
    "app/hh_negotiations.py",
    "app/hh_resume.py",
    "app/hh_client.py",
    "app/hh_client_mobile.py",
    "app/hh_client_fallback.py",
    "app/hh_client_factory.py",
    # Mobile-flow модули: делегируют в web-функции как fallback (legitimate).
    # Phase 3 mobile_questionnaire → hh_apply.fill_and_submit_questionnaire.
    "app/mobile_questionnaire.py",
    # Security fix: routes/apply.py импортирует _aio_egress_kwargs (private
    # helper для правильного proxy в aiohttp — не hot-path caller).
    "app/routes/apply.py",
    # Targeted questionnaire tracing needs preview and exact reviewed-answer
    # submission options that are not part of the generic HHClient contract.
    "app/routes/questionnaire_trace.py",
}

# Файлы, чьи hot-path call-site мигрированы на get_client(acc).
MIGRATED_CALLER_FILES = (
    "app/manager.py",
    "app/routes/accounts.py",
    "app/routes/debug.py",
    "app/routes/settings.py",
    "app/routes/llm.py",
    "app/routes/data.py",
    "app/routes/core.py",
    "app/routes/sessions.py",
    "app/routes/apply.py",
    "app/hh_api.py",
)

WEB_ADAPTER = "app/hh_client_web.py"


def _scanned_files():
    """Все .py под app/ (рекурсивно) + web_app.py, кроме исключений."""
    app_files = (
        p for p in (ROOT / "app").rglob("*.py")
        if "__pycache__" not in p.parts
    )
    files = list(app_files) + [ROOT / "web_app.py"]
    return sorted(
        p for p in files
        if p.is_file() and p.relative_to(ROOT).as_posix() not in EXCLUDED_FILES
    )


def _parse(path):
    rel = path.relative_to(ROOT).as_posix()
    return ast.parse(path.read_text(encoding="utf-8"), filename=rel)


def _scan(tree, rel):
    """Обход AST одного файла (rel — путь относительно корня).

    Возвращает (import_violations, use_violations) — списки строк
    «file:line: описание»:
    - import_violations: имена из 4 модулей вне whitelist'а
      (включая star-import);
    - use_violations: обращения к мигрированным функциям — вызовы И
      передачи ссылки (например run_in_executor(None, func, acc)),
      как по имени из from-import, так и по атрибуту модуля-алиаса.
    """
    import_bad = []
    use_bad = []
    # локальное имя -> (модуль, исходное имя) для from-import;
    from_bindings = {}
    # локальное имя -> модуль для алиасов самого модуля;
    module_aliases = {}

    class Visitor(ast.NodeVisitor):
        def visit_ImportFrom(self, node):
            if node.module in MIGRATED_FUNCTIONS:
                for alias in node.names:
                    if alias.name == "*":
                        import_bad.append(
                            f"{rel}:{node.lineno}: from {node.module} import *"
                        )
                        continue
                    if alias.name not in NON_MIGRATABLE:
                        import_bad.append(
                            f"{rel}:{node.lineno}: from {node.module} "
                            f"import {alias.name}"
                            + (f" as {alias.asname}" if alias.asname else "")
                        )
                    bound = alias.asname or alias.name
                    from_bindings[bound] = (node.module, alias.name)
            elif node.module == "app":
                for alias in node.names:
                    if alias.name in _MODULE_SHORT_NAMES:
                        bound = alias.asname or alias.name
                        module_aliases[bound] = f"app.{alias.name}"
            self.generic_visit(node)

        def visit_Import(self, node):
            for alias in node.names:
                if alias.name in MIGRATED_FUNCTIONS:
                    bound = alias.asname or alias.name
                    module_aliases[bound] = alias.name
            self.generic_visit(node)

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load):
                binding = from_bindings.get(node.id)
                if binding is not None:
                    module, original = binding
                    if original in MIGRATED_FUNCTIONS[module]:
                        use_bad.append(
                            f"{rel}:{node.lineno}: {node.id} "
                            f"(from {module} import {original})"
                        )
            self.generic_visit(node)

        def visit_Attribute(self, node):
            if (
                isinstance(node.ctx, ast.Load)
                and isinstance(node.value, ast.Name)
            ):
                module = module_aliases.get(node.value.id)
                if module is not None and node.attr not in NON_MIGRATABLE:
                    suffix = (
                        " — мигрирована на get_client(acc)"
                        if node.attr in MIGRATED_FUNCTIONS[module]
                        else " — вне whitelist немигрируемых имён"
                    )
                    use_bad.append(
                        f"{rel}:{node.lineno}: {node.value.id}.{node.attr} "
                        f"({module}){suffix}"
                    )
            self.generic_visit(node)

    Visitor().visit(tree)
    return import_bad, use_bad


# ---------------------------------------------------------------------------
# 1. Импорты: из 4 модулей внешним файлам доступен только whitelist
#    (автоматически ловит и удалённый мёртвый импорт fetch_rating_by_vacancy,
#    и colliding fetch_employer_rating из hh_negotiations).
# ---------------------------------------------------------------------------

def test_external_imports_only_whitelisted_names():
    violations = []
    for path in _scanned_files():
        rel = path.relative_to(ROOT).as_posix()
        import_bad, _ = _scan(_parse(path), rel)
        violations.extend(import_bad)
    assert not violations, (
        "Импорты имён из web-flow модулей (app.hh_chat / hh_apply / "
        "hh_negotiations / hh_resume) вне whitelist'а немигрируемых имён.\n"
        "Мигрированные функции импортировать нельзя — вызывать через "
        "get_client(acc).<method>(). Нарушения:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 2. Вызовы: ни прямого вызова, ни передачи ссылки на мигрированную функцию
#    (например в run_in_executor) во внешних файлах быть не должно.
# ---------------------------------------------------------------------------

def test_no_direct_calls_of_migrated_functions():
    violations = []
    for path in _scanned_files():
        rel = path.relative_to(ROOT).as_posix()
        _, use_bad = _scan(_parse(path), rel)
        violations.extend(use_bad)
    assert not violations, (
        "Прямые обращения к мигрированным функциям web-flow модулей — "
        "все hot-path callers должны идти через get_client(acc).<method>(). "
        "Нарушения:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 3. Позитивная проверка: мигрированные файлы существуют, а реальные callers
#    get_client импортируют его из factory. Часть файлов Phase 3.6 не имела
#    account-bound web-flow вызовов; для них не создаём фиктивный импорт.
# ---------------------------------------------------------------------------

def test_migrated_callers_import_get_client():
    missing = []
    for rel in MIGRATED_CALLER_FILES:
        path = ROOT / rel
        if not path.is_file():
            missing.append(f"{rel} (file missing)")
            continue
        tree = _parse(path)
        calls_get_client = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "get_client"
            for node in ast.walk(tree)
        )
        found = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "app.hh_client_factory"
            and any(alias.name == "get_client" for alias in node.names)
            for node in ast.walk(tree)
        )
        if calls_get_client and not found:
            missing.append(rel)
    assert not missing, (
        "Файлы с мигрированными call-site должны импортировать "
        "get_client из app.hh_client_factory, но импорт не найден в:\n"
        + "\n".join(missing)
    )


# ---------------------------------------------------------------------------
# 4. Web-flow guard: адаптер WebHHClient не потерял делегаты.
# ---------------------------------------------------------------------------

def test_web_adapter_still_imports_webflow_modules():
    path = ROOT / WEB_ADAPTER
    assert path.is_file(), (
        f"{WEB_ADAPTER} отсутствует — web-flow реализация HHClient потеряна"
    )
    imported = set()
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.ImportFrom):
            if node.module in MIGRATED_FUNCTIONS:
                imported.add(node.module)
            elif node.module == "app":
                imported |= {
                    f"app.{alias.name}" for alias in node.names
                    if f"app.{alias.name}" in MIGRATED_FUNCTIONS
                }
        elif isinstance(node, ast.Import):
            imported |= {
                alias.name for alias in node.names
                if alias.name in MIGRATED_FUNCTIONS
            }
    missing = set(MIGRATED_FUNCTIONS) - imported
    assert not missing, (
        f"{WEB_ADAPTER} больше не импортирует: {sorted(missing)}. "
        "Делегаты web-flow реализации не должны удаляться."
    )


# ---------------------------------------------------------------------------
# Self-check констант теста: whitelist и мигрированный список не
# пересекаются (иначе guard противоречил бы сам себе).
# ---------------------------------------------------------------------------

def test_whitelist_and_migrated_sets_are_disjoint():
    overlap = NON_MIGRATABLE & set().union(*MIGRATED_FUNCTIONS.values())
    assert not overlap, (
        f"Имена одновременно в whitelist и в мигрированном списке: {overlap}"
    )
