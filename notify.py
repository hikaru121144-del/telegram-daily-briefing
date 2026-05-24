import argparse
import csv
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


CONFIG_FILE = "briefing_config.json"
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
                "summary": strip_html(text_of(item, ["description"])),
            }
            for item in items
        ]

    if root_name == "feed":
        entries = [child for child in root if child.tag.split("}")[-1] == "entry"][:max_items]
        parsed = []
        for entry in entries:
            title = first_child_text(entry, "title") or "(untitled)"
            summary = strip_html(first_child_text(entry, "summary") or first_child_text(entry, "content"))
            link = ""
            for child in entry:
                if child.tag.split("}")[-1] == "link":
                    link = child.attrib.get("href", "")
                    if link:
                        break
            parsed.append({"title": title, "link": link, "summary": summary})
        return parsed

    return []


def strip_html(value: str) -> str:
    text = ""
    in_tag = False
    for char in value:
        if char == "<":
            in_tag = True
        elif char == ">":
            in_tag = False
        elif not in_tag:
            text += char
    return " ".join(html.unescape(text).split())


def truncate(value: str, length: int = 90) -> str:
    value = " ".join(value.split())
    if len(value) <= length:
        return value
    return value[: length - 1].rstrip() + "..."


def contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("briefing_config.json must contain an object.")
    return data


def item_matches(item: dict[str, str], keywords: list[str] | None, exclude_keywords: list[str] | None) -> bool:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    if exclude_keywords and any(keyword.lower() in text for keyword in exclude_keywords):
        return False
    if not keywords:
        return True
    return any(keyword.lower() in text for keyword in keywords)


def collect_section(section: dict) -> list[dict[str, str]]:
    collected = []
    seen_links = set()
    keywords = section.get("keywords")
    exclude_keywords = section.get("exclude_keywords")
    require_chinese = section.get("language") == "zh"

    for feed in section.get("feeds", []):
        feed_name = feed.get("name", "Source")
        try:
            items = parse_feed(fetch_url(feed["url"]), int(feed.get("max_items", 5)))
        except (urllib.error.URLError, ET.ParseError, TimeoutError, ValueError, KeyError):
            continue

        for item in items:
            if require_chinese and not contains_cjk(f"{item.get('title', '')} {item.get('summary', '')}"):
                continue
            link = item.get("link") or item.get("title", "")
            if link in seen_links or not item_matches(item, keywords, exclude_keywords):
                continue
            seen_links.add(link)
            item["source"] = feed_name
            collected.append(item)

    return collected[: int(section.get("max_items", 5))]


def fetch_weather(locations: list[str | dict]) -> list[str]:
    lines = []
    for location in locations:
        if isinstance(location, dict):
            label = location.get("label", location.get("query", ""))
            query_value = location.get("query", label)
        else:
            label = location
            query_value = location
        query = urllib.parse.quote(query_value)
        try:
            data = fetch_url(f"https://wttr.in/{query}?m&format=3", timeout=10).decode("utf-8")
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError):
            continue
        if data:
            _, _, details = data.strip().partition(":")
            lines.append(f"{html.escape(label)}:{html.escape(details or data.strip())}")
    return lines


def fetch_markets(symbols: list[dict]) -> list[str]:
    if not symbols:
        return []

    lines = []
    for symbol in symbols:
        label = symbol["label"]
        query = urllib.parse.quote(symbol["stooq"], safe=".")
        url = f"https://stooq.com/q/l/?s={query}&f=sd2t2ohlcv&e=csv"
        try:
            rows = list(csv.reader(fetch_url(url, timeout=15).decode("utf-8").splitlines()))
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError):
            continue
        if not rows or len(rows[0]) < 7 or rows[0][6] == "N/D":
            continue
        date = rows[0][1]
        close = rows[0][6]
        lines.append(f"{html.escape(label)}: {html.escape(close)} <i>({html.escape(date)})</i>")
    return lines


def section_by_name(config: dict, name: str) -> dict | None:
    for section in config.get("sections", []):
        if section.get("name") == name:
            return section
    return None


def render_item(item: dict[str, str]) -> str:
    title = html.escape(item["title"])
    link = item.get("link", "")
    source = html.escape(item.get("source", ""))
    summary = truncate(item.get("summary", ""), 72)
    source_text = f" <i>({source})</i>" if source else ""

    if link:
        line = f'- <a href="{html.escape(link, quote=True)}">{title}</a>{source_text}'
    else:
        line = f"- {title}{source_text}"
    if summary and contains_cjk(summary):
        line += f"\n  {html.escape(summary)}"
    return line


def build_message(config: dict, profile_name: str) -> str:
    utc_offset_hours = int(config.get("utc_offset_hours", 8))
    timezone = dt.timezone(dt.timedelta(hours=utc_offset_hours))
    today = dt.datetime.now(timezone).strftime("%Y-%m-%d")
    profile = config.get("profiles", {}).get(profile_name, config.get("profiles", {}).get("morning", {}))
    title = profile.get("title", "Daily Briefing")
    message_sections = [f"<b>{html.escape(title)}</b> · {today}"]

    if config.get("weather", {}).get("enabled") and profile_name == "morning":
        weather_lines = fetch_weather(config["weather"].get("locations", []))
        if weather_lines:
            message_sections.append("\n<b>天氣</b>\n" + "\n".join(f"- {line}" for line in weather_lines))

    if config.get("markets", {}).get("enabled"):
        market_lines = fetch_markets(config["markets"].get("symbols", []))
        if market_lines:
            message_sections.append("\n<b>市場速覽</b>\n" + "\n".join(f"- {line}" for line in market_lines))

    for section_name in profile.get("sections", []):
        section = section_by_name(config, section_name)
        if not section:
            continue
        items = collect_section(section)
        if not items:
            continue
        lines = [f"\n<b>{html.escape(section_name)}</b>"]
        lines.extend(render_item(item) for item in items)
        message_sections.append("\n".join(lines))

    message_sections.append("\n<i>已過濾：八卦、未證實謠言、低價值廣告與 NIKKE 相關內容。</i>")
    return "\n".join(message_sections)


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
    parser.add_argument("--config", default=CONFIG_FILE, help="Path to briefing config JSON file.")
    parser.add_argument("--profile", default=os.environ.get("BRIEFING_PROFILE", "morning"), choices=["morning", "evening"])
    args = parser.parse_args()

    config = load_config(args.config)
    message = build_message(config, args.profile)

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
