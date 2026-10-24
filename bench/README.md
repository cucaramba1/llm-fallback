# Замеры бесплатных и Claude-моделей (22-24.10.2026)

Все скрипты только читают базы проектов. Запускать из venv нужного проекта, по одному процессу (бесплатные лимиты узкие, см. правила).

| Скрипт | Что делает | Запуск (из `reels-radar`, если не сказано иное) |
|---|---|---|
| `bench.py` | Reels Radar: тот же промпт и схема через FreeLLMAPI, текст без кадров, 125 записей | `.venv/bin/python bench.py <модель> <out.jsonl>` |
| `analyze.py` | Сводка по `res_*.jsonl` в своей папке: JSON, тема, вид, цели | `.venv/bin/python analyze.py` |
| `bench_claude.py` | То же через `claude -p` (`haiku`/`sonnet`), третий аргумент шаг выборки | `.venv/bin/python bench_claude.py haiku out.jsonl 1` |
| `ib_replay.py` | Idea Bot: реплей `analyze`/`pick_l3` на готовых идеях | из `idea-bot`: `.venv/bin/python ib_replay.py <модель> out.json analyze\|pick` |

Скрипты написаны под scratchpad (пути к результатам относительные от файла скрипта), перед запуском скопируй в рабочую папку или поправь пути.

## Итоги
- gpt-oss-120b: JSON 100%, вид 97%, цели 92%, тема 61%.
- ministral-14b: JSON 65%, вид 97%, цели 68%, тема 59%.
- Idea Bot `analyze` на ministral: валидно 6/10, тип 4/6, тема 3/6, бизнес-оценка завышена. Запас там не включать.
