#!/usr/bin/env bash
# Выкладывает текущее состояние репозитория в Hugging Face Space (Docker SDK).
# Пушится один снимок без истории: Space хранит только то, что нужно для сборки.
# Нужны переменные HF_TOKEN (write) и HF_SPACE ("username/space-name").
set -euo pipefail
: "${HF_TOKEN:?нужен HF_TOKEN}"
: "${HF_SPACE:?нужен HF_SPACE вида username/space-name}"
HF_USER="${HF_SPACE%%/*}"
SRC="$(git rev-parse --show-toplevel)"
TMP="$(mktemp -d)"
git -C "$SRC" archive --format=tar HEAD | tar -x -C "$TMP"
cd "$TMP"
git init -q -b main
git config user.name "deploy-bot"
git config user.email "deploy@users.noreply.huggingface.co"
git add -A
git commit -q -m "Deploy $(git -C "$SRC" rev-parse --short HEAD)"
git push -q --force "https://${HF_USER}:${HF_TOKEN}@huggingface.co/spaces/${HF_SPACE}" main
echo "Выложено в https://huggingface.co/spaces/${HF_SPACE}"
