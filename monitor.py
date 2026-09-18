import os
import json
import hashlib
import difflib
from datetime import datetime

import requests
import urllib3
from bs4 import BeautifulSoup


# =========================================================
# MPESB HOMEPAGE MONITOR
# =========================================================

URL = "https://esb.mp.gov.in/e_default.html"
STATE_FILE = "esb_state.json"

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]


# Disable warning for MPESB SSL fallback
urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


# =========================================================
# HEADERS
# =========================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    api_url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        api_url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=40,
    )

    print("Telegram status:", response.status_code)
    print("Telegram response:", response.text)

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram API error: {result}"
        )

    print(
        "Telegram notification sent successfully."
    )


# =========================================================
# FETCH MPESB WEBSITE
# =========================================================

def fetch_website():

    cache_buster = datetime.now().strftime(
        "%Y%m%d%H%M%S%f"
    )

    url = (
        f"{URL}?_monitor={cache_buster}"
    )

    print("Checking MPESB website...")
    print("URL:", url)

    try:

        # First try normal secure SSL verification
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=45,
            verify=True,
        )

    except requests.exceptions.SSLError as ssl_error:

        print(
            "Normal SSL verification failed."
        )

        print(
            "Retrying with SSL verification disabled..."
        )

        print(
            "SSL error:",
            ssl_error
        )

        # MPESB server has SSL certificate
        # verification issue on GitHub runner.
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=45,
            verify=False,
        )

    response.raise_for_status()

    print(
        "Website status:",
        response.status_code
    )

    print(
        "Downloaded bytes:",
        len(response.content)
    )

    if len(response.content) < 1000:

        raise RuntimeError(
            "Website response is unexpectedly small."
        )

    return response.content


# =========================================================
# NORMALIZE WEBSITE CONTENT
# =========================================================

def normalize_html(content):

    soup = BeautifulSoup(
        content,
        "html.parser"
    )

    # Remove non-visible / dynamic code
    for tag in soup([
        "script",
        "style",
        "noscript",
        "svg"
    ]):

        tag.decompose()

    # -----------------------------------------------------
    # VISIBLE TEXT
    # -----------------------------------------------------

    text_lines = []

    for line in soup.get_text("\n").splitlines():

        line = " ".join(
            line.split()
        )

        if line:
            text_lines.append(line)

    visible_text = "\n".join(
        text_lines
    )

    # -----------------------------------------------------
    # ALL LINKS
    # -----------------------------------------------------

    links = []

    for a in soup.find_all("a"):

        title = " ".join(
            a.get_text(
                " ",
                strip=True
            ).split()
        )

        href = a.get(
            "href",
            ""
        ).strip()

        if href:

            links.append(
                f"{title} | {href}"
            )

    # Remove duplicate links
    links = sorted(
        set(links)
    )

    link_text = "\n".join(
        links
    )

    # -----------------------------------------------------
    # FINAL COMPARABLE CONTENT
    # -----------------------------------------------------

    comparable_content = (
        "VISIBLE TEXT\n"
        + visible_text
        + "\n\n"
        + "LINKS\n"
        + link_text
    )

    return comparable_content


# =========================================================
# HASH
# =========================================================

def make_hash(content):

    return hashlib.sha256(
        content.encode(
            "utf-8",
            errors="ignore"
        )
    ).hexdigest()


# =========================================================
# LOAD OLD STATE
# =========================================================

def load_state():

    if not os.path.exists(
        STATE_FILE
    ):

        return None

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception as error:

        print(
            "State file read error:",
            error
        )

        return None


# =========================================================
# SAVE STATE
# =========================================================

def save_state(content):

    state = {
        "url": URL,
        "hash": make_hash(content),
        "content": content,
        "checked_at": datetime.now().isoformat(),
    }

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        "Monitoring state saved."
    )


# =========================================================
# FIND CHANGES
# =========================================================

