from __future__ import annotations
from version import VERSION
import hashlib
import json
import os
import shutil
import ssl
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CURRENT = DATA / "current"
DEFAULT = DATA / "default"
REQUIRED = [
    "schedule_numerator.json",
    "schedule_denominator.json",
    "shelter_numerator.json",
    "shelter_denominator.json",
]


# Separate, explicitly approved repositories for application releases and
# schedule/content manifests. Never use the update-feed repository for OTA code.
ALLOWED_CONTENT_REPOSITORIES = (
    "salenko93-hash/LiceumTVRPi5-0.18",
    "salenko93-hash/lyceumtv-updates",
)


def _https_only(url: str) -> None:
    parsed = urlsplit(str(url))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Дозволено лише HTTPS URL без вбудованих облікових даних")
    # GitHub content remains pinned to the two repositories controlled by
    # this deployment; other GitHub repositories are rejected explicitly.
    github_prefixes = {
        "github.com": tuple("/" + repo + "/" for repo in ALLOWED_CONTENT_REPOSITORIES),
        "raw.githubusercontent.com": tuple("/" + repo + "/" for repo in ALLOWED_CONTENT_REPOSITORIES),
        "api.github.com": tuple("/repos/" + repo + "/" for repo in ALLOWED_CONTENT_REPOSITORIES),
    }
    if parsed.hostname in github_prefixes and not any(
        parsed.path.startswith(prefix) for prefix in github_prefixes[parsed.hostname]
    ):
        raise ValueError("GitHub content source is not an approved LyceumTV repository")


def _download(url: str, timeout: int = 20) -> bytes:
    _https_only(url)
    req = Request(
        url,
        headers={"User-Agent": f"LyceumTV-RPi/{VERSION}", "Accept": "application/json"},
    )
    with urlopen(
        req, timeout=timeout, context=ssl.create_default_context()
    ) as response:
        if hasattr(response,'geturl'):
            _https_only(response.geturl())
        if (
            getattr(response, "status", 200) < 200
            or getattr(response, "status", 200) >= 300
        ):
            raise RuntimeError(f"HTTP {response.status}")
        return response.read()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_schedule(name: str, raw: bytes) -> None:
    obj = json.loads(raw.decode("utf-8"))
    if obj.get("placeholder"):
        raise ValueError(f"{name}: placeholder")
    bells, days = obj.get("bellSchedule"), obj.get("days")
    if not isinstance(bells, list) or not bells or not isinstance(days, dict):
        raise ValueError(f"{name}: invalid schema")
    for day in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"):
        if day not in days or not isinstance(days[day], dict):
            raise ValueError(f"{name}: missing {day}")


def _validate_calendar(raw: bytes) -> None:
    obj = json.loads(raw.decode("utf-8"))
    if "daysOff" not in obj or "ranges" not in obj:
        raise ValueError("calendar.json: invalid schema")


def _validate_content(raw: bytes) -> None:
    obj = json.loads(raw.decode("utf-8"))
    if not any(
        k in obj for k in ("announcements", "substitutions", "events", "schedule")
    ):
        raise ValueError("content.json: no supported fields")


def sync_bundle(
    manifest_url: str,
    sheets_url: str = "",
    pin_local_denominator: bool = False,
    pinned_schedules: list[str] | None = None,
) -> dict[str, Any]:
    _https_only(manifest_url)
    manifest_raw = _download(manifest_url)
    manifest = json.loads(manifest_raw.decode("utf-8"))
    schedules = manifest.get("schedules")
    if not isinstance(schedules, dict):
        raise ValueError("Manifest schedules missing")
    base_url = manifest_url.rsplit("/", 1)[0] + "/"

    pinned = {
        str(x).strip().removesuffix(".json")
        for x in (pinned_schedules or [])
        if str(x).strip()
    }
    if pin_local_denominator:
        pinned.add("schedule_denominator")

    stage = Path(tempfile.mkdtemp(prefix="lyceumtv-sync-", dir=str(DATA)))
    try:
        for name in REQUIRED:
            stem = name.removesuffix(".json")
            if stem in pinned:
                raw = (DEFAULT / name).read_bytes()
                _validate_schedule(name, raw)
                (stage / name).write_bytes(raw)
                continue
            item = schedules.get(name)
            if not isinstance(item, dict):
                raise ValueError(f"Manifest missing {name}")
            raw = _download(urljoin(base_url, str(item["url"])))
            expected = str(item.get("sha256", "")).lower()
            if len(expected) != 64 or _sha256(raw) != expected:
                raise ValueError(f"{name}: SHA-256 mismatch")
            _validate_schedule(name, raw)
            (stage / name).write_bytes(raw)

        cal_item = manifest.get("calendar")
        if isinstance(cal_item, dict):
            raw = _download(urljoin(base_url, str(cal_item["url"])))
            if _sha256(raw) != str(cal_item.get("sha256", "")).lower():
                raise ValueError("calendar.json: SHA-256 mismatch")
            _validate_calendar(raw)
            (stage / "calendar.json").write_bytes(raw)
        else:
            shutil.copy2(DEFAULT / "calendar.json", stage / "calendar.json")

        content_item = manifest.get("content")
        if isinstance(content_item, dict):
            raw = _download(urljoin(base_url, str(content_item["url"])))
            if _sha256(raw) != str(content_item.get("sha256", "")).lower():
                raise ValueError("content.json: SHA-256 mismatch")
            _validate_content(raw)
            (stage / "content.json").write_bytes(raw)
        else:
            shutil.copy2(DEFAULT / "content.json", stage / "content.json")

        # Google Apps Script is authoritative only for content/announcements if configured.
        if str(sheets_url or "").strip():
            raw = _download(str(sheets_url).strip())
            _validate_content(raw)
            (stage / "content.json").write_bytes(raw)

        (stage / "content_manifest.json").write_bytes(manifest_raw)

        previous = DATA / "previous"
        if previous.exists():
            shutil.rmtree(previous)
        if CURRENT.exists():
            os.replace(CURRENT, previous)
        os.replace(stage, CURRENT)
        pin_note = ""
        if pinned:
            pin_note = " • локально закріплено: " + ", ".join(sorted(pinned))
        return {
            "ok": True,
            "version": str(manifest.get("version", "")),
            "message": "Синхронізація завершена; SHA-256 і JSON перевірені" + pin_note,
            "pinned": sorted(pinned),
        }
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
