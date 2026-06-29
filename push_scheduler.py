"""Daily push notifications for parenting reminders.

Three notification types, staggered to avoid same-day overload:

  1. Health events (vaccine + well-baby checkup) — daily check at 09:00.
     Fires when a milestone is exactly TODAY or exactly 7 DAYS away.
     Vaccine and checkup events on the same day are COMBINED into one message.

  2. Developmental milestones — fires once on the baby's monthly anniversary
     (e.g., born Apr 5 → milestone fires Oct 5 for 6-month mark).

  3. Policy deadline reminders — TUESDAY only, 09:00.
     GitHub policy data is crawled every Monday early morning; Tuesday push
     guarantees data is fresh. Queries the teammate's RAG API for content.
"""

import calendar
import logging
import threading
import time
from datetime import date, datetime, timezone, timedelta
from collections import defaultdict

import config

logger = logging.getLogger(__name__)

_TW_TZ    = timezone(timedelta(hours=8))
_PUSH_HOUR = 9  # 09:00 Taiwan time

# ── Taiwan CDC immunization schedule (age in months → vaccine names) ────────────

_VACCINE_SCHEDULE: dict[int, list[str]] = {
    0:  ["卡介苗（BCG）", "B型肝炎疫苗（第1劑）"],
    1:  ["B型肝炎疫苗（第2劑）"],
    2:  ["五合一疫苗（第1劑）", "13價肺炎鏈球菌疫苗（第1劑）"],
    4:  ["五合一疫苗（第2劑）", "13價肺炎鏈球菌疫苗（第2劑）"],
    6:  ["五合一疫苗（第3劑）", "13價肺炎鏈球菌疫苗（第3劑）", "B型肝炎疫苗（第3劑）"],
    12: ["麻疹腮腺炎德國麻疹混合疫苗（MMR 第1劑）", "水痘疫苗", "日本腦炎疫苗（第1劑）"],
    15: ["日本腦炎疫苗（第2劑）"],
    18: ["五合一疫苗（第4劑）"],
    24: ["A型肝炎疫苗（第1劑）"],
    27: ["A型肝炎疫苗（第2劑）"],
}

# ── Taiwan MOH well-baby checkup schedule (兒童預防保健服務) ────────────────────

_CHECKUP_SCHEDULE: dict[int, str] = {
    1:  "第1次兒童預防保健（嬰兒期）",
    2:  "第2次兒童預防保健（嬰兒期）",
    4:  "第3次兒童預防保健（嬰兒期）",
    6:  "第4次兒童預防保健（嬰兒期）",
    9:  "第5次兒童預防保健（聽力篩查）",
    12: "第6次兒童預防保健（幼兒期）",
    18: "第7次兒童預防保健（幼兒期）",
    24: "第8次兒童預防保健（學前）",
    30: "第9次兒童預防保健（學前）",
    36: "第10次兒童預防保健（學前）",
}

# ── Developmental milestones (age in months → description) ──────────────────────

_MILESTONE_SCHEDULE: dict[int, str] = {
    1:  "開始注視人臉、聽到聲音會轉頭",
    2:  "出現社交性微笑、喉嚨發出咕咕聲",
    3:  "趴著能抬頭 45°、追視移動物體",
    4:  "趴著抬頭 90°、開始伸手抓東西",
    5:  "能辨識熟悉的臉、對名字有反應",
    6:  "扶著可以坐、可以開始嘗試副食品",
    7:  "學會翻身、發出雙音節（如「爸爸」）",
    8:  "開始爬行、會找尋藏起來的玩具",
    9:  "扶著站立、模仿大人的動作與聲音",
    10: "拍手、開始理解「不行」的意思",
    11: "扶著走路、叫爸爸媽媽",
    12: "走出第一步、說 2～3 個有意義的字",
    15: "走路漸穩、能指認書中的圖案",
    18: "會說 10 個字以上、疊 3～4 個積木",
    21: "開始說 2 字短句、喜歡模仿做家事",
    24: "說 2～3 字句、自己用湯匙吃飯",
    27: "會說自己的名字、喜歡玩假扮遊戲",
    30: "說 3 字句、會單腳跳",
    33: "能與其他孩子一起玩、會說故事片段",
    36: "認識基本顏色、能完整說出需求",
}


