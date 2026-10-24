import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import llm_fallback as lf  # noqa: E402

SCHEMA = {"type": "object", "required": ["a", "b"],
          "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}}


def run(coro):
    return asyncio.run(coro)


def lim(e):
    return "limit" in str(e)


def kw(**extra):
    return dict(system="sys", schema=SCHEMA, timeout=5, **extra)


async def ok_primary(s, prompt, **kw_):
    return {"a": 1, "b": 2, "who": "claude"}


async def limit_primary(s, prompt, **kw_):
    raise RuntimeError("usage limit reached")


async def other_primary(s, prompt, **kw_):
    raise RuntimeError("boom")


def test_extract_json_variants():
    assert lf.extract_json('текст ```json\n{"a": 1, "n": {"x": 2}}\n``` хвост') == {"a": 1, "n": {"x": 2}}
    assert lf.extract_json("нет json") is None
    assert lf.extract_json("{битый") is None


def test_extract_json_allows_raw_newlines_in_strings():
    assert lf.extract_json('```json\n{"a": "строка1\nстрока2", "b": 1}\n```') == {"a": "строка1\nстрока2", "b": 1}


def test_primary_ok_no_router(monkeypatch):
    monkeypatch.setattr(lf, "_post", lambda *a: pytest.fail("роутер не должен вызываться"))
    out = run(lf.with_fallback(ok_primary, None, "p", free_ok=True, is_limit=lim, **kw()))
    assert out["who"] == "claude" and lf.last_backend == "claude"


def test_limit_free_ok_uses_router(monkeypatch):
    seen = {}

    def fake(body, timeout):
        seen["body"] = body
        return 'вот ответ: {"a": 1, "b": 2}'

    monkeypatch.setattr(lf, "_post", fake)
    out = run(lf.with_fallback(limit_primary, None, "p", free_ok=True, is_limit=lim, tools=("Read",), **kw()))
    assert out == {"a": 1, "b": 2}
    assert lf.last_backend.startswith("router:")
    assert "только по тексту" in seen["body"]["messages"][1]["content"]


def test_limit_not_free_ok_raises_original(monkeypatch):
    monkeypatch.setattr(lf, "_post", lambda *a: pytest.fail("роутер не должен вызываться"))
    with pytest.raises(RuntimeError, match="usage limit"):
        run(lf.with_fallback(limit_primary, None, "p", free_ok=False, is_limit=lim, **kw()))


def test_non_limit_error_not_swallowed(monkeypatch):
    monkeypatch.setattr(lf, "_post", lambda *a: pytest.fail("роутер не должен вызываться"))
    with pytest.raises(RuntimeError, match="boom"):
        run(lf.with_fallback(other_primary, None, "p", free_ok=True, is_limit=lim, **kw()))


def test_router_failure_reraises_original_limit(monkeypatch):
    def fail(*a):
        raise lf.RouterError("429")

    monkeypatch.setattr(lf, "_post", fail)
    with pytest.raises(RuntimeError, match="usage limit"):
        run(lf.with_fallback(limit_primary, None, "p", free_ok=True, is_limit=lim, **kw()))


def test_bad_json_retries_once_then_fails(monkeypatch):
    monkeypatch.setattr(lf, "ROUTER_MODELS", ["m1"])
    calls = []
    monkeypatch.setattr(lf, "_post", lambda *a: calls.append(1) or "не json")
    with pytest.raises(lf.RouterError):
        run(lf.run_router("p", system="s", schema=SCHEMA, timeout=5))
    assert len(calls) == 2


def test_missing_required_key_retries(monkeypatch):
    answers = iter(['{"a": 1}', '{"a": 1, "b": 2}'])
    monkeypatch.setattr(lf, "_post", lambda *a: next(answers))
    assert run(lf.run_router("p", system="s", schema=SCHEMA, timeout=5)) == {"a": 1, "b": 2}


def test_text_mode_no_schema(monkeypatch):
    monkeypatch.setattr(lf, "_post", lambda *a: "просто текст")
    assert run(lf.run_router("p", system="s", timeout=5)) == "просто текст"


def test_wrong_type_retries(monkeypatch):
    schema = {"type": "object", "required": ["t", "n"],
              "properties": {"t": {"type": "string"}, "n": {"type": ["string", "null"]}}}
    answers = iter(['{"t": {"x": 1}, "n": null}', '{"t": "ok", "n": null}'])
    monkeypatch.setattr(lf, "_post", lambda *a: next(answers))
    assert run(lf.run_router("p", system="s", schema=schema, timeout=5)) == {"t": "ok", "n": None}


def test_bool_is_not_integer():
    assert not lf.conforms({"a": True}, {"required": ["a"], "properties": {"a": {"type": "integer"}}})


def test_chain_falls_to_second_model(monkeypatch):
    monkeypatch.setattr(lf, "ROUTER_MODELS", ["m1", "m2"])
    seen = []

    def fake(body, t):
        seen.append(body["model"])
        if body["model"] == "m1":
            raise lf.RouterError("429")
        return '{"a": 1, "b": 2}'

    monkeypatch.setattr(lf, "_post", fake)
    out = run(lf.with_fallback(limit_primary, None, "p", free_ok=True, is_limit=lim, **kw()))
    assert out == {"a": 1, "b": 2} and seen == ["m1", "m2"] and lf.last_backend == "router:m2"


def test_chain_all_fail_reraises_original(monkeypatch):
    monkeypatch.setattr(lf, "ROUTER_MODELS", ["m1", "m2"])

    def fail(*a):
        raise lf.RouterError("429")

    monkeypatch.setattr(lf, "_post", fail)
    with pytest.raises(RuntimeError, match="usage limit"):
        run(lf.with_fallback(limit_primary, None, "p", free_ok=True, is_limit=lim, **kw()))
