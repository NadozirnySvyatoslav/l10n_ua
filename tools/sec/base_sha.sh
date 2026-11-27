#!/usr/bin/env bash
# Друкує базу для diff перевірок шлюзу. Аргументи: <BASE_SHA> [<базова гілка>].
# На push нової гілки github.event.before = 000…0, після force-push старого коміта може не бути
# в історії. Тоді беремо merge-base з базовою гілкою. Якщо він збігається з HEAD (push самої
# базової гілки) або його немає — батька HEAD.
set -euo pipefail
base="${1:-}"
branch="${2:-}"
if [ -n "$base" ] && ! [[ "$base" =~ ^0+$ ]] && git cat-file -e "${base}^{commit}" 2>/dev/null; then
  echo "$base"
  exit 0
fi
head=$(git rev-parse HEAD)
if [ -n "$branch" ] && mb=$(git merge-base "origin/$branch" HEAD 2>/dev/null) && [ "$mb" != "$head" ]; then
  echo "::notice::база для diff: merge-base з origin/$branch ($mb)" >&2
  echo "$mb"
  exit 0
fi
if git rev-parse -q --verify 'HEAD^' >/dev/null; then
  echo "::notice::база для diff: HEAD^" >&2
  git rev-parse 'HEAD^'
  exit 0
fi
echo "::error::не знайдено бази для diff (перший коміт репо?)" >&2
exit 1
