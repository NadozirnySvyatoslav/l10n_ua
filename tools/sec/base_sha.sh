#!/usr/bin/env bash
# Друкує базу для diff перевірок шлюзу. Аргументи: <BASE_SHA> [<базова гілка>] [<голова PR>].
# - PR: actions/checkout бере merge-коміт refs/pull/N/merge (PR поверх СВІЖОЇ базової гілки), а
#   pull_request.base.sha лишається з моменту відкриття PR. Diff від нього тягне в PR усе, що
#   влили в базову гілку відтоді. Тому, якщо HEAD — merge-коміт, другий батько якого = голова PR,
#   база = перший батько (свіжа голова базової гілки).
# - push нової гілки (before = 000…0) або force-push (коміта немає в історії): merge-base з
#   базовою гілкою; якщо він збігається з HEAD (push самої базової гілки) або його немає — HEAD^.
set -euo pipefail
base="${1:-}"
branch="${2:-}"
pr_head="${3:-}"
head=$(git rev-parse HEAD)
if [ -n "$pr_head" ] && p2=$(git rev-parse -q --verify 'HEAD^2') && [ "$p2" = "$(git rev-parse "$pr_head")" ]; then
  echo "::notice::база для diff: перший батько merge-коміту PR" >&2
  git rev-parse 'HEAD^1'
  exit 0
fi
if [ -n "$base" ] && ! [[ "$base" =~ ^0+$ ]] && git cat-file -e "${base}^{commit}" 2>/dev/null; then
  echo "$base"
  exit 0
fi
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