def find_changes(
    old_content,
    new_content
):

    old_lines = (
        old_content.splitlines()
    )

    new_lines = (
        new_content.splitlines()
    )

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="OLD",
        tofile="NEW",
        n=2,
    )

    added = []
    removed = []

    for line in diff:

        if line.startswith("+++"):
            continue

        if line.startswith("---"):
            continue

        if line.startswith("+"):

            value = line[1:].strip()

            if value:
                added.append(
                    value
                )

        elif line.startswith("-"):

            value = line[1:].strip()

            if value:
                removed.append(
                    value
                )

    return added, removed


# =========================================================
# CREATE TELEGRAM MESSAGE
# =========================================================

def create_notification(
    added,
    removed
):

    message = (
        "🚨 MPESB WEBSITE UPDATE!\n\n"
        "🌐 MPESB Homepage पर नया "
        "बदलाव मिला है।\n\n"
    )

    # -----------------------------------------------------
    # NEW / UPDATED CONTENT
    # -----------------------------------------------------

    if added:

        message += (
            "🆕 NEW / UPDATED:\n"
        )

        for item in added[:20]:

            message += (
                f"• {item}\n"
            )

        message += "\n"

    # -----------------------------------------------------
    # REMOVED / CHANGED CONTENT
    # -----------------------------------------------------

    if removed:

        message += (
            "❌ REMOVED / CHANGED:\n"
        )

        for item in removed[:10]:

            message += (
                f"• {item}\n"
            )

        message += "\n"

    # -----------------------------------------------------
    # WEBSITE LINK
    # -----------------------------------------------------

    message += (
        "🔗 MPESB Homepage:\n"
        "https://esb.mp.gov.in/e_default.html"
    )

    # Telegram message safety limit
    if len(message) > 3900:

        message = (
            message[:3900]
            + "\n..."
        )

    return message


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 60)

    print(
        "MPESB HOMEPAGE MONITOR STARTED"
    )

    print("=" * 60)

    # -----------------------------------------------------
    # FETCH WEBSITE
    # -----------------------------------------------------

    raw_content = fetch_website()

    # -----------------------------------------------------
    # NORMALIZE
    # -----------------------------------------------------

    new_content = normalize_html(
        raw_content
    )

    if not new_content.strip():

        raise RuntimeError(
            "No usable website content was found."
        )

    # -----------------------------------------------------
    # NEW HASH
    # -----------------------------------------------------

    new_hash = make_hash(
        new_content
    )

    print(
        "New website hash:",
        new_hash
    )

    # -----------------------------------------------------
    # LOAD OLD STATE
    # -----------------------------------------------------

    old_state = load_state()

    # =====================================================
    # FIRST RUN
    # =====================================================

    if old_state is None:

        print(
            "No previous snapshot found."
        )

        save_state(
            new_content
        )

        print(
            "First snapshot created."
        )

        print(
            "No Telegram notification "
            "on first run."
        )

        return

    # -----------------------------------------------------
    # OLD HASH
    # -----------------------------------------------------

    old_hash = old_state.get(
        "hash",
        ""
    )

    print(
        "Old website hash:",
        old_hash
    )

    # =====================================================
    # NO CHANGE
    # =====================================================

    if old_hash == new_hash:

        print(
            "✅ No website change detected."
        )

        save_state(
            new_content
        )

        return

    # =====================================================
    # CHANGE DETECTED
    # =====================================================

    print(
        "🚨 WEBSITE CHANGE DETECTED!"
    )

    old_content = old_state.get(
        "content",
        ""
    )

    # -----------------------------------------------------
    # FIND EXACT CHANGES
    # -----------------------------------------------------

    added, removed = find_changes(
        old_content,
        new_content
    )

    print(
        "Added/updated lines:",
        len(added)
    )

    print(
        "Removed/changed lines:",
        len(removed)
    )

    # -----------------------------------------------------
    # CREATE MESSAGE
    # -----------------------------------------------------

    message = create_notification(
        added,
        removed
    )

    print(
        "\nTelegram message:"
    )

    print(
        message
    )

    # =====================================================
    # SEND TELEGRAM FIRST
    # =====================================================

    # IMPORTANT:
    # New state will NOT be saved until Telegram
    # successfully sends the notification.

    send_telegram(
        message
    )

    # =====================================================
    # SAVE NEW STATE
    # =====================================================

    save_state(
        new_content
    )

    print(
        "✅ Update processed successfully."
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    main()
