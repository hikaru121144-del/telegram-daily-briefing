import argparse
import datetime as dt
import html
import json
import os
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


SOURCES_FILE = "sources.json"
TELEGRAM_LIMIT = 3900


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def fetch_url(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "telegram-daily-briefing/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def text_of(parent: ET.Element, names: list[str]) -> str:
    for name in names:
        found = parent.find(name)
        if found is not None and found.text:
            return html.unescape(found.text.strip())
    return ""


def first_child_text(parent: ET.Element, local_name: str) -> str:
    for child in parent:
        if child.tag.split("}")[-1] == local_name and child.text:
            return html.unescape(child.text.strip())
    return ""


def parse_feed(feed_bytes: bytes, max_items: int) -> list[dict[str, str]]:
    root = ET.fromstring(feed_bytes)
    root_name = root.tag.split("}")[-1].lower()

    if root_name == "rss":
        channel = root.find("channel")
        if channel is None:
            return []
        items = channel.findall("item")[:max_items]
        return [
            {
                "title": text_of(item, ["title"]) or "(untitled)",
                "link": text_of(item, ["link"]),
            }
            for item in items
        ]

    if root_name == "feed":
        entries = [child for child in root if child.tag.split("}")[-1] == "entry"][:max_items]
        parsed = []
        for entry in entries:
            title = first_child_text(entry, "title") or "(untitled)"
            link = ""
            for child in entry:
                if child.tag.split("}")[-1] == "link":
                    link = child.attrib.get("href", "")
                    if link:
                        break
            parsed.append({"title": title, "link": link})
        return parsed

    return []


def load_sources(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("sources.json must contain a list of source objects.")
    return data


def build_message(sources: list[dict]) -> str:
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    sections = [f"<b>Daily Briefing</b> · {today}"]

    for source in sources:
        name = source.get("name", "Untitled Source")
        url = source.get("url")
        max_items = int(source.get("max_items", 5))

        if not url:
            continue

        try:
            items = parse_feed(fetch_url(url), max_items)
        except (urllib.error.URLError, ET.ParseError, TimeoutError, ValueError) as error:
            sections.append(f"\n<b>{html.escape(name)}</b>\n- Failed to load: {html.escape(str(error))}")
            continue

        if not items:
            sections.append(f"\n<b>{html.escape(name)}</b>\n- No items found")
            continue

        lines = [f"\n<b>{html.escape(name)}</b>"]
        for item in items:
            title = html.escape(item["title"])
            link = item.get("link", "")
            if link:
                lines.append(f'- <a href="{html.escape(link, quote=True)}">{title}</a>')
            else:
                lines.append(f"- {title}")
        sections.append("\n".join(lines))

    return "\n".join(sections)


def split_message(message: str) -> list[str]:
    if len(message) <= TELEGRAM_LIMIT:
        return [message]

    chunks = []
    remaining = message
    while len(remaining) > TELEGRAM_LIMIT:
        split_at = remaining.rfind("\n\n", 0, TELEGRAM_LIMIT)
        if split_at == -1:
            split_at = TELEGRAM_LIMIT
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def send_telegram(message: str, token: str, chat_id: str) -> None:
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in split_message(message):
        payload = urllib.parse.urlencode(
            {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        request = urllib.request.Request(api_url, data=payload, method="POST")
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            result = json.loads(body)
            if not result.get("ok"):
                raise RuntimeError(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a daily briefing to Telegram.")
    parser.add_argument("--dry-run", action="store_true", help="Print the message without sending it.")
    parser.add_argument("--sources", default=SOURCES_FILE, help="Path to sources JSON file.")
    args = parser.parse_args()

    sources = load_sources(args.sources)
    message = build_message(sources)

    if args.dry_run:
        print(textwrap.dedent(message))
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.", file=sys.stderr)
        return 2

    send_telegram(message, token, chat_id)
    print("Telegram briefing sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
