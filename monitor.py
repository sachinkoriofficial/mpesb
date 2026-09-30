import os
import json
import hashlib
import difflib
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup


# ============================================================
# MPESB HOMEPAGE MONITOR
# ============================================================

URL = "https://esb.mp.gov.in/e_default.html"
STATE_FILE = "esb_state.json"

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]


# ============================================================
# SSL WARNING
# ============================================================

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    telegram_url = (
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        telegram_url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True
        },
        timeout=30
    )

    response.raise_for_status()


def send_long_telegram(message):
    """
    Telegram message limit is around 4096 characters.
    Split large notifications safely.
    """

    max_length = 3800

    if len(message) <= max_length:
        send_telegram(message)
        return

    parts = []

    while len(message) > max_length:
        split_at = message.rfind("\n", 0, max_length)

        if split_at == -1:
            split_at = max_length

        parts.append(message[:split_at])
        message = message[split_at:].lstrip("\n")

    if message:
        parts.append(message)

    for part in parts:
        send_telegram(part)


# ============================================================
# FETCH WEBSITE
# ============================================================

def fetch_website():

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),

        "Cache-Control": (
            "no-cache, no-store, max-age=0, must-revalidate"
        ),

        "Pragma": "no-cache",

        "Expires": "0",

        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        )
    }

    # Cache busting
    cache_buster = datetime.now().strftime(
        "%Y%m%d%H%M%S%f"
    )

    request_url = (
        URL
        + "?monitor="
        + cache_buster
    )

    print("🌐 Checking:", request_url)

    try:

        response = requests.get(
            request_url,
            headers=headers,
            timeout=60,
            allow_redirects=True,
            verify=True
        )

    except requests.exceptions.SSLError:

        print(
            "⚠️ SSL verification failed."
            " Retrying without SSL verification..."
        )

        response = requests.get(
            request_url,
            headers=headers,
            timeout=60,
            allow_redirects=True,
            verify=False
        )

    response.raise_for_status()

    print(
        "✅ Website fetched successfully"
    )

    print(
        "🔗 Final URL:",
        response.url
    )

    return response.text


# ============================================================
# NORMALIZE VISIBLE PAGE CONTENT
# ============================================================

def normalize_page(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # Remove elements which are not visible page content
    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "template"
        ]
    ):
        tag.decompose()

    # --------------------------------------------------------
    # TEXT
    # --------------------------------------------------------

    raw_text = soup.get_text(
        "\n"
    )

    # Normalize only whitespace.
    # IMPORTANT:
    # We do NOT remove duplicate lines.
    # We do NOT remove words.
    # We do NOT remove dates/numbers.
    # Therefore even a small text change can be detected.
    lines = []

    for line in raw_text.splitlines():

        # Convert tabs/multiple spaces into one space
        line = re.sub(
            r"[ \t]+",
            " ",
            line
        ).strip()

        if line:
            lines.append(line)

    # --------------------------------------------------------
    # LINKS
    # --------------------------------------------------------

    links = []

    for a in soup.find_all(
        "a",
        href=True
    ):

        title = a.get_text(
            " ",
            strip=True
        )

        href = a.get(
            "href",
            ""
        ).strip()

        if not href:
            continue

        absolute_href = urljoin(
            URL,
            href
        )

        links.append(
            f"{title} -> {absolute_href}"
        )

    # Keep every link exactly.
    # Do not sort away meaningful ordering.
    links = list(
        dict.fromkeys(links)
    )

    return lines, links


# ============================================================
# CREATE HASH
# ============================================================

def create_hash(
    lines,
    links
):

    content = (
        "\n".join(lines)
        + "\n--- LINKS ---\n"
        + "\n".join(links)
    )

    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


# ============================================================
# STATE
# ============================================================

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
        ) as file:

            return json.load(file)

    except Exception as error:

        print(
            "⚠️ Could not read state:",
            error
        )

        return None


def save_state(data):

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# FIND EXACT TEXT CHANGES
# ============================================================

def find_text_changes(
    old_lines,
    new_lines
):

    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="OLD MPESB PAGE",
            tofile="NEW MPESB PAGE",
            lineterm=""
        )
    )

    return diff


# ============================================================
# FIND LINK CHANGES
# ============================================================

def find_link_changes(
    old_links,
    new_links
):

    old_set = set(
        old_links
    )

    new_set = set(
        new_links
    )

    added = [
        link
        for link in new_links
        if link not in old_set
    ]

    removed = [
        link
        for link in old_links
        if link not in new_set
    ]

    return added, removed


# ============================================================
# CREATE TELEGRAM MESSAGE
# ============================================================

