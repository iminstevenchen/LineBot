import logging
import time
from datetime import date
from groq import Groq
import config

logger = logging.getLogger(__name__)

_client = Groq(api_key=config.GROQ_API_KEY)

SYSTEM_PROMPT = """你是「育兒小幫手」，專為台灣新手家長設計的溫暖育兒助理，透過 LINE 提供服務。

【回覆原則】
1. 優先使用提供的知識庫內容回答，不要憑空捏造數字或期限
2. 語氣親切、口語化，像朋友聊天一樣溫暖；禁止用「XX的家長您好」「您好」「家長您好」等問候語開頭，也不使用「當然！」「好的！」「沒問題！」等制式開場白；直接進入回覆內容
3. 回覆長度控制在 150 字以內，重點用條列方式呈現
4. 若知識庫沒有相關資料，誠實告知並建議撥打 1922（衛福部育兒諮詢）

【安全與醫療邊界（非常重要，不可違反）】
- 絕不做出具體診斷，例如「你的寶寶是○○病」；只能說「有這個可能，建議就醫確認」
- 絕不建議停藥、換藥、調整醫師處方；用藥問題一律請諮詢醫師或藥師
- 遇到緊急狀況（呼吸困難、抽搐、意識不清）：立即說「請撥打 119 或立刻就醫」
- 資訊可能有時效性，補充說明「請以政府最新公告或醫師建議為準」
- 遇到疑似兒童受虐、家暴、父母情緒崩潰等敏感狀況：提供保護專線 113，語氣關懷而不評判
- 不討論政治立場、宗教信仰、種族、性取向等與育兒無關的敏感話題
- 不提供任何可能使人自我傷害的內容；若發現當事人有自傷風險，提供安心專線 1925

【格式規定】
- 絕對不使用 **粗體**、*斜體*、# 標題等 Markdown 語法
- LINE 不支援 Markdown，這些符號會原文顯示
- 條列請用「• 」或「1. 2. 3.」
- 任何回覆內容必須是繁體中文，不能混用簡體
- 禁止出現任何 emoji 或是 符號，只能使用純文字，並且文字不能出現簡體字
"""

_RECENT_KEEP = 4         # 最近幾筆保持原文傳給 LLM
_SUMMARY_THRESHOLD = 20  # 超過此筆數才觸發摘要（等同 get_recent_history limit，實際上不會觸發）