# ── Date helpers ─────────────────────────────────────────────────────────────────

def _add_months(d: date, months: int) -> date:
    """Return d + months, clamped to the last valid day of the target month."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def _age_months(birth_date: date, today: date) -> int:
    return (today.year - birth_date.year) * 12 + (today.month - birth_date.month)


# ── Health event collectors ───────────────────────────────────────────────────────

def _due_health_events(birth_date: date, today: date) -> dict[date, list[tuple[str, str]]]:
    """Return {due_date: [(kind, name), ...]} for events due today or in 7 days.

    kind is either 'vaccine' or 'checkup'.
    Only fires on exactly today (days_until == 0) or exactly 7 days out.
    """
    events: dict[date, list] = defaultdict(list)
    for months, vaccines in _VACCINE_SCHEDULE.items():
        due = _add_months(birth_date, months)
        if (due - today).days in (0, 7):
            for v in vaccines:
                events[due].append(("vaccine", v))
    for months, checkup in _CHECKUP_SCHEDULE.items():
        due = _add_months(birth_date, months)
        if (due - today).days in (0, 7):
            events[due].append(("checkup", checkup))
    return dict(events)


def _build_health_message(child_name: str, events: dict[date, list[tuple[str, str]]], today: date) -> str:
    """Combine all health events into a single LINE message."""
    lines = [f"🏥 {child_name} 的健康提醒"]
    for due_date in sorted(events):
        days_until = (due_date - today).days
        timing = "【今天】" if days_until == 0 else f"【7 天後 {due_date.strftime('%m/%d')}】"
        vaccines  = [name for kind, name in events[due_date] if kind == "vaccine"]
        checkups  = [name for kind, name in events[due_date] if kind == "checkup"]
        if vaccines:
            lines.append(f"\n💉 {timing} 接種疫苗")
            for v in vaccines:
                lines.append(f"  • {v}")
        if checkups:
            lines.append(f"\n👶 {timing} 兒童健檢")
            for c in checkups:
                lines.append(f"  • {c}")
    lines.append("\n請攜帶健兒手冊前往診所或衛生所 😊\n（資訊以衛福部最新公告為準）")
    return "\n".join(lines)


# ── Milestone ────────────────────────────────────────────────────────────────────

def _get_milestone_message(birth_date: date, child_name: str, today: date) -> str | None:
    """Return a milestone message if today is the baby's exact monthly anniversary."""
    age = _age_months(birth_date, today)
    if age <= 0:
        return None
    # Only fire if today is the actual anniversary date (not just any day in that month)
    anniversary = _add_months(birth_date, age)
    if anniversary != today:
        return None
    text = _MILESTONE_SCHEDULE.get(age)
    if not text:
        return None
    return (
        f"🌟 {child_name} 滿 {age} 個月了！\n\n"
        f"這個月的發展里程碑：\n• {text}\n\n"
        "每個寶寶步調不同，以上為一般參考。\n"
        "若有疑慮請諮詢兒科醫師 😊"
    )


# ── Policy reminder (RAG-based, runs Tuesdays) ──────────────────────────────────

def _get_policy_reminder(child_name: str, age_months: int, city: str) -> str | None:
    """Query RAG (policy-pipeline indexed content) and summarise upcoming deadlines.

    Only called on Tuesdays; GitHub policy data is crawled on Monday mornings,
    so Tuesday push guarantees the data is fresh.
    Returns a formatted LINE message or None if nothing urgent.
    """
    try:
        import rag
        from llm import _chat
        query = f"{city or '台灣'} 寶寶 {age_months} 個月 育兒補助 政策 申請期限 截止日"
        chunks = rag.query_rag(query)
        if not chunks:
            return None
        knowledge = "\n".join(chunks[:3])
        prompt = (
            f"以下是育兒補助政策資訊（資料每週一更新）：\n{knowledge}\n\n"
            f"家長居住在「{city or '台灣'}」，{child_name}目前 {age_months} 個月大。\n"
            "請用繁體中文（80字以內，不用 Markdown，條列用「•」）整理出近期最重要的申請提醒或截止日。\n"
            "若沒有明確截止資訊，請只回覆「無相關截止提醒」。"
        )
        reply = _chat(
            "你是育兒政策提醒助手，只輸出繁體中文摘要，不加任何解釋。",
            prompt,
            temperature=0.3,
            max_tokens=200,
        )
        if not reply or "無相關截止提醒" in reply:
            return None
        return f"📋 本週政策申請提醒\n\n{reply.strip()}\n\n（資料每週一自動更新，以政府最新公告為準）"
    except Exception as e:
        logger.warning("政策提醒查詢失敗：%s", e)
        return None


