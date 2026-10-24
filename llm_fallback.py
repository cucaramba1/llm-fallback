"""Запас на случай лимита Claude: тот же вызов через локальный FreeLLMAPI.

Только stdlib, чтобы любой проект подключал файл через sys.path без новых зависимостей.
Бесплатная модель включается только для задач с free_ok=True (решает вызывающий код).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger("llm_fallback")

ROUTER_URL = os.environ.get("FREELLM_URL", "http://127.0.0.1:3001")
ROUTER_DB = Path.home() / "Claude Code/freellmapi/server/data/freeapi.db"
# модели по очереди: gpt-oss точнее (замер 22.10: JSON 100%, цели 92%), ministral стабильнее по доступности (JSON 65%, цели 68%)
ROUTER_MODELS = [m.strip() for m in os.environ.get(
    "FREELLM_MODELS", os.environ.get("FREELLM_MODEL", "openai/gpt-oss-120b,ministral-14b-latest")).split(",") if m.strip()]

# кто ответил в последнем вызове: "claude" или "router:<модель>" (для логов и пометок в карточках)
last_backend = "claude"
last_model = ""


class RouterError(RuntimeError):
    pass


def _key() -> str:
    if os.environ.get("FREELLM_KEY"):
        return os.environ["FREELLM_KEY"]
    try:
        with sqlite3.connect(f"file:{ROUTER_DB}?mode=ro", uri=True) as c:
            row = c.execute("select value from settings where key='unified_api_key'").fetchone()
    except sqlite3.Error as e:
        raise RouterError(f"ключ роутера недоступен: {e}")
    if not row:
        raise RouterError("ключ роутера не найден")
    return row[0]


def _post(body: dict, timeout: int) -> str:
    rq = urllib.request.Request(f"{ROUTER_URL}/v1/chat/completions", json.dumps(body).encode(),
                                {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(rq, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"].get("content") or ""
    except urllib.error.HTTPError as e:
        raise RouterError(f"роутер {e.code}: {e.read().decode(errors='ignore')[:200]}")
    except Exception as e:  # noqa: BLE001 (сеть, таймаут, кривой JSON ответа)
        raise RouterError(f"роутер недоступен: {str(e)[:200]}")


def extract_json(text: str) -> dict | None:
    """Первый JSON-объект в тексте: модель может обернуть его в ```json или пояснения."""
    dec = json.JSONDecoder(strict=False)  # модели кладут реальные переводы строк внутрь строковых полей
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(text[i:])
            except ValueError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


_PY = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def conforms(obj: dict, schema: dict) -> bool:
    """Все обязательные ключи на месте и типы верхнего уровня совпадают со схемой (null допустим, если схема его допускает)."""
    props = schema.get("properties", {})
    for k in schema.get("required", []):
        if k not in obj:
            return False
        t = props.get(k, {}).get("type")
        ts = t if isinstance(t, list) else [t]
        v = obj[k]
        if t is None or (v is None and "null" in ts):
            continue
        if not any(isinstance(v, _PY[x]) and not (x in ("integer", "number") and isinstance(v, bool))
                   for x in ts if x in _PY):
            return False
    return True


async def _one_model(model: str, prompt: str, system: str, schema: dict | None, timeout: int) -> dict | str:
    hint = ("\n\nОтветь ТОЛЬКО JSON без markdown-ограждений, строго по схеме:\n"
            + json.dumps(schema, ensure_ascii=False)) if schema else ""
    body = {"model": model, "max_tokens": int(os.environ.get("FREELLM_MAX_TOKENS", "4000")), "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt + hint}]}
    for attempt in (1, 2):  # один повтор на кривой JSON
        txt = await asyncio.to_thread(_post, body, timeout)
        if schema is None:
            return txt
        obj = extract_json(txt)
        if obj is not None and conforms(obj, schema):
            return obj
        log.warning("роутер %s вернул невалидный JSON (попытка %d)", model, attempt)
    raise RouterError(f"роутер {model}: нет валидного JSON по схеме")


async def run_router(prompt: str, *, system: str, schema: dict | None = None, timeout: int,
                     model: str | None = None) -> dict | str:
    """Модели по очереди (или одна, если model задан). Кто ответил, лежит в last_model."""
    global last_model
    errors = []
    for m in ([model] if model else ROUTER_MODELS):
        try:
            out = await _one_model(m, prompt, system, schema, timeout)
        except RouterError as e:
            errors.append(str(e)[:160])
            log.warning("модель %s не сработала, пробую следующую: %s", m, e)
            continue
        last_model = m
        return out
    raise RouterError(" | ".join(errors) or "нет моделей в FREELLM_MODELS")


async def with_fallback(primary: Callable[..., Awaitable], s, prompt: str, *, free_ok: bool,
                        is_limit: Callable[[Exception], bool], **kw):
    """Claude первым. При лимите и free_ok=True та же задача уходит в роутер, иначе ошибка как раньше."""
    global last_backend
    try:
        out = await primary(s, prompt, **kw)
        last_backend = "claude"
        return out
    except Exception as e:  # noqa: BLE001
        if not (free_ok and is_limit(e)):
            raise
        note = ""
        if kw.get("tools"):
            note = "\n\n(Файлы и кадры сейчас недоступны, работай только по тексту выше.)"
        try:
            out = await run_router(prompt + note, system=kw["system"], schema=kw.get("schema"),
                                   timeout=kw["timeout"])
        except RouterError as re_:
            log.error("запас не сработал: %s", re_)
            raise e  # исходная ошибка лимита: вызывающий код поставит задачу на паузу как раньше
        last_backend = f"router:{last_model}"
        log.warning("лимит Claude, ответил запас %s", last_backend)
        return out
