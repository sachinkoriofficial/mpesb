import os
import json
import hashlib
import difflib
from datetime import datetime

import requests
from bs4 import BeautifulSoup


# ==============================
# MPESB WEBSITE MONITOR
# ==============================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", "397982523")

URLS = {
    "MPESB Home": "https://esb.mp.gov.in/e_default.html",
    "MPESB Rulebooks": "https://esb.mp.gov.in/rulebooks/rule_books.htm",
}

STATE_FILE = "esb_state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}


def get_page(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=40
    )
    response.raise_for_status()
    return response.text


def parse_page(html, base_url):
    soup = BeautifulSoup(html, "html.parser")

    # Remove unnecessary elements
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Get visible text
    text = soup.get_text(" ", strip=True)

    # Clean spaces
    text = " ".join(text.split())

    # Collect links
    links = []

    for a in soup.find_all("a", href=True):
        title = a.get_text(" ", strip=True)
        href = a.get("href", "").strip()

        if not href:
            continue

        if href.startswith("http"):
            full_url = href
        elif href.startswith("/"):
            from urllib.parse import urljoin
            full_url = urljoin(base_url, href)
        else:
            from urllib.parse import urljoin
            full_url = urljoin(base_url, href)

        links.append({
            "title": title,
            "url": full_url
        })

    # Remove duplicates
    unique_links = []
    seen = set()

    for item in links:
        key = (item["title"], item["url"])

        if key not in seen:
            seen.add(key)
            unique_links.append(item)

    return text, unique_links


def make_hash(text):
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


def send_telegram(message):
    if not BOT_TOKEN:
        print("BOT_TOKEN is missing.")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": False
    }

    response = requests.post(
        url,
        data=payload,
        timeout=30
    )

    if response.status_code != 200:
        print("Telegram Error:", response.text)
        return False

    return True


def get_changes(old_links, new_links):
    old_set = {
        (x["title"], x["url"])
        for x in old_links
    }

    new_set = {
        (x["title"], x["url"])
        for x in new_links
    }

    added = new_set - old_set
    removed = old_set - new_set

    return added, removed


def text_difference(old_text, new_text):
    old_words = old_text.split()
    new_words = new_text.split()

    diff = list(
        difflib.unified_diff(
            old_words,
            new_words,
            n=8
        )
    )

    changes = []

    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            changes.append(line[1:])

    # Keep notification short
    result = " ".join(changes)

    if len(result) > 900:
        result = result[:900] + "..."

    return result


def monitor():

    print("=" * 60)
    print("MPESB WEBSITE MONITOR")
    print(datetime.now().strftime("%d-%m-%Y %I:%M:%S %p"))
    print("=" * 60)

    old_state = load_state()
    new_state = {}

    all_changes = []

    for name, url in URLS.items():

        print(f"\nChecking: {name}")
        print(url)

        try:
            html = get_page(url)

            text, links = parse_page(
                html,
                url
            )

            current_hash = make_hash(text)

            new_state[name] = {
                "hash": current_hash,
                "text": text,
                "links": links,
                "checked": datetime.now().isoformat()
            }

            # First run
            if name not in old_state:
                print("Initial snapshot created.")
                continue

            old_page = old_state[name]

            old_hash = old_page.get("hash")
            old_links = old_page.get("links", [])
            old_text = old_page.get("text", "")

            if old_hash == current_hash:
                print("No change.")
                continue

            print("CHANGE DETECTED!")

            added, removed = get_changes(
                old_links,
                links
            )

            text_change = text_difference(
                old_text,
                text
            )

            all_changes.append({
                "name": name,
                "url": url,
                "added": added,
                "removed": removed,
                "text_change": text_change
            })

        except Exception as e:

            print(
                f"ERROR while checking {name}: {e}"
            )

    save_state(new_state)

    # No changes
    if not all_changes:
        print("\nNo meaningful changes found.")
        return

    # ==============================
    # TELEGRAM MESSAGE
    # ==============================

    message = "🚨 MPESB WEBSITE UPDATE\n\n"

    message += (
        "⏰ "
        + datetime.now().strftime(
            "%d-%m-%Y %I:%M %p"
        )
        + "\n\n"
    )

    for change in all_changes:

        message += f"📢 {change['name']}\n\n"

        # New links
        if change["added"]:

            message += "🆕 NEW / UPDATED LINKS:\n"

            count = 0

            for title, link in change["added"]:

                if not title:
                    title = "New Link"

                message += (
                    f"• {title}\n"
                    f"{link}\n"
                )

                count += 1

                if count >= 8:
                    break

            message += "\n"

        # Removed links
        if change["removed"]:

            message += "❌ REMOVED LINKS:\n"

            count = 0

            for title, link in change["removed"]:

                if not title:
                    title = "Link"

                message += f"• {title}\n"

                count += 1

                if count >= 5:
                    break

            message += "\n"

        # Text changes
        if change["text_change"]:

            message += "✏️ CONTENT CHANGE:\n"
            message += (
                change["text_change"]
                + "\n\n"
            )

        message += (
            f"🔗 Open Website:\n"
            f"{change['url']}\n\n"
        )

    message += "🤖 MPESB Automatic Monitor"

    # Telegram message limit safety
    if len(message) > 3900:
        message = message[:3900] + "\n\n..."

    sent = send_telegram(message)

    if sent:
        print("\n✅ Telegram notification sent.")
    else:
        print("\n❌ Telegram notification failed.")


if __name__ == "__main__":
    monitor()
