#!/usr/bin/env bash
# Turns this folder into a git repo, commits it as YOU, and (optionally) creates the GitHub repo and pushes.
#   ./scripts/publish.sh                    private repo named "toastfx"
#   ./scripts/publish.sh --public           public repo
#   ./scripts/publish.sh --name my-name     different repo name
#   ./scripts/publish.sh --no-github        only make the local git commit
set -euo pipefail
cd "$(dirname "$0")/.."
NAME=toastfx; VIS=--private; GH=1
while [ $# -gt 0 ]; do
  case "$1" in
    --public) VIS=--public ;;
    --private) VIS=--private ;;
    --name) NAME="$2"; shift ;;
    --no-github) GH=0 ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac; shift
done
command -v git >/dev/null || { echo "Install git first: sudo apt install git"; exit 1; }

AUTHOR="$(git config user.name || true)"
if [ -z "$AUTHOR" ]; then
  read -r -p "Your name for the license and commits: " AUTHOR
  git config --global user.name "$AUTHOR"
fi
if [ -z "$(git config user.email || true)" ]; then
  read -r -p "Your email (a GitHub no-reply address is fine): " EM
  git config --global user.email "$EM"
fi
sed -i "s/__AUTHOR__/$AUTHOR/" LICENSE

[ -d .git ] || git init -q -b main
git add -A
if git diff --cached --quiet; then echo "Nothing new to commit."; else
  git commit -q -m "Initial release: ToastFX voice effects, soundboard, hotkeys, .deb builder

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
  echo "Committed."
fi

if [ "$GH" = 1 ]; then
  command -v gh >/dev/null || { echo "Install the GitHub CLI: sudo apt install gh   (then run this again)"; exit 1; }
  gh auth status >/dev/null 2>&1 || { echo "Log in to GitHub (opens a browser):"; gh auth login; }
  if git remote get-url origin >/dev/null 2>&1; then git push -u origin main
  else gh repo create "$NAME" $VIS --source=. --remote=origin --push --description "Real-time voice changer and soundboard for Linux (PipeWire)"
  fi
  echo; gh repo view --web 2>/dev/null || true
fi
