import logging
import threading

from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest,
    TextMessage,
    Configuration,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent, PostbackEvent

import config
import db
import llm
import onboarding
import push_scheduler
import rag

# ── LINE SDK 初始化 ────────────────────────────────────────────────────────────
_line_conf = Configuration(access_token=config.LINE_CHANNEL_ACCESS_TOKEN)
handler    = WebhookHandler(config.LINE_CHANNEL_SECRET)

# ── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 啟動時建立資料表（DB 連線失敗時不影響伺服器啟動） ─────────────────────────
try:
    db.get_pool()
    db.init_tables()
except Exception as e:
    logger.warning("DB 初始化失敗（稍後重試）：%s", e)

push_scheduler.start_scheduler()


# ── Webhook 路由 ───────────────────────────────────────────────────────────────

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body      = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning("LINE 簽名驗證失敗")
        abort(400)

    return "OK", 200


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


@app.route("/admin/push-now", methods=["POST"])
def admin_push_now():
    """Manually trigger daily push (for testing only)."""
    threading.Thread(target=push_scheduler.run_daily_push, daemon=True).start()
    return {"status": "triggered"}, 200


# ── Follow 事件（使用者加入好友） ─────────────────────────────────────────────

@handler.add(FollowEvent)
def handle_follow(event: FollowEvent):
    user_id = event.source.user_id
    db.get_or_create_user(user_id)
    # 自動抓 LINE 顯示名稱存入 parent_name
    try:
        with ApiClient(_line_conf) as client:
            profile = MessagingApi(client).get_profile(user_id)
            db.update_user_profile(user_id, parent_name=profile.display_name)
            logger.info("抓取 LINE 顯示名稱：%s → %s", user_id, profile.display_name)
    except Exception as e:
        logger.warning("無法取得 LINE 顯示名稱：%s", e)
    db.set_onboarding_state(user_id, 'waiting_phone_number')
    _send_messages(event.reply_token, [onboarding.welcome_ask_phone()])


# ── Postback 事件（DatetimePicker 等互動元件） ────────────────────────────────

@handler.add(PostbackEvent)
def handle_postback(event: PostbackEvent):
    user_id = event.source.user_id
    data    = event.postback.data

    if data == "action=set_birthday":
        date_str = event.postback.params['date']
        current_state = db.get_or_create_user(user_id).get('onboarding_state', '')
        logger.info("生日選擇：user=%s, date=%s, state=%s", user_id, date_str, current_state)
        messages = onboarding.after_birthday_postback(user_id, date_str, current_state)
        _send_messages(event.reply_token, messages)


