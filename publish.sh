#!/usr/bin/env bash
# Create the GitHub repository and push this project to it.
#
# The token is read from the terminal without echoing, passed to git and curl
# through the environment, and never written to .git/config, to shell history,
# or to any file. Nothing about it is stored after this script exits.
#
#   ./publish.sh            private repo (default)
#   ./publish.sh --public   public repo
set -euo pipefail
cd "$(dirname "$0")"

USER=mohamadassi2
REPO=hwsw-codesign-project
PRIVATE=true
[ "${1:-}" = "--public" ] && PRIVATE=false

command -v curl >/dev/null || { echo "curl is required"; exit 1; }
[ -n "$(git status --porcelain)" ] && { echo "working tree is dirty; commit first"; exit 1; }

printf 'GitHub token for %s (input hidden): ' "$USER"
read -rs GH_TOKEN; echo
[ -n "$GH_TOKEN" ] || { echo "no token given"; exit 1; }
export GH_TOKEN

echo "==> checking the token"
who=$(curl -sS -H "Authorization: Bearer $GH_TOKEN" https://api.github.com/user | sed -n 's/.*"login"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
[ -n "$who" ] || { echo "the token was rejected by GitHub"; exit 1; }
echo "    authenticated as $who"

echo "==> creating $USER/$REPO (private=$PRIVATE)"
code=$(curl -sS -o /tmp/ghresp.$$ -w '%{http_code}' -X POST \
  -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
  https://api.github.com/user/repos \
  -d "{\"name\":\"$REPO\",\"private\":$PRIVATE,\"description\":\"Technion 00460882 final project: optimizing two pyperformance benchmarks and a canonical-Huffman accelerator in SystemVerilog\",\"has_issues\":false,\"has_wiki\":false}")
if [ "$code" = "201" ]; then echo "    created"
elif grep -q "name already exists" /tmp/ghresp.$$ 2>/dev/null; then echo "    already exists, reusing it"
else echo "    failed (HTTP $code):"; head -5 /tmp/ghresp.$$; rm -f /tmp/ghresp.$$; exit 1; fi
rm -f /tmp/ghresp.$$

git remote set-url origin "https://github.com/$USER/$REPO.git" 2>/dev/null \
  || git remote add origin "https://github.com/$USER/$REPO.git"

echo "==> pushing $(git rev-list --count HEAD) commits"
git -c credential.helper= \
    -c credential.helper='!f() { echo username=x-access-token; echo "password=$GH_TOKEN"; }; f' \
    push -u origin main

unset GH_TOKEN
echo
echo "done: https://github.com/$USER/$REPO"
