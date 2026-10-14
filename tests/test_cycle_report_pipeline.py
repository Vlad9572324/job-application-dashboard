"""Execute actual manager branches with synthetic candidates and no HH I/O.

AST extraction keeps production break/continue and report hooks intact while
excluding unrelated scheduler, account startup, and collection side effects.
Run from a temporary cwd, as with the other manager integration tests.
"""
import ast
import copy
import inspect
import textwrap
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import manager as module
from app.cycle_report import SKIP_REASONS, begin_cycle, cycle_snapshot, found_cycle
from app.manager import BotManager
from app.mutation_safety import MutationBlocked
from app.state import AccountState


def worker_tree():
    return ast.parse(textwrap.dedent(inspect.getsource(BotManager._run_account_worker_inner)))


def assigns(node, name):
    return isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == name for target in node.targets)


def branch_sequence(start_name, end_condition):
    for parent in ast.walk(worker_tree()):
        body = getattr(parent, "body", None)
        if not isinstance(body, list):
            continue
        starts = [i for i, node in enumerate(body) if assigns(node, start_name)]
        if not starts:
            continue
        start = starts[0]
        end = next(i for i in range(start + 1, len(body))
                   if isinstance(body[i], ast.If) and ast.unparse(body[i].test) == end_condition)
        return body[start:end + 1]
    raise AssertionError("Production manager branch not found")


def execute(nodes, env):
    wrapper = ast.For(target=ast.Name(id="_once", ctx=ast.Store()),
        iter=ast.List(elts=[ast.Constant(0)], ctx=ast.Load()),
        body=copy.deepcopy(nodes), orelse=[])
    tree = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
    exec(compile(tree, "<actual-cycle-report-pipeline>", "exec"), env)
    return env


@pytest.fixture
def pipeline(monkeypatch):
    state = AccountState({"name": "synthetic-cycle", "short": "S", "color": "blue",
        "urls": [], "resume_hash": "synthetic-resume"})
    state.apply_tests = True
    state.degraded_fallback_enabled = False
    bot = BotManager.__new__(BotManager)
    bot.paused = False
    bot._stop_event = threading.Event()
    bot._hr_contacts_lock = threading.Lock()
    bot.hr_contacts = []
    for name in ("_add_log", "_add_response", "_add_acc_event", "_push_action",
                 "_persist_pauses", "_activity_vacancy", "_check_auto_pause"):
        setattr(bot, name, Mock())
    bot._maybe_roll_daily_counter = Mock(return_value=False)

    def pending(*args, **kwargs):
        state.paused = True
        state.paused_reason = "outcome_unknown"
    bot.hold_pending_apply = Mock(side_effect=pending)
    for name in ("add_applied", "add_test_vacancy", "log_debug", "log_exception"):
        monkeypatch.setattr(module, name, Mock())
    monkeypatch.setattr(module, "is_applied", lambda *args: False)
    monkeypatch.setattr(module, "is_test", lambda *args: False)
    for name in ("get_client", "fetch_vacancy_details", "fetch_employer_rating", "_oauth_apply"):
        monkeypatch.setattr(module, name, Mock(side_effect=AssertionError("Unexpected external operation")))
    monkeypatch.setattr(module, "HH", SimpleNamespace(
        get=Mock(side_effect=AssertionError("Unexpected external operation"))))
    monkeypatch.setattr(module, "time", SimpleNamespace(sleep=Mock(), time=Mock(return_value=0)))
    for key, value in {
        "auto_apply_tests": False, "title_include_keywords": [], "title_exclude_keywords": [],
        "skip_auto_response_vacancies": False, "accredited_it_only": False,
        "prefer_quick_responses": False, "min_employer_rating": 0,
        "min_recommendations_percent": 0, "allowed_schedules": [], "min_salary": 0,
        "fresh_vacancies_mode": False, "prefer_hh_signals": False,
        "use_oauth_apply": False, "stop_on_hh_limit": True,
    }.items():
        monkeypatch.setattr(module.CONFIG, key, value)
    begin_cycle(state)
    return bot, state


