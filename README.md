# telegram-schimbari-alert

Bot Telegram pentru monitorizare anunțuri cu Playwright.

## Ce face acum
- Configurare din butoane Telegram.
- Monitorizare pe **maxim 5 site-uri** per utilizator.
- Filtrare după keyword și interval de preț.
- Alertă doar pentru link-uri noi (deduplicare în SQLite).

## Configurare rapidă
1. Setează variabila `TELEGRAM_TOKEN`.
2. Opțional setează `ALERT_INTERVAL_SECONDS` (implicit 60).
3. Rulează botul:

```bash
python bot.py
```

În Telegram:
- `/start`
- `Add Site` (repetă până la 5)
- `Set Keyword`
- `Set Price`
- `Start Alerts`
