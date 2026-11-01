# v4.0.1 — перевірки інсталятора

Межа оцінки: локальна публічна копія, ізольований Linux-контейнер, Windows
PowerShell, Chrome Full HD. Робочий Raspberry Pi не підключався і не оновлювався.
Результат програмних сценаріїв PASS; приймання на реальному Pi — PARTIAL.

## Сценарії

| Вимога | Виконана перевірка |
| --- | --- |
| Чиста інсталяція | `test_installer`: оркестрація в тимчасовому дереві, backup перед backend; `test_install_storage`: реальне створення каталогів і конфігурації у Linux |
| Оновлення | `test_installer_upgrade`: verified backup перед prepare; `test_update_transaction`: реальні процеси supervisor і заміна коду |
| Відсутній ota_pending | `test_upgrade_missing_ota_pending_is_normal`; файл не створюється |
| Власник/права | Відмова без chown/chmod; створення лише відсутніх allowlisted каталогів; symlink відхиляється |
| Сторонній ZIP/IDE | `.idea/.gitignore` ігнорується й не передається; невідомий код, tamper, path traversal відхиляються |
| Немає SSH | PowerShell: відсутній binary та Connection refused блокують upload/install |
| Немає місця | Одночасний звіт DISK, BACKUP_SPACE, SERVICE_ACCESS, CONFIG |
| Backup failure | Немає встановлення/prepare; baseline gzip/tar/SHA перевірені |
| Health failure | Код ізольовано на clean install; попередній code snapshot відновлено на upgrade |
| Rollback | Health mismatch, частковий copy, interrupted job, ручний rollback; приватні дані незмінні |
| Повторний запуск | Каталоги створюються один раз; кожна дозволена транзакція потребує нового verified backup; невідома partial install блокується |
| CheckOnly і logs | Немає встановлення або зупинки служб; конкретна причина та етап у журналі; secrets masked; тимчасові каталоги очищені |

Тести первинного встановлення не виконують справжній apt, nginx, systemd або
зміни користувачів ОС: backend і SSH ізольовано/імітуються. Це перевірка логіки,
а не підтвердження успішного встановлення на фізичний Pi.

## Набори

- Python unittest: повний discovery у Linux і через `VERIFY_PROJECT.py` у Windows;
  детальний список і результат кожного тесту друкується штатним runner `-v`.
- Linux Bash: `bash -n` для всіх `scripts/*.sh`.
- PowerShell: `tests/test_installer_powershell.ps1`, 14 перевірок, справжній pwsh,
  SSH/SCP замокані; мережевих звернень до Raspberry Pi немає.
- JavaScript: 8 runtime regression checks через `VERIFY_PROJECT.py`.
- Браузер: `browser_demo_tv_display.cjs` (12), `browser_tv_display_preview.cjs`
  (13), `browser_tv_display_install.cjs` (9), `browser_air_raid.cjs` (10).
  Урок, перерва, чисельник/знаменник, групи, заміна, черговий клас, канікули,
  вихідний, погода, offline cache, невідомий статус, тривога/відбій та програмне
  відтворення звукових подій; звичайні слайди не перекривають попередження.
- Реліз: privacy gate, manifest/hash, ZIP CRC, SHA-256 і повторний
  `VERIFY_PROJECT.py` після розпакування через `tools/build_official_release.py --verify`.
- CI: Linux verification/build/browser і окрема Windows PowerShell job.

## Невиконане та обмеження

Шість opt-in Linux-тестів потребують привілейованого systemd/root runner і
пропускаються з явною причиною. У Windows додатково пропускаються POSIX-перевірки
прав і supervisor. Не виконувались фізичні HDMI/аудіо та фактичне встановлення
ОС-пакетів на Pi. Ruff у локальному Python не встановлений; цей додатковий lint
не оголошується пройденим.

Windows TCP-тест початково отримував WinError 10053 замість HTTP 503 при закритті
перевантаженого сокета з непрочитаним запитом. Тест уточнено лише для Windows:
допускається reset/reject, а звільнення слоту і наступна HTTP 200 перевіряються
додатково. Linux і далі зобов'язаний повертати HTTP 503. Production HTTP-код
не змінювався. Повторний повний Windows runner пройшов.

Невстановлений текст останньої історичної помилки не видається за знайдену
причину: потрібний новий redacted log або попередній журнал із Pi.
