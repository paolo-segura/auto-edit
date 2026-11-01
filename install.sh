#!/bin/bash
# Auto Edit installer for Mac. Safe to run again: it updates what's there.
set -euo pipefail

REPO="${AUTO_EDIT_REPO:-https://github.com/paolo-segura/auto-edit.git}"
DIR="$HOME/.auto-edit"

say() { printf '\n==> %s\n' "$1"; }
die() { printf '\nInstall stopped: %s\n' "$1" >&2; exit 1; }

[ "$(uname)" = "Darwin" ] || die "this version is Mac only."

say "Checking Homebrew (installs the video tools; it may ask for your Mac password)"
if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && eval "$("$b" shellenv)"
  done
fi
if ! command -v brew >/dev/null 2>&1; then
  # This script arrives through a pipe, so point Homebrew at the keyboard or it can't ask for a password.
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" < /dev/tty
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$b" ]; then
      eval "$("$b" shellenv)"
      grep -qs "brew shellenv" "$HOME/.zprofile" || echo "eval \"\$($b shellenv)\"" >> "$HOME/.zprofile"
    fi
  done
fi
command -v brew >/dev/null 2>&1 || die "Homebrew didn't install. See https://brew.sh"

say "Installing ffmpeg, Node, speech recognition and Python"
for pkg in git ffmpeg node whisper-cpp python@3.14; do
  brew list --formula "$pkg" >/dev/null 2>&1 || brew install "$pkg"
done

say "Downloading Auto Edit to $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  [ ! -e "$DIR" ] || die "$DIR already exists and isn't an Auto Edit install. Move it, then run this again."
  git clone --depth 1 "$REPO" "$DIR"
fi

say "Setting up"
"$(brew --prefix python@3.14)/bin/python3.14" -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install --quiet --disable-pip-version-check -r "$DIR/requirements.txt"
(cd "$DIR" && npm ci --silent --no-fund --no-audit)
"$DIR/node_modules/.bin/hyperframes" browser ensure

BIN="${AUTO_EDIT_BIN:-$(brew --prefix)/bin/autoedit}"
cat > "$BIN" <<EOF
#!/bin/bash
export PATH="$(brew --prefix)/bin:\$PATH"
exec "$DIR/.venv/bin/python" "$DIR/autoedit.py" "\$@"
EOF
chmod +x "$BIN"

DESKTOP="$HOME/Desktop/Auto Edit.command"
if [ -d "$HOME/Desktop" ]; then
  cat > "$DESKTOP" <<EOF
#!/bin/bash
"$BIN"
echo
read -r -p "Press Enter to close. " _
EOF
  chmod +x "$DESKTOP"
fi

if [ -d "$HOME/.claude" ]; then
  mkdir -p "$HOME/.claude/skills/auto-edit"
  cp "$DIR/skill/auto-edit/SKILL.md" "$HOME/.claude/skills/auto-edit/SKILL.md"
  CLAUDE_NOTE="Claude Code found: you can also say \"edit this video\" there."
else
  CLAUDE_NOTE=""
fi

say "Checking everything works"
"$BIN" doctor || die "something is missing. See the lines marked NO above."

cat <<EOF

All set. Double-click "Auto Edit" on your Desktop, or run: autoedit myvideo.mov
$CLAUDE_NOTE
EOF
