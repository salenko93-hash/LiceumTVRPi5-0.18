#!/usr/bin/env bash
set -Eeuo pipefail

SCREEN_ID="${LYCEUMTV_SCREEN_ID:-main-hall}"
URL="${LYCEUMTV_URL:-http://127.0.0.1:8080/?screen=$SCREEN_ID}"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [[ ! -d "$XDG_RUNTIME_DIR" || ! -w "$XDG_RUNTIME_DIR" || ! -x "$XDG_RUNTIME_DIR" ]]; then
  echo "Kiosk cannot write XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR. Check ProtectHome=tmpfs and BindPaths in lyceumtv-kiosk.service." >&2
  exit 1
fi
if [[ $(stat -c %u -- "$XDG_RUNTIME_DIR") != "$(id -u)" || $(stat -c %a -- "$XDG_RUNTIME_DIR") != 700 ]]; then
  echo "Kiosk runtime directory must belong to the kiosk user and have mode 0700: $XDG_RUNTIME_DIR" >&2
  exit 1
fi
if ! runtime_probe=$(mktemp "$XDG_RUNTIME_DIR/.lyceumtv-runtime-XXXXXX"); then
  echo "Kiosk cannot create files in XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR; Wayland cannot start." >&2
  exit 1
fi
rm -f -- "$runtime_probe"

# IMPORTANT: this profile is intentionally separate from old Chromium/Desktop
# profiles that may have been encrypted using GNOME/Default Keyring.
PROFILE_DIR="${HOME}/.config/lyceumtv-kiosk-chromium"
mkdir -p "$PROFILE_DIR"
chmod 700 "$PROFILE_DIR" 2>/dev/null || true

# Disable the translation bubble in this dedicated profile, preserving other prefs.
# Chromium's native sandbox/security flags remain unchanged.
python3 - "$PROFILE_DIR" <<'KIOSK_PROFILE'
import json, os, pathlib, sys, uuid
profile = pathlib.Path(sys.argv[1]) / "Default"
profile.mkdir(parents=True, exist_ok=True)
path = profile / "Preferences"
value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
if not isinstance(value, dict):
    raise SystemExit("Invalid kiosk Preferences; preserve and repair the profile before retrying")
for key in ("translate", "intl"):
    if not isinstance(value.get(key), dict):
        value[key] = {}
value["translate"]["enabled"] = False
value["intl"]["accept_languages"] = "uk,en"
value["intl"]["selected_languages"] = "uk,en"
stage = path.with_name("Preferences." + uuid.uuid4().hex + ".tmp")
try:
    stage.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    stage.chmod(0o600)
    os.replace(stage, path)
finally:
    stage.unlink(missing_ok=True)
KIOSK_PROFILE

# A hard power-off can leave Chromium singleton locks. They are safe to
# remove before this dedicated single-browser kiosk starts.
rm -f \
  "$PROFILE_DIR/SingletonLock" \
  "$PROFILE_DIR/SingletonCookie" \
  "$PROFILE_DIR/SingletonSocket" 2>/dev/null || true

for _ in $(seq 1 90); do
  if curl -fsS --max-time 1 http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

BROWSER=""
for b in chromium chromium-browser; do
  if command -v "$b" >/dev/null 2>&1; then
    BROWSER="$(command -v "$b")"
    break
  fi
done

if [[ -z "$BROWSER" ]]; then
  echo "Chromium not found" >&2
  exit 1
fi

export LIBSEAT_BACKEND=logind

# --password-store=basic is the key setting: Chromium does not request
# GNOME/Default Keyring for password encryption. LyceumTV does not save
# browser passwords, so the basic store has no useful secrets to protect.
exec /usr/bin/cage -- "$BROWSER" \
  --ozone-platform=wayland \
  --enable-features=UseOzonePlatform \
  --force-device-scale-factor=1 \
  --force-color-profile=srgb \
  --kiosk \
  --start-fullscreen \
  --no-first-run \
  --no-default-browser-check \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --password-store=basic \
  --disable-sync \
  --disable-save-password-bubble \
  --disable-features=Translate,TranslateUI,MediaRouter,PasswordManagerOnboarding,AutofillServerCommunication \
  --disable-translate \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --autoplay-policy=no-user-gesture-required \
  --user-data-dir="$PROFILE_DIR" \
  --lang=uk-UA \
  "$URL"
