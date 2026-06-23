這裡為你準備好了完整的 `.md`（Markdown）檔案內容。你可以直接複製下方代碼框中的文字，並在 VS Code 中新增一個檔案（例如命名為 `linebot_dev_plan.md`）貼上。

這個結構是專門為你負責的 **Line Bot 開發任務** 所規劃的，方便你直接作為開發筆記、任務清單（To-do list），或是稍後複製到你們的 [Lark Docs](https://tsgmg663zqbn.sg.larksuite.com/wiki/Wdpgw23dIinDcnkC0IllntKggNb) 專案文件中。

```markdown
# 育兒導航全攻略 — Line Bot 開發規劃與實作筆記

本文件用於記錄「基於 RAG 與時序提醒之新手爸媽智慧應援 Agent」專案中，**Line Bot 前端交互與中樞串接**的開發流程、架構與待辦事項。

---

## 🛠️ Line Bot 系統架構流程

當使用者在 Line 傳送訊息時，後端程式（FastAPI / Flask）將依序執行以下四大模組：


```

[使用者發送訊息]
│
▼

1. 識別與記憶 ───► 檢查 Line userId，撈取/儲存基本資料與對話歷史 (DB)
│
▼
2. 提問意圖整理 ─► 透過 LLM 將口語提問重寫（Rewrite）為精準檢索關鍵字
│
▼
3. 串聯 RAG ────► 將關鍵字丟給 RAG 模組，至向量資料庫撈取育兒 PDF 知識
│
▼
4. 生成與回傳 ───► 組裝 [基本資料 + 檢索知識 + 提問] 丟給 LLM 生成溫暖回覆 ──► Line 回傳

```

---

## 📝 開發任務清單 (To-do List)

### 🟩 階段一：環境建置與 Hello World（當前進度）
- [ ] 於 Line Developers Console 建立 Provider 與 Messaging API Channel。
- [ ] 取得 `Channel Access Token` 與 `Channel Secret`。
- [ ] 使用 Python 建立基礎 Webhook 伺服器（建議使用 FastAPI + `line-bot-sdk`）。
- [ ] 設定 `ngrok`（或部署至 Web 服務）取得 HTTPS URL，並填入 Line Webhook URL。
- [ ] 測試基礎「換句話說 / Echo 回應」，確保 Line 平台與後端順利通訊。

### 🟨 階段二：資料庫設計對接（配合 Week 2）
- [ ] 與負責資料庫（Table）的同學協調，確認以下欄位已設計：
  - [ ] `user_profiles` 表：包含 `line_user_id`、`baby_birthday_or_due_date`（時序提醒用）、`user_nickname`。
  - [ ] `chat_histories` 表：包含 `message_id`、`line_user_id`、`role` (user/assistant)、`content`、`timestamp`。
- [ ] 實作 Line 後端程式將新用戶資料與對話紀錄寫入資料庫的邏輯。

### 🟧 階段三：意圖優化與 RAG 虛擬對接（配合 Week 3）
- [ ] 撰寫第一版 Prompt，測試讓 LLM 進行「提問重寫（Query Rewriting）」，將口語轉為結構化關鍵字。
- [ ] 與負責 RAG/向量資料庫的同學定義 API 接口或 MCP（Model Context Protocol）協定。
- [ ] **Mock 測試**：在 RAG 尚未完全完工前，先在程式中 Hardcode 假知識文本，測試「LLM 組裝 Prompt ➔ 生成回應 ➔ 回傳 Line」的完整鏈路。

### 🟥 階段四：系統整合與時序主動推送
- [ ] 正式串接 RAG 模組，實現真實育兒 PDF 知識檢索。
- [ ] 串接「時序提醒功能」，當時間觸發時，由 Line Bot 主動調用 `push_message` API 向特定 `line_user_id` 推送疫苗或發展里程碑提醒。
- [ ] 進行異常處理（如：RAG 檢索不到資料時的預設溫暖回應）。

---

## 📌 關鍵資料結構參考 (JSON 範例)

### 1. LLM 組裝 Prompt 的上下文結構
```json
{
  "user_context": {
    "line_user_id": "U123456789...",
    "baby_age_weeks": 6,
    "user_nickname": "奕閔"
  },
  "current_query": "寶寶最近大便好像有點綠綠的，正常嗎？",
  "rewritten_keyword": "新生兒 綠色母乳便 消化里程碑",
  "rag_retrieved_context": [
    "根據育兒指南第45頁：母乳寶寶因為腸胃蠕動較快，膽汁來不及氧化，常排出黃綠色稀便，若活力正常且無白便、黑便、血便，皆屬正常現象..."
  ]
}

```

---

## 🗄️ 專案與參考資源

* 專案時程：2026-05-11 至 2026-07-01
* 團隊文件：[工研院期末專題-育兒導航全攻略 Lark Wiki](https://tsgmg663zqbn.sg.larksuite.com/wiki/Wdpgw23dIinDcnkC0IllntKggNb)
* 開發工具：VS Code, Python 3.11+, Line Messaging API

```

### 💡 在 VS Code 中的操作小技巧：
1. 開啟 VS Code，按下 `Ctrl + N`（Mac 用 `Cmd + N`）新增檔案。
2. 將上述內容完整貼上。
3. 按下 `Ctrl + S`（Mac 用 `Cmd + S`），將檔案命名為 `linebot_dev_plan.md` 儲存。
4. 在 VS Code 中，你可以點擊右上角的 **「Open Preview」圖示（一個放大鏡配書本的圖標）**，就能直接在右側看到排版漂亮的 Markdown 預覽畫面了！

```