def snapshot(state):
    report = cycle_snapshot(state, blocked=state.paused)
    assert report["processed"] == sum(report[key] for key in ("sent", "skipped", "errors", "unknown"))
    assert report["processed"] <= report["found_unique"]
    assert report["already"] <= report["skipped"]
    assert report["remaining"] == report["found_unique"] - report["processed"]
    return report


def filter_candidates(pipeline, candidates, *, salary=None, schedules=None):
    bot, state = pipeline
    state.vacancy_meta = candidates
    env = dict(vars(module), self=bot, state=state, acc=state.acc,
        unique_vacancies=set(candidates), salary_map=salary or {}, schedule_map=schedules or {})
    return execute(branch_sequence("filtered", "not filtered"), env)


@pytest.mark.parametrize("reason", [
    "missing_title", "archived", "already", "questionnaire_disabled",
    "salary", "schedule", "title_exclude",
])
def test_actual_all_skipped_filter_closes_cycle_with_exact_reason(pipeline, monkeypatch, reason):
    bot, state = pipeline
    candidate = {"title": "Synthetic role"}
    salary, schedules = {}, {}
    if reason == "missing_title":
        candidate = {}
    elif reason == "archived":
        candidate["archived"] = True
    elif reason == "already":
        monkeypatch.setattr(module, "is_applied", lambda *args: True)
    elif reason == "questionnaire_disabled":
        state.apply_tests = False
        monkeypatch.setattr(module, "is_test", lambda *args: True)
    elif reason == "salary":
        monkeypatch.setattr(module.CONFIG, "min_salary", 100)
        salary = {"v": 50}
    elif reason == "schedule":
        monkeypatch.setattr(module.CONFIG, "allowed_schedules", ["remote"])
        schedules = {"v": {"fullDay"}}
    elif reason == "title_exclude":
        monkeypatch.setattr(module.CONFIG, "title_exclude_keywords", ["synthetic"])
    found_cycle(state, ["v"], 1)
    result = filter_candidates(pipeline, {"v": candidate}, salary=salary, schedules=schedules)
    report = snapshot(state)
    assert result["filtered"] == []
    assert (report["processed"], report["skipped"], report["sent"], report["remaining"]) == (1, 1, 0, 0)
    assert report["skip_reasons"] == [{"key": reason, "label": SKIP_REASONS[reason], "count": 1}]
    assert report["status"] == "waiting" and report["finished_at"]
    module.get_client.assert_not_called()
    module.add_applied.assert_not_called()


def test_actual_filter_deduplicates_cross_search_and_repeated_observations(pipeline, monkeypatch):
    bot, state = pipeline
    monkeypatch.setattr(module, "is_applied", lambda *args: True)
    found_cycle(state, ["v", "v", "v"], 3)
    candidates = {"v": {"title": "Synthetic role"}}
    filter_candidates(pipeline, candidates)
    filter_candidates(pipeline, candidates)
    report = snapshot(state)
    assert (report["found_raw"], report["found_unique"]) == (3, 1)
    assert (report["processed"], report["already"], report["skipped"]) == (1, 1, 1)
    assert state.already_applied == 2  # Legacy events do not inflate the cycle report.


def completed_results(pipeline, results, *, batch=None):
    bot, state = pipeline
    batch = batch or ["v" + str(i) for i in range(len(results))]
    state.vacancy_meta = {vid: {"title": "Synthetic role", "company": "Synthetic company"} for vid in batch}
    found_cycle(state, batch, len(batch))
    env = dict(vars(module), self=bot, state=state, acc=state.acc,
        batch=batch, results=results, filtered=batch, i=0, batch_size=len(batch),
        attempt_accounts={vid: dict(state.acc, _pinned_resume_id="synthetic-resume") for vid in batch})
    execute(branch_sequence("completed", "state.limit_exceeded"), env)
    return snapshot(state)


@pytest.mark.parametrize("cancelled", [("cancelled", {}), MutationBlocked("synthetic cancellation")])
def test_actual_completed_cancelled_is_not_sent(pipeline, cancelled):
    _, state = pipeline
    report = completed_results(pipeline, [cancelled])
    assert (report["processed"], report["skipped"], report["sent"], report["errors"]) == (1, 1, 0, 0)
    assert report["skip_reasons"][0]["key"] == "cancelled"
    assert state.sent == state.daily_sent == 0
    module.add_applied.assert_not_called()


