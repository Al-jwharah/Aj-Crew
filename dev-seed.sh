#!/bin/bash
# Copy the Aj Crew data home into .ajcrew-dev/ for local development.
# Safe to re-run — wipes .ajcrew-dev first so you get a clean snapshot.
#
# Usage: ./dev-seed.sh
set -e

# The data home moved from the top-level ~/.ajcrew to ~/.kiro/crew. Prefer
# the current location; fall back to the legacy one for a box that still uses
# it so this script doesn't silently no-op.
if [ -d "$HOME/.kiro/crew" ]; then
  SRC="$HOME/.kiro/crew"
elif [ -d "$HOME/.ajcrew" ]; then
  SRC="$HOME/.ajcrew"
else
  SRC=""
fi
DST="$(cd "$(dirname "$0")" && pwd)/.ajcrew-dev"

if [ -z "$SRC" ]; then
  echo "No ~/.kiro/crew or ~/.ajcrew found — nothing to seed."
  exit 0
fi

if [ -d "$DST" ]; then
  # Refuse to rm -rf if .ajcrew-dev is a symlink (could follow to unrelated dir)
  if [ -L "$DST" ]; then
    echo "ERROR: .ajcrew-dev is a symlink — refusing to remove. Delete it manually."
    exit 1
  fi
  echo "Removing existing .ajcrew-dev/ ..."
  rm -rf "$DST"
fi

echo "Copying $SRC → .ajcrew-dev/ ..."
cp -R "$SRC" "$DST"

echo "Done. Start the gateway with:"
echo "  AJCREW_HOME=.ajcrew-dev bin/ajcrew gateway"
