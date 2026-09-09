import os
import json
import hashlib
import difflib
from datetime import datetime

import requests
from bs4 import BeautifulSoup


# =========================================================
# MPESB WEBSITE MONITOR
# =========================================================

URLS = {
    "MPESB Home": "https://esb.mp.gov.in/e_default.html",
    "MPESB Rulebooks": "https://esb.mp.gov.in/rulebooks/rule_books.htm",
    "MPESB Important Notices": "https://esb.mp.gov.in/advertisement/Important_message_candidate.htm",
}

STATE_FILE = "esb_state.json"

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

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
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=40,
    )

    if not response.ok:
        print("Telegram Error:", response.text)

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API failed: {result}")

    print("Telegram message sent successfully.")


# =========================================================
# WEBSITE FETCH
# =========================================================

def get_page(url):
    """
    Cache-busting request so GitHub/server/browser cache
    does not return an old version of the website.
    """

    cache_bust = int(datetime.now().timestamp())

    response = requests.get(
        url,
        params={"_monitor": cache_bust},
        headers=HEADERS,
        timeout=40,
    )

    response.raise_for_status()

    print(
        f"Fetched: {url} | "
        f"Status: {response.status_code} | "
        f"Size: {len(response.text)}"
    )

    return response.text


# =========================================================
# HTML PARSER
# =========================================================

def parse_page(html, base_url):
    soup = BeautifulSoup(html, "html.parser")

    # Remove unnecessary content
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    # Visible text
    text = soup.get_text("\n", strip=True)

    # Clean empty lines
    lines = []
    for line in text.splitlines():
        line = " ".join(line.split())
        if line:
            lines.append(line)

    clean_text = "\n".join(lines)

    # Links
    links = []

    for a in soup.find_all("a", href=True):
        title = " ".join(a.get_text(" ", strip=True).split())
        href = a.get("href", "").strip()

        if not href:
            continue

        if href.startswith("javascript:"):
            continue

        links.append({
            "title": title,
            "url": href,
        })

    # Remove duplicate links
    unique_links = []
    seen = set()

    for item in links:
        key = (item["title"], item["url"])

        if key not in seen:
            seen.add(key)
            unique_links.append(item)

    # Hash visible content + links
    link_text = "\n".join(
        f"{x['title']} | {x['url']}"
        for x in unique_links
    )

    combined = clean_text + "\n---LINKS---\n" + link_text

    content_hash = hashlib.sha256(
        combined.encode("utf-8", errors="ignore")
    ).hexdigest()

    return {
        "hash": content_hash,
        "text": clean_text,
        "links": unique_links,
    }


# =========================================================
# IMPORTANT TEXT EXTRACTION
# =========================================================

def extract_last_updated(text):
    keywords = [
        "Last updation",
        "Last Updated",
        "Last update",
        "last updation",
        "last updated",
    ]

    for line in text.splitlines():
        for keyword in keywords:
            if keyword.lower() in line.lower():
                return line.strip()

    return None


def get_new_links(old_data, new_data):
    old_links = {
        (x.get("title", ""), x.get("url", ""))
        for x in old_data.get("links", [])
    }

    new_links = []

    for link in new_data.get("links", []):
        key = (
            link.get("title", ""),
            link.get("url", ""),
        )

        if key not in old_links:
            new_links.append(link)

    return new_links


# =========================================================
# TEXT DIFFERENCE
# =========================================================

def get_text_changes(old_text, new_text):
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm="",
            n=1,
        )
    )

    changes = []

    for line in diff:
        if line.startswith("+++") or line.startswith("---"):
            continue

        if line.startswith("+"):
            value = line[1:].strip()

            if value:
                changes.append(f"🆕 {value}")

    return changes[:15]


# =========================================================
# TELEGRAM MESSAGE
# =========================================================

def create_message(changes):
    message = "🚨 MPESB WEBSITE UPDATE!\n\n"

    message += "🌐 MPESB वेबसाइट पर नया बदलाव मिला है।\n\n"

    for change in changes:
        message += change + "\n"

    message += "\n🔗 https://esb.mp.gov.in/"

    return message


# =========================================================
# LOAD STATE
# =========================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print("State file read error:", e)
        return {}


# =========================================================
# SAVE STATE
# =========================================================

def save_state(state):
    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2,
        )


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 60)
    print("MPESB WEBSITE MONITOR STARTED")
    print("=" * 60)

    old_state = load_state()
    new_state = {}

    all_changes = []

    first_run = not bool(old_state)

    for name, url in URLS.items():

        print(f"\nChecking: {name}")

        try:
            html = get_page(url)

            page_data = parse_page(
                html,
                url
            )

            new_state[name] = page_data

            # First run
            if name not in old_state:
                print(f"First snapshot created for: {name}")
                continue

            old_data = old_state[name]

            # Hash changed
            if old_data.get("hash") != page_data.get("hash"):

                print(f"CHANGE DETECTED: {name}")

                # New links
                new_links = get_new_links(
                    old_data,
                    page_data
                )

                for link in new_links[:10]:

                    title = link.get(
                        "title",
                        "New Update"
                    )

                    link_url = link.get(
                        "url",
                        ""
                    )

                    all_changes.append(
                        f"📢 {title}"
                    )

                    if link_url:
                        all_changes.append(
                            f"🔗 {link_url}"
                        )

                # Important text changes
                text_changes = get_text_changes(
                    old_data.get("text", ""),
                    page_data.get("text", "")
                )

                for change in text_changes:
                    all_changes.append(change)

                # Last Updated information
                old_updated = extract_last_updated(
                    old_data.get("text", "")
                )

                new_updated = extract_last_updated(
                    page_data.get("text", "")
                )

                if (
                    new_updated
                    and new_updated != old_updated
                ):
                    all_changes.append(
                        f"🕐 {new_updated}"
                    )

            else:
                print(f"No change: {name}")

        except Exception as e:

            print(
                f"ERROR checking {name}: {e}"
            )

            # Do not destroy previous state
            if name in old_state:
                new_state[name] = old_state[name]


    # =====================================================
    # SAVE STATE
    # =====================================================

    save_state(new_state)

    print("\nState saved successfully.")


    # =====================================================
    # SEND TELEGRAM
    # =====================================================

    if not first_run and all_changes:

        # Remove duplicate lines
        cleaned_changes = []
        seen = set()

        for item in all_changes:
            if item not in seen:
                seen.add(item)
                cleaned_changes.append(item)

        message = create_message(
            cleaned_changes
        )

        print("\nSending Telegram notification...")

        send_telegram(message)

        print("Notification sent.")

    elif first_run:

        print(
            "First run completed. "
            "Baseline saved. No Telegram notification."
        )

    else:

        print(
            "No website changes detected."
        )


if __name__ == "__main__":
    main()