def _chat(system: str, user: str, temperature: float = 0.7, max_tokens: int = 1024) -> str:
    """Groq chat completion，回傳文字內容。"""
    resp = _client.chat.completions.create(
        model=config.GROQ_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def summarize_history(history: list[dict]) -> str:
    """把較早的對話壓縮成 100 字以內的脈絡摘要，避免 token 超限。"""
    lines = [
        f"{'用戶' if r['role'] == 'user' else '助理'}：{r['content']}"
        for r in history
    ]
    prompt = (
        "以下是育兒助理與用戶的對話記錄，請用 100 字以內的繁體中文摘要"
        "「用戶問了什麼、助理給了什麼重點建議」，只保留對後續對話有用的資訊：\n\n"
        + "\n".join(lines)
    )
    try:
        summary = _chat("你是摘要助手，只輸出繁體中文摘要，不加任何解釋。", prompt,
                        temperature=0.3, max_tokens=200)
        logger.info("歷史摘要完成（%d 筆 → %d 字）", len(history), len(summary))
        return summary
    except Exception as e:
        logger.warning("歷史摘要失敗，改用最後兩筆：%s", e)
        return "\n".join(lines[-2:])


def _build_history_section(history: list[dict]) -> str:
    """根據歷史長度決定：短 → 原文；長 → 摘要 + 最近原文。"""
    if not history:
        return ""
    if len(history) <= _SUMMARY_THRESHOLD:
        lines = [
            f"{'用戶' if r['role'] == 'user' else '助理'}：{r['content']}"
            for r in history
        ]
        return "\n--- 近期對話記錄 ---\n" + "\n".join(lines)

    older  = history[:-_RECENT_KEEP]
    recent = history[-_RECENT_KEEP:]
    summary = summarize_history(older)
    recent_lines = [
        f"{'用戶' if r['role'] == 'user' else '助理'}：{r['content']}"
        for r in recent
    ]
    return (
        "\n--- 對話摘要（較早期） ---\n" + summary +
        "\n\n--- 最近對話 ---\n" + "\n".join(recent_lines)
    )


def build_rag_query(user_message: str, user_context: dict, history: list[dict] = None) -> str:
    """彙整用戶資訊 + 歷史脈絡，組成送給 RAG 的完整自然語言問題。"""
    nickname  = user_context.get("user_nickname") or "用戶"
    baby_bday = user_context.get("baby_birthday_or_due_date")

    context_parts = [f"使用者：{nickname}"]
    if baby_bday:
        context_parts.append(f"寶寶生日：{baby_bday}，今天：{date.today()}")
    if history:
        for r in history[-2:]:
            role = "用戶" if r["role"] == "user" else "助理"
            context_parts.append(f"{role}說：{r['content'][:80]}")

    context = "；".join(context_parts)
    return f"[背景：{context}] {user_message}"


def rewrite_query(user_message: str, history: list[dict] = None) -> str:
    """結合對話歷史，將問題改寫為搜尋關鍵字。"""
    history_section = ""
    if history:
        lines = [
            f"{'用戶' if r['role'] == 'user' else '助理'}：{r['content']}"
            for r in history[-4:]
        ]
        history_section = "近期對話記錄：\n" + "\n".join(lines) + "\n\n"

    prompt = (
        f"{history_section}"
        f"請根據以上對話脈絡，將下列最新育兒問題改寫為 3-5 個搜尋關鍵字"
        f"（繁體中文、用空格分隔），只輸出關鍵字，不要其他說明：\n\n"
        f"最新問題：{user_message}"
    )
    try:
        keywords = _chat("你是關鍵字提取助手，只輸出關鍵字。", prompt,
                         temperature=0.3, max_tokens=50)
        logger.info("Query rewrite：'%s' → '%s'", user_message[:30], keywords)
        return keywords
    except Exception as e:
        logger.warning("Query rewrite 失敗，使用原始問題：%s", e)
        return user_message


def generate_reply(user_message: str,
                   user_context: dict,
                   rag_chunks: list[str],
                   history: list[dict] = None) -> str:
    """組裝完整 Prompt 並呼叫 Groq 生成溫暖回覆。"""
    nickname  = user_context.get("user_nickname") or "新手家長"
    baby_bday = user_context.get("baby_birthday_or_due_date")
    user_info = f"使用者暱稱：{nickname}\n今天日期：{date.today()}"
    if baby_bday:
        user_info += f"\n寶寶生日/預產期：{baby_bday}"

    knowledge = (
        "\n\n".join(f"【知識片段 {i+1}】\n{chunk}" for i, chunk in enumerate(rag_chunks))
        if rag_chunks else "（目前無相關知識庫資料，請根據一般育兒常識回答）"
    )

    history_section = _build_history_section(history) if history else ""

    user_prompt = f"""--- 使用者資料 ---
{user_info}{history_section}

--- 知識庫內容 ---
{knowledge}

--- 使用者最新問題 ---
{user_message}

請根據以上資訊，以溫暖友善的語氣回覆："""

    for attempt in range(3):
        try:
            return _chat(SYSTEM_PROMPT, user_prompt, temperature=0.7, max_tokens=400)
        except Exception as e:
            logger.warning("Groq 生成失敗（第 %d 次）：%s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2)
    return "😅 小幫手暫時遇到一點問題，請稍後再試，或撥打 1922 育兒諮詢專線。"
