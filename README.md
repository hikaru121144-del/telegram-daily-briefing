# Telegram Daily Briefing

每天由 GitHub Actions 自動整理你指定的資訊來源，並推送到 Telegram。

## 你會得到什麼

- 每天早上與晚上固定時間自動推播
- 支援分類 RSS / Atom 資訊來源
- 支援天氣、股價與匯率速覽
- 支援手動從 GitHub Actions 觸發
- 不需要伺服器，不需要電腦開著
- 不依賴 OpenAI API，之後可再加 AI 摘要

## 快速設定

### 1. 建立 Telegram Bot

1. 在 Telegram 搜尋 `@BotFather`
2. 傳送 `/newbot`
3. 依照指示建立 bot
4. 複製 BotFather 給你的 token

### 2. 取得 Chat ID

1. 傳一則訊息給你的 bot
2. 在瀏覽器打開：

```text
https://api.telegram.org/bot<你的 BOT TOKEN>/getUpdates
```

3. 找到回傳 JSON 裡的 `chat.id`

如果你要推到群組，先把 bot 加進群組，再在群組裡傳一則訊息，然後同樣用 `getUpdates` 找 chat id。

### 3. 設定 GitHub Secrets

在 GitHub repo 進入：

`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`

新增：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 4. 設定資訊來源

編輯 `briefing_config.json`。

```json
{
  "name": "AI / 開發工具",
  "feeds": [
  {
    "name": "Hacker News",
    "url": "https://news.ycombinator.com/rss",
    "max_items": 5
  }
  ]
}
```

### 5. 設定推播時間

GitHub Actions 的 cron 使用 UTC。

目前 `.github/workflows/daily-telegram.yml` 設定為：

```yaml
- cron: "0 0 * * *"
- cron: "30 14 * * *"
```

也就是台北時間每天早上 08:00 與晚上 22:30。

## 本地測試

先只看訊息，不真的發送：

```powershell
python notify.py --dry-run
```

測試晚上版：

```powershell
python notify.py --dry-run --profile evening
```

真的發送：

```powershell
$env:TELEGRAM_BOT_TOKEN="你的 token"
$env:TELEGRAM_CHAT_ID="你的 chat id"
python notify.py
```

## 之後可以加的功能

- OpenAI API 摘要與去重
- 天氣、匯率、股票、加密貨幣
- Google Calendar 今日行程
- Notion / GitHub / Gmail 摘要
- 不同時間推不同內容
- 重要關鍵字才推播
