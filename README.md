# 育兒導航全攻略 LINE Bot

台灣新手爸媽的育兒 AI 助理，透過 LINE 提供疫苗時程、育兒補助、健康問答等服務。

---

## 專案架構

```
Develop LineBot/
├── config.ini          ← LINE Bot 金鑰（channel_access_token, channel_secret）
├── .env                ← 機密環境變數（DATABASE_URL, GEMINI_API_KEY）
├── requirements.txt    ← Python 套件清單
│
├── config.py           ← 統一讀取 config.ini + .env
├── main.py             ← Flask App、LINE Webhook、訊息路由
├── onboarding.py       ← 新用戶引導流程（暱稱 → 生日 → 性別 → 地區 → 興趣）
├── db.py               ← Supabase PostgreSQL 連線池 + CRUD
├── llm.py              ← Gemini API（query rewrite、build_rag_query、generate_reply）
└── rag_mock.py         ← Mock 知識庫（開發用，正式版換成 AnythingLLM API）
```

### 訊息處理流程

```
用戶傳訊息
  → get_or_create_user()             # 取得用戶資料（暱稱、寶寶生日等）
  → get_recent_history(limit=6)      # 撈近期對話（記憶功能，save 前！）
  → save_message("user", text)       # 儲存當前訊息
  → build_rag_query()                # 彙整用戶資料 + 歷史 → 完整查詢句
  → rag_mock.query_mock_rag()        # RAG 找知識片段（正式版換 AnythingLLM）
  → generate_reply()                 # Gemini 生成回覆（含安全規範）
  → save_message("assistant", reply) # 儲存機器人回覆
  → 回傳給用戶
```

---

## 快速啟動

### 1. 建立虛擬環境並安裝套件

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 設定金鑰

**config.ini**（LINE Bot 金鑰，從 LINE Developers 取得）：
```ini
[line-bot]
channel_access_token = 你的_channel_access_token
channel_secret = 你的_channel_secret
```

**.env**（資料庫與 AI 金鑰）：
```
DATABASE_URL=postgresql://...   # Supabase 連線字串
GEMINI_API_KEY=你的_gemini_key
```

### 3. 啟動 Flask

```bash
python main.py
```

預設跑在 `http://localhost:8000`，健康檢查：`GET /health`

### 4. 啟動 ngrok（開發用）

```bash
ngrok http 8000
```

將 ngrok 產生的 HTTPS URL + `/callback` 填入 LINE Developers → Webhook URL。

---

## 資料庫結構

### user_profiles
| 欄位 | 說明 |
|---|---|
| line_user_id | LINE 用戶 ID（Primary Key） |
| user_nickname | 寶寶暱稱 |
| baby_birthday_or_due_date | 寶寶生日或預產期 |
| baby_gender | 寶寶性別（男/女/未知） |
| region | 所在縣市 |
| interests | 感興趣的主題（逗號分隔） |
| onboarding_state | 引導流程進度 |

### chat_histories
| 欄位 | 說明 |
|---|---|
| message_id | 訊息 ID（Auto Increment） |
| line_user_id | 外鍵 → user_profiles |
| role | user 或 assistant |
| content | 訊息內容 |
| created_at | 建立時間 |

---

## 待辦事項

- [ ] 接隊友 AnythingLLM RAG API（替換 `rag_mock.py` 的 `query_mock_rag()`）
- [ ] 對話歷史過長時的摘要機制（避免 token 超限）
- [ ] 正式部署（Railway / Render / Cloud Run，取代 ngrok）
- [ ] Gemini 失敗時的錯誤通知機制

---

## 安全規範

本 Bot 的 AI 回覆遵守以下原則（定義於 `llm.py` 的 `SYSTEM_PROMPT`）：

- 不做具體醫療診斷，有症狀一律建議就醫確認
- 不建議停藥或調整醫師處方
- 緊急狀況（抽搐、呼吸困難）立即引導撥打 119
- 知識庫資訊不足時，誠實告知並提供 1922 育兒諮詢專線
- 疑似兒童受虐或家暴，提供保護專線 113
- 不討論政治、宗教等敏感話題

---

## 常用指令（使用者可輸入）

| 指令 | 效果 |
|---|---|
| 我的資料 / 查看資料 | 顯示已儲存的寶寶資料 |
| 修改資料 | 重新進行 onboarding 設定 |
