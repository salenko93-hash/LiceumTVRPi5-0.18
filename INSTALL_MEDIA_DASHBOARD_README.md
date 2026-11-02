# LyceumTV Media Dashboard — installation notes

This package is a DEVELOPMENT / LOCAL RELEASE candidate built from v4.0.1; release candidate 4.0.2 with an optional media dashboard. It is not an official GitHub Release and has NOT passed physical Raspberry Pi acceptance.

## Windows preview (no installation)
Run START_DEMO_WINDOWS.bat (requires Python) then open http://127.0.0.1:8094/media-dashboard.html?demo=1 .

## Integration
The new mode is at /media-dashboard.html. Existing TV Display and alert logic remain separate. To edit content, use the media-dashboard tab in /admin.html on the running LyceumTV application after administrator authentication. The server stores data/media_dashboard.json locally. Use only existing local media paths under /media/.

## Installation policy
Do not use the old immutable v4.0.1 GitHub Release name for this modified candidate. The installer requires a verified backup, successful Pi diagnostics, and explicit approval. First inspect the release sources and apply an official signed/tagged release process from https://github.com/salenko93-hash/LiceumTVRPi5-0.18 before production deployment. Do NOT copy a development candidate over a live /opt/lyceumtv installation.

## Validation
Run python -B VERIFY_PROJECT.py, then python -B scripts/release_preflight.py --root . . Physical display, audio, alert priority and admin auth require acceptance on actual Pi.