# ── LINE push helper ─────────────────────────────────────────────────────────────

def _line_push(user_id: str, text: str) -> None:
    """Send a LINE push message. Defined here to avoid circular import with main.py."""
    from linebot.v3.messaging import (
        ApiClient, Configuration, MessagingApi,
        PushMessageRequest, TextMessage,
    )
    try:
        conf = Configuration(access_token=config.LINE_CHANNEL_ACCESS_TOKEN)
        with ApiClient(conf) as client:
            MessagingApi(client).push_message(
                PushMessageRequest(to=user_id, messages=[TextMessage(type="text", text=text)])
            )
        logger.info("推播成功：%s", user_id)
    except Exception as e:
        logger.error("LINE 推播失敗：user=%s err=%s", user_id, e)


# ── Per-user orchestration ────────────────────────────────────────────────────────

def _push_user_notifications(user: dict, child: dict, today: date, is_tuesday: bool) -> None:
    """Collect and send all relevant notifications for one user today."""
    user_id    = user.get("line_user_id")
    birth_date = child.get("birth_date")
    if not user_id or not birth_date:
        return
    if isinstance(birth_date, str):
        birth_date = date.fromisoformat(birth_date)

    child_name = child.get("child_name") or "寶寶"
    city       = user.get("city") or ""
    age_months = _age_months(birth_date, today)

    # 1. Health events (vaccine + checkup combined into one message)
    events = _due_health_events(birth_date, today)
    if events:
        msg = _build_health_message(child_name, events, today)
        _line_push(user_id, msg)
        logger.info("健康事件推播：user=%s events=%s", user_id, list(events.keys()))

    # 2. Developmental milestone (only on the exact monthly anniversary)
    milestone_msg = _get_milestone_message(birth_date, child_name, today)
    if milestone_msg:
        _line_push(user_id, milestone_msg)
        logger.info("里程碑推播：user=%s age=%d months", user_id, age_months)

    # 3. Policy deadlines — Tuesdays only (data fresh after Monday crawl)
    if is_tuesday and config.RAG_API_URL:
        policy_msg = _get_policy_reminder(child_name, age_months, city)
        if policy_msg:
            _line_push(user_id, policy_msg)
            logger.info("政策推播：user=%s age=%d city=%s", user_id, age_months, city)


# ── Main daily job ────────────────────────────────────────────────────────────────

def run_daily_push() -> None:
    """Entry point called once daily by the scheduler (and by /admin/push-now)."""
    today = datetime.now(_TW_TZ).date()
    is_tuesday = datetime.now(_TW_TZ).weekday() == 1  # 1 = Tuesday
    logger.info("每日推播任務開始 date=%s is_tuesday=%s", today, is_tuesday)
    try:
        import db
        pairs = db.get_all_active_users_with_children()
        logger.info("活躍用戶：%d 位", len(pairs))
        for user, child in pairs:
            try:
                _push_user_notifications(user, child, today, is_tuesday)
            except Exception as e:
                logger.error("推播失敗：user=%s err=%s", user.get("line_user_id"), e)
    except Exception as e:
        logger.error("每日推播任務失敗：%s", e)
    logger.info("每日推播任務完成")


# ── Scheduler ─────────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    """Start a background daemon thread that fires run_daily_push at 09:00 TW time."""
    def _loop() -> None:
        while True:
            now    = datetime.now(_TW_TZ)
            target = now.replace(hour=_PUSH_HOUR, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            sleep_secs = (target - now).total_seconds()
            logger.info(
                "推播排程：下次於 %s 台灣時間（%.0f 秒後）",
                target.strftime("%Y-%m-%d %H:%M"),
                sleep_secs,
            )
            time.sleep(sleep_secs)
            run_daily_push()

    t = threading.Thread(target=_loop, daemon=True, name="push-scheduler")
    t.start()
    logger.info("每日推播排程已啟動（每天 %02d:00 台灣時間）", _PUSH_HOUR)