@pytest.mark.parametrize("result", ["auth_error", "error"])
def test_actual_completed_failure_is_reported_even_without_legacy_error_increment(pipeline, result):
    _, state = pipeline
    report = completed_results(pipeline, [(result, {})])
    assert (report["processed"], report["errors"], report["sent"]) == (1, 1, 0)
    assert state.sent == state.daily_sent == 0
    if result == "auth_error":
        assert state.paused and state.paused_reason == "auth"
        assert report["status"] == "blocked"
        assert state.errors == 0


def test_completed_batch_preserves_all_terminal_results_after_auth_break(pipeline):
    report = completed_results(pipeline, [("auth_error", {}), ("error", {}), ("cancelled", {}), ("sent", {})])
    assert (report["processed"], report["sent"], report["errors"], report["skipped"]) == (4, 1, 2, 1)
    assert report["remaining"] == 0 and report["status"] == "blocked"


def test_completed_duplicate_already_does_not_downgrade_confirmed_sent(pipeline):
    report = completed_results(pipeline, [("sent", {}), ("already", {})], batch=["v", "v"])
    assert (report["found_raw"], report["found_unique"], report["processed"]) == (2, 1, 1)
    assert (report["sent"], report["already"], report["skipped"]) == (1, 0, 0)


def test_actual_collection_failure_is_not_an_application_failure(pipeline):
    bot, state = pipeline
    branch = next(node for node in ast.walk(worker_tree())
        if isinstance(node, ast.ExceptHandler) and "COLLECT CRASH" in ast.unparse(node))
    execute(branch.body, dict(vars(module), self=bot, state=state,
        e=RuntimeError("synthetic collection failure")))
    report = cycle_snapshot(state)
    assert report["operation_errors"] == 1 and report["partial"] is True
    assert report["status"] == "error"
    assert report["found_unique"] is None and report["remaining"] is None
    assert (report["processed"], report["errors"], report["sent"], report["unknown"]) == (0, 0, 0, 0)


def test_attempt_guard_rechecks_remote_it_scope_after_setting_changes(pipeline, monkeypatch):
    bot, state = pipeline
    assignment = next(node for node in ast.walk(worker_tree()) if assigns(node, 'attempt_accounts'))
    guard_loop = next(node for node in ast.walk(worker_tree()) if isinstance(node, ast.For)
                     and ast.unparse(node.target) == '(scope_vid, attempt_acc)')
    env = execute([assignment, guard_loop], dict(vars(module), self=bot, state=state,
                  batch=['v'], acc=state.acc))
    guard = env['attempt_accounts']['v']['_mutation_guard']
    monkeypatch.setattr(module.human_pace, 'is_active_hour', lambda *a, **k: True)  # not wall-clock dependent
    monkeypatch.setattr(module.CONFIG, 'remote_it_only', False)
    assert guard()
    monkeypatch.setattr(module.CONFIG, 'remote_it_only', True)
    assert not guard()
    state.vacancy_meta['v'] = {'professional_roles':[{'id':'96'}], 'work_format':[{'id':'REMOTE'}]}
    assert guard()
    state.vacancy_meta['v']['work_format'] = [{'id':'HYBRID'}]
    assert not guard()
    module.add_applied.assert_not_called()


@pytest.mark.parametrize("questionnaire_result,expected", [
    ("sent", "sent"), ("already", "already"), ("auth_error", "errors"),
    ("error", "errors"), ("unknown", "unknown"), ("cancelled", "skipped"),
])
def test_actual_questionnaire_intermediate_test_has_one_final_outcome(pipeline, monkeypatch, questionnaire_result, expected):
    bot, state = pipeline
    fill = AsyncMock(return_value=(questionnaire_result, {}))
    monkeypatch.setattr(module, "get_client", Mock(return_value=SimpleNamespace(fill_questionnaire=fill)))
    report = completed_results(pipeline, [("test", {})])
    assert report["processed"] == 1 and report["questionnaires_pending"] == 0
    assert report[expected] == 1
    assert report["sent"] == int(questionnaire_result == "sent")
    assert fill.await_count == 1
    if questionnaire_result == "auth_error":
        assert state.paused_reason == "auth" and report["status"] == "blocked"