def create_message(
    text_diff,
    added_links,
    removed_links
):

    message = (
        "🚨 MPESB WEBSITE UPDATE!\n\n"
        "🌐 MPESB Homepage पर बदलाव मिला है।\n\n"
    )

    # --------------------------------------------------------
    # TEXT CHANGE
    # --------------------------------------------------------

    meaningful_diff = []

    for line in text_diff:

        if (
            line.startswith("+++") or
            line.startswith("---") or
            line.startswith("@@")
        ):
            continue

        if line.startswith("+"):
            meaningful_diff.append(
                "🟢 " + line[1:]
            )

        elif line.startswith("-"):
            meaningful_diff.append(
                "🔴 " + line[1:]
            )

    if meaningful_diff:

        message += (
            "📝 TEXT CHANGE:\n"
        )

        for line in meaningful_diff[:40]:

            if len(line) > 500:
                line = line[:497] + "..."

            message += (
                line
                + "\n"
            )

        message += "\n"


    # --------------------------------------------------------
    # NEW LINKS
    # --------------------------------------------------------

    if added_links:

        message += (
            "🔗 NEW / UPDATED LINKS:\n"
        )

        for link in added_links[:20]:

            if len(link) > 500:
                link = link[:497] + "..."

            message += (
                "🟢 "
                + link
                + "\n"
            )

        message += "\n"


    # --------------------------------------------------------
    # REMOVED LINKS
    # --------------------------------------------------------

    if removed_links:

        message += (
            "❌ REMOVED LINKS:\n"
        )

        for link in removed_links[:20]:

            if len(link) > 500:
                link = link[:497] + "..."

            message += (
                "🔴 "
                + link
                + "\n"
            )

        message += "\n"


    # --------------------------------------------------------
    # FOOTER
    # --------------------------------------------------------

    message += (
        "📌 Official MPESB Homepage:\n"
        "https://esb.mp.gov.in/e_default.html"
    )

    return message


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "========================================"
    )

    print(
        "🔍 MPESB WEBSITE MONITOR STARTED"
    )

    print(
        "========================================"
    )


    # --------------------------------------------------------
    # FETCH
    # --------------------------------------------------------

    html = fetch_website()


    # --------------------------------------------------------
    # EXTRACT PAGE CONTENT
    # --------------------------------------------------------

    new_lines, new_links = normalize_page(
        html
    )


    print(
        "📝 Text lines:",
        len(new_lines)
    )

    print(
        "🔗 Links:",
        len(new_links)
    )


    # --------------------------------------------------------
    # HASH
    # --------------------------------------------------------

    new_hash = create_hash(
        new_lines,
        new_links
    )


    # --------------------------------------------------------
    # LOAD OLD STATE
    # --------------------------------------------------------

    old_state = load_state()


    # --------------------------------------------------------
    # FIRST RUN
    # --------------------------------------------------------

    if old_state is None:

        print(
            "ℹ️ First run detected."
        )

        state = {
            "hash": new_hash,
            "lines": new_lines,
            "links": new_links,
            "checked_at": datetime.now().isoformat(),
            "final_url": URL,
            "monitor_version": 2
        }

        save_state(
            state
        )

        print(
            "✅ Baseline saved."
        )

        return


    # --------------------------------------------------------
    # OLD STATE
    # --------------------------------------------------------

    old_lines = old_state.get(
        "lines",
        []
    )

    old_links = old_state.get(
        "links",
        []
    )

    old_hash = old_state.get(
        "hash"
    )


    # --------------------------------------------------------
    # NO CHANGE
    # --------------------------------------------------------

    if old_hash == new_hash:

        print(
            "✅ NO CHANGE DETECTED."
        )

        return


    # --------------------------------------------------------
    # CHANGE DETECTED
    # --------------------------------------------------------

    print(
        "🚨 CHANGE DETECTED!"
    )


    # --------------------------------------------------------
    # EXACT TEXT DIFF
    # --------------------------------------------------------

    text_diff = find_text_changes(
        old_lines,
        new_lines
    )


    # --------------------------------------------------------
    # LINK DIFF
    # --------------------------------------------------------

    added_links, removed_links = find_link_changes(
        old_links,
        new_links
    )


    print(
        "📝 Text changes:",
        len(text_diff)
    )

    print(
        "🟢 Added links:",
        len(added_links)
    )

    print(
        "🔴 Removed links:",
        len(removed_links)
    )


    # --------------------------------------------------------
    # TELEGRAM MESSAGE
    # --------------------------------------------------------

    message = create_message(
        text_diff,
        added_links,
        removed_links
    )


    # --------------------------------------------------------
    # IMPORTANT:
    # SEND TELEGRAM FIRST
    # SAVE STATE ONLY AFTER SUCCESS
    # --------------------------------------------------------

    print(
        "📤 Sending Telegram notification..."
    )

    send_long_telegram(
        message
    )


    print(
        "✅ Telegram notification sent."
    )


    # --------------------------------------------------------
    # SAVE NEW STATE
    # --------------------------------------------------------

    new_state = {
        "hash": new_hash,
        "lines": new_lines,
        "links": new_links,
        "checked_at": datetime.now().isoformat(),
        "final_url": URL,
        "monitor_version": 2
    }

    save_state(
        new_state
    )


    print(
        "💾 New monitoring state saved."
    )

    print(
        "========================================"
    )

    print(
        "✅ MONITOR COMPLETED"
    )

    print(
        "========================================"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
