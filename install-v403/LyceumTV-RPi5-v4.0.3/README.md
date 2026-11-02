# LyceumTV 4.0 — Raspberry Pi 5

Єдине офіційне джерело коду та програмних оновлень:
**https://github.com/salenko93-hash/LiceumTVRPi5-0.18**.

TV Display: дві таблиці по чотири класи, поділ на групи, заміни, черговий клас,
календар, погода та повноекранна повітряна тривога. DEMO використовує той самий
рендерер із тестовими даними та не запускає звук. Версія інтерфейсу/релізу —
4.0.1; сумісна внутрішня версія API — 3.6.1.

## Публічні дані

Репозиторій і Release не містять робочих ключів, конфігурації, медіатеки,
backup, приватних XLSX, реальних розкладів або прізвищ викладачів.
`data/default` — порожні стартові розклади. `public/preview-data` і
`tests/fixtures` — явно синтетичні приклади, які не є робочим розкладом.
Після першого встановлення адміністратор імпортує приватні дані локально.
Налаштування й токени вводяться на Pi; не додавайте їх у Git або чат.

## Перше встановлення

Raspberry Pi OS 64-bit, Raspberry Pi 5, Python 3.10+, SSH та звичайний користувач
із sudo. До встановлення зробіть образ SD/диска й збережіть поза пристроєм.
Використовуйте **версійний Release ZIP**, а не GitHub Source code ZIP.

Для v4.0.1 на Pi:

```bash
curl -fLO https://github.com/salenko93-hash/LiceumTVRPi5-0.18/releases/download/v4.0.1/LyceumTV-RPi5-v4.0.1.zip
curl -fLO https://github.com/salenko93-hash/LiceumTVRPi5-0.18/releases/download/v4.0.1/LyceumTV-RPi5-v4.0.1.zip.sha256
sha256sum -c LyceumTV-RPi5-v4.0.1.zip.sha256
unzip LyceumTV-RPi5-v4.0.1.zip
cd LyceumTV-RPi5-v4.0.1
bash scripts/install_air_raid.sh 192.168.0.18
```

У Windows розпакуйте перевірений ZIP у порожню папку, перевірте hash через
`Get-FileHash`, потім виконайте `INSTALL_AIR_RAID_RPI5.ps1 -PiHost 192.168.0.18 -PiUser admin`.
Вкажіть фактичну адресу/користувача свого Pi. Скрипт запитає INSTALL.

Перед встановленням виконайте -CheckOnly. Повна діагностика, політика безпечної
підготовки, журналювання й recovery описані в [інструкції v4.0.1](docs/INSTALLER_V4_0_1.md).
Оновлення використовує verified data backup та code transaction з автоматичним
відкатом; повний provisioning виконується лише на чистій системі.

Встановлення налаштовує службових користувачів, systemd, nginx/HTTPS і kiosk.
Секрети створюються локально; отримати ключі ролей можна тільки через
`sudo /usr/local/sbin/lyceumtv-show-keys`. Немає стандартних паролів у репозиторії.

## Оновлення: перевірити за замовчуванням, застосувати лише з дозволу

Після встановлення timer `lyceumtv-official-check.timer` перевіряє Release кожні
6 годин. Він лише читає GitHub і пише результат у journal, **ніколи не встановлює**.

```bash
sudo -u lyceumtv python3 -B /opt/lyceumtv/server/official_updates.py check
journalctl -u lyceumtv-official-check.service --no-pager
```

Окреме адміністративне застосування конкретної перевіреної версії:

```bash
sudo -u lyceumtv python3 -B /opt/lyceumtv/server/official_updates.py apply --tag v4.0.1 --approve
```

Updater приймає тільки Release assets цього репозиторію, перевіряє успішний
`verify.yml` для commit тега, зовнішній SHA-256, внутрішній файловий manifest,
Python-синтаксис, безпечні ZIP-шляхи та repository/version metadata.
Завантаження й verified data backup виконуються при працюючому сервері.
Лише потім створюється транзакція; supervisor зупиняє застосунок безпосередньо
для заміни коду. Три послідовні health-check потрібні для прийняття; інакше
автоматично повертається попередній code snapshot.

`data/default`, `data/current`, конфігурація, локальні override, імпорти,
медіафайли та backups не входять у code transaction і не переписуються
даними репозиторію. Ручні private schedule providers — окремі локальні
налаштування, вони не є джерелом програмних релізів. Старий signed OTA також
обмежений офіційним джерелом; вимогу Ed25519-підпису не послаблено.

## Відкат

Повернення останнього code snapshot через той самий supervisor:

```bash
sudo -u lyceumtv python3 -B /opt/lyceumtv/server/official_updates.py rollback --approve
curl -fsS http://127.0.0.1:8080/api/health
```

Якщо модуль нового updater недоступний:

```bash
sudo -u lyceumtv python3 -B /opt/lyceumtv/server/update_transaction.py --root /opt/lyceumtv --rollback
```

Code rollback зберігає поточні приватні дані. Data backup знаходиться в
`/opt/lyceumtv/data/backups`; full-install backups — `/var/backups/lyceumtv`.
Для повернення full-install копії: зупинити LyceumTV timers/workers/server/kiosk,
перевірити gzip/tar, перемістити невдалий `/opt/lyceumtv` в окремий каталог,
розпакувати точну перевірену pre-install копію в `/opt`, повернути необхідні
system files зі snapshot, виконати daemon-reload та перевірити health.
Це не downgrade ОС/apt; для повного ідентичного стану використовуйте образ SD.
`/legacy-tv` — лише інша сторінка, не відкат коду.

## DEMO й перевірки

```bash
python3 -B tools/serve_tv_preview.py --port 8094
```

Відкрити `http://127.0.0.1:8094/demo.html`. Дев'ять сценаріїв: урок, перерва,
чисельник, знаменник, заміна, групи, черговий клас, канікули, тривога.

```bash
python3 -m pip install -r requirements.txt
python3 -B VERIFY_PROJECT.py
python3 -B tools/check_public_distribution.py
npm install --prefix .preview-tools --no-save --package-lock=false playwright@1.64.1
npx --prefix .preview-tools playwright install --with-deps chrome
NODE_PATH=.preview-tools/node_modules node tests/browser_demo_tv_display.cjs
NODE_PATH=.preview-tools/node_modules node tests/browser_tv_display_preview.cjs
NODE_PATH=.preview-tools/node_modules node tests/browser_tv_display_install.cjs
NODE_PATH=.preview-tools/node_modules node tests/browser_air_raid.cjs
```

GitHub Actions виконує ці перевірки на кожному push/PR. Привілейовані opt-in
systemd/backup перевірки потребують окремого ізольованого runner; фізичні ARM64,
HDMI, чутність і autoplay потрібно прийняти на реальному Pi після дозволу.
Жоден локальний чи CI тест не встановлює оновлення на робочий Raspberry Pi.
