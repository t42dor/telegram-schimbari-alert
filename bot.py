# ... imports la fel ...

print("DEBUG: Script pornit...")

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    print("DEBUG: Token lipsă!")
    raise RuntimeError("No token")

print(f"DEBUG: Token: {TOKEN[:10]}...")

ALERT_INTERVAL_SECONDS = int(os.getenv("ALERT_INTERVAL_SECONDS", "60"))
MAX_SITES_PER_USER = 5

# Conexiune principală pentru UI
db_ui = sqlite3.connect("data.db", check_same_thread=False)
cursor_ui = db_ui.cursor()

# Conexiune separată pentru monitor (async safe)
db_monitor = sqlite3.connect("data.db", check_same_thread=False)
cursor_monitor = db_monitor.cursor()

# Creează tabele (folosește cursor_ui)
cursor_ui.execute(
    "CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY, keyword TEXT, min_price INTEGER DEFAULT 0, max_price INTEGER DEFAULT 999999999, active INTEGER DEFAULT 1)"
)
cursor_ui.execute("CREATE TABLE IF NOT EXISTS seen (chat_id INTEGER, link TEXT)")
cursor_ui.execute(
    "CREATE TABLE IF NOT EXISTS user_sites (chat_id INTEGER, site TEXT, UNIQUE(chat_id, site))"
)
db_ui.commit()
print("DEBUG: Tabele create")

def ensure_user(chat_id: int) -> None:
    cursor_ui.execute(
        "INSERT OR IGNORE INTO users (chat_id, min_price, max_price, active) VALUES (?, 0, 999999999, 1)",
        (chat_id,),
    )
    db_ui.commit()
    print(f"DEBUG: User {chat_id} asigurat în DB")

def get_user_sites(chat_id: int) -> list[str]:
    cursor_monitor.execute(
        "SELECT site FROM user_sites WHERE chat_id=? ORDER BY rowid ASC", (chat_id,)
    )
    rows = cursor_monitor.fetchall()
    sites = [row[0] for row in rows]
    print(f"DEBUG: get_user_sites({chat_id}) → {len(sites)} site-uri: {sites}")
    return sites

# ... restul funcțiilor DB la fel, dar folosește cursor_ui și db_ui.commit() după fiecare operație ...

# În message_handler (add_site, remove_site etc.):
# Exemplu pentru add_site:
try:
    cursor_ui.execute(
        "INSERT INTO user_sites (chat_id, site) VALUES (?, ?)",
        (chat_id, text),
    )
    db_ui.commit()
    print(f"DEBUG: INSERT executat și commit pentru site {text}")
    context.user_data.pop("pending_action", None)
    await update.message.reply_text("Site adăugat ✔")
except sqlite3.IntegrityError:
    await update.message.reply_text("Site-ul există deja.")
except Exception as e:
    print(f"DEBUG: Eroare DB la add_site: {e}")
    await update.message.reply_text("Eroare la adăugare site.")

# În monitor loop:
async def monitor(app):
    while True:
        print("DEBUG: Ciclu monitor...")
        cursor_monitor.execute(
            "SELECT chat_id, keyword, min_price, max_price FROM users WHERE active=1"
        )
        users = cursor_monitor.fetchall()
        print(f"DEBUG: {len(users)} user-i activi găsiți: {[u[0] for u in users]}")

        # ... restul codului tău ...

        # Exemplu în for user:
        sites = get_user_sites(chat_id)  # folosește cursor_monitor
        if not sites:
            print(f"DEBUG: User {chat_id} fără site-uri în monitor")
            continue

        # ... scraping ...

        # La seen insert:
        cursor_monitor.execute(
            "INSERT INTO seen (chat_id, link) VALUES (?, ?)",
            (chat_id, href),
        )
        db_monitor.commit()
        print(f"DEBUG: Seen salvat pentru {href}")

        await asyncio.sleep(ALERT_INTERVAL_SECONDS)