# ── 文字訊息 ───────────────────────────────────────────────────────────────────

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    user_id = event.source.user_id
    text    = event.message.text.strip()
    logger.info("收到訊息：user=%s, text='%s'", user_id, text)

    user_context = db.get_or_create_user(user_id)
    state = user_context.get('onboarding_state', 'new')

    # 僅在正常問答時才需要歷史（省去 onboarding 階段的無謂 DB 查詢）
    # 必須在 save_message 之前撈，避免當前訊息混入歷史
    history = db.get_recent_history(user_id, limit=20) if state == 'done' else []

    db.save_message(user_id, "user", text)

    # ── 初始 Onboarding 狀態：不可被選單指令打斷 ─────────────────────────────
    _INITIAL_ONBOARDING = {
        'new', 'waiting_parent_name', 'waiting_phone_number', 'confirm_website_profile',
        'waiting_city', 'waiting_parental_employment', 'waiting_child_name',
        'waiting_child_birthday', 'waiting_child_gender', 'waiting_birth_order',
        'waiting_special_status',
    }
    if state in _INITIAL_ONBOARDING:
        if state == 'new':
            db.set_onboarding_state(user_id, 'waiting_child_name')
            _send_messages(event.reply_token, [onboarding.welcome()])
        else:
            messages = onboarding.process(user_id, text, state)
            if messages:
                _send_messages(event.reply_token, messages)
        return

    # ── Rich Menu 固定指令（done / editing_* / selecting_child 皆可用） ────────
    if text in ("我的資料", "查看資料", "查看我的資料", "個人資料"):
        active_child = db.get_active_child(user_id)
        _send_messages(event.reply_token, [onboarding.show_profile(user_context, active_child)])
        return

    if text == "修改資料":
        children = db.get_children(user_id)
        db.set_onboarding_state(user_id, 'editing_select_child')
        _send_messages(event.reply_token, [onboarding.edit_select_target(children)])
        return

    if text == "新增寶寶":
        db.create_child(user_id)
        db.set_onboarding_state(user_id, 'waiting_child_name')
        _send_messages(event.reply_token, [onboarding.welcome_add_child()])
        return

    if text == "切換寶寶":
        children = db.get_children(user_id)
        if len(children) <= 1:
            _reply_text(event.reply_token, "目前只有一位寶寶 😊\n輸入「新增寶寶」可以新增！")
        else:
            db.set_onboarding_state(user_id, 'selecting_child')
            _send_messages(event.reply_token, [onboarding.child_select_message(children)])
        return

    if text == "不用，謝謝":
        _reply_text(event.reply_token, "好的！有任何育兒問題隨時問我 😊")
        return

    # ── editing_* / selecting_child：處理流程中的文字回應 ────────────────────
    if state != 'done':
        messages = onboarding.process(user_id, text, state)
        if messages:
            _send_messages(event.reply_token, messages)
        return

    # ── 正常問答流程 ───────────────────────────────────────────────────────────
    active_child = db.get_active_child(user_id)
    # 合併活躍孩子資料到 context（llm.py 使用舊欄位名稱，在此對應）
    context_for_llm = {
        **user_context,
        "user_nickname": active_child.get("child_name") or user_context.get("user_nickname"),
        "baby_birthday_or_due_date": active_child.get("birth_date") or user_context.get("baby_birthday_or_due_date"),
        "baby_gender": active_child.get("gender") or user_context.get("baby_gender"),
        "region": user_context.get("city") or user_context.get("region"),
    }

    # 立即回覆（避免 LINE 5 秒 webhook 逾時）；3 歲以上加提醒
    birth_date = active_child.get("birth_date") or user_context.get("baby_birthday_or_due_date")
    immediate_msgs = []
    if onboarding.is_over_service_age(birth_date):
        child_name = active_child.get("child_name") or "您的寶寶"
        immediate_msgs.append(TextMessage(type="text", text=(
            f"⚠️ 提醒：{child_name} 已達 3 歲以上，"
            "育兒小幫手目前主要服務 0～3 歲寶寶，"
            "部分資訊可能不完全適用，建議洽詢兒科醫師或相關機構喔！"
        )))
    immediate_msgs.append(TextMessage(type="text", text="思考中，請稍候... 🤔"))
    _send_messages(event.reply_token, immediate_msgs)

    # RAG + LLM 在背景執行，完成後用 Push Message 傳送真正答案
    threading.Thread(
        target=_process_qa_async,
        args=(user_id, text, context_for_llm, history),
        daemon=True,
    ).start()


def _process_qa_async(user_id: str, text: str, context_for_llm: dict, history: list) -> None:
    import time as _time
    t_start = _time.time()
    try:
        rag_query  = llm.build_rag_query(text, context_for_llm, history)

        t1 = _time.time()
        rag_chunks = rag.query_rag(rag_query)
        logger.info("⏱ RAG：%.2fs（%d 片段）", _time.time() - t1, len(rag_chunks))

        t2 = _time.time()
        reply = llm.generate_reply(text, context_for_llm, rag_chunks, history)
        logger.info("⏱ LLM：%.2fs", _time.time() - t2)

        t3 = _time.time()
        db.save_message(user_id, "assistant", reply)
        db.trim_chat_history(user_id, keep=30)
        logger.info("⏱ DB write：%.2fs", _time.time() - t3)

        t4 = _time.time()
        _push_text(user_id, reply)
        logger.info("⏱ Push：%.2fs", _time.time() - t4)

        logger.info("⏱ 總計：%.2fs", _time.time() - t_start)
    except Exception as e:
        logger.error("背景問答處理失敗：%s", e)
        _push_text(user_id, "😅 小幫手暫時遇到一點問題，請稍後再試，或撥打 1922 育兒諮詢專線。")


# ── 工具函式 ───────────────────────────────────────────────────────────────────

def _send_messages(reply_token: str, messages: list) -> None:
    try:
        with ApiClient(_line_conf) as client:
            MessagingApi(client).reply_message(
                ReplyMessageRequest(reply_token=reply_token, messages=messages)
            )
        logger.info("回覆成功（%d 則）", len(messages))
    except Exception as e:
        logger.error("LINE 回覆失敗：%s", e)


def _reply_text(reply_token: str, text: str) -> None:
    _send_messages(reply_token, [TextMessage(type="text", text=text)])


def _push_text(user_id: str, text: str) -> None:
    try:
        with ApiClient(_line_conf) as client:
            MessagingApi(client).push_message(
                PushMessageRequest(to=user_id, messages=[TextMessage(type="text", text=text)])
            )
        logger.info("Push 回覆成功")
    except Exception as e:
        logger.error("LINE Push 失敗：%s", e)


# ── 啟動 ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
