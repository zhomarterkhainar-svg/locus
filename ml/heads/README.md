# Обученные головы

Файлы появляются после `python ml/train_heads.py` (локально или в GitHub Actions, workflow «Train models»):

- `heads.json` — модель CLIP, дата, данные, alpha смеси и метрики каждой головы;
- `category.json`, `dorm_sub.json`, `sport_sub.json`, `bunk.json` — веса линейных голов (классы, W, b).

Если файлов нет или они обучены для другой модели CLIP, сервис работает на zero-shot промптах.
Отчёт с метриками: `ml/REPORT.md`.
