import re
from datetime import date, datetime

import db
from linebot.v3.messaging import (
    QuickReply, QuickReplyItem, MessageAction,
    DatetimePickerAction, TextMessage, FlexMessage, FlexContainer,
)

_MAX_NAME_LEN = 10                         # 姓名／寶寶名字最大字數
_PHONE_RE     = re.compile(r'^09\d{8}$')  # 台灣手機 09XXXXXXXX


def _is_valid_phone(phone: str) -> bool:
    cleaned = re.sub(r'[\s\-]', '', phone)
    return bool(_PHONE_RE.match(cleaned))


# ── 常數 ─────────────────────────────────────────────────────────────────────────

ALL_CITIES = [
    "台北市", "新北市", "桃園市", "基隆市", "新竹市", "新竹縣", "苗栗縣",
    "台中市", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "台南市",
    "高雄市", "屏東縣", "宜蘭縣", "花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣",
]

# 兩層縣市選擇：先選地區，再選縣市
_REGIONS: dict[str, list[str]] = {
    "北部": ["台北市", "新北市", "桃園市", "基隆市", "新竹市", "新竹縣", "苗栗縣"],
    "中部": ["台中市", "彰化縣", "南投縣", "雲林縣"],
    "南部": ["嘉義市", "嘉義縣", "台南市", "高雄市", "屏東縣"],
    "東部": ["宜蘭縣", "花蓮縣", "台東縣"],
    "離島": ["澎湖縣", "金門縣", "連江縣"],
}
_REGION_NAMES = list(_REGIONS.keys())

_EDIT_PARENT_FIELDS = ["姓名", "手機", "縣市", "就業狀況"]
_EDIT_CHILD_FIELDS  = ["寶寶名字", "生日", "性別", "胎次", "特殊身分"]
_PARENT_EDIT_STATES = frozenset({
    'edit_parent_name', 'edit_phone_number', 'edit_city', 'edit_parental_employment'
})
_CHILD_EDIT_STATES = frozenset({
    'edit_child_name', 'edit_child_birthday', 'edit_child_gender',
    'edit_birth_order', 'edit_special_status'
})

# 選項按鈕 emoji（label 顯示用，不影響送出的 text）
_OPTION_EMOJIS = {
    "男寶寶": "👦", "女寶寶": "👧",
    "雙薪家庭": "💼", "單薪家庭": "🏠", "全職照顧": "👶",
    "第 1 胎": "1️⃣", "第 2 胎": "2️⃣", "第 3 胎": "3️⃣", "第 4 胎以上": "4️⃣",
    "姓名": "👤", "手機": "📱", "縣市": "📍", "就業狀況": "📊",
    "寶寶名字": "📝", "生日": "🎂", "性別": "🍼", "胎次": "🧒", "特殊身分": "📋",
    "家長資料": "👪",
}
_FIELD_TO_EDIT_STATE = {
    "姓名":    "edit_parent_name",
    "手機":    "edit_phone_number",
    "縣市":    "edit_city",
    "就業狀況": "edit_parental_employment",
    "寶寶名字": "edit_child_name",
    "生日":    "edit_child_birthday",
    "性別":    "edit_child_gender",
    "胎次":    "edit_birth_order",
    "特殊身分": "edit_special_status",
}

EMPLOYMENT_OPTIONS = ["雙薪家庭", "單薪家庭", "全職照顧"]
EMPLOYMENT_CODE = {"雙薪家庭": "both_working", "單薪家庭": "single_working", "全職照顧": "not_working"}
EMPLOYMENT_LABEL = {v: k for k, v in EMPLOYMENT_CODE.items()}

GENDER_OPTIONS = ["男寶寶", "女寶寶"]
GENDER_CODE = {"男寶寶": "男", "女寶寶": "女"}
GENDER_LABEL = {"男": "男寶寶", "女": "女寶寶"}

BIRTH_ORDER_OPTIONS = ["第 1 胎", "第 2 胎", "第 3 胎", "第 4 胎以上"]
BIRTH_ORDER_CODE = {"第 1 胎": 1, "第 2 胎": 2, "第 3 胎": 3, "第 4 胎以上": 4}
BIRTH_ORDER_LABEL = {1: "第 1 胎", 2: "第 2 胎", 3: "第 3 胎", 4: "第 4 胎以上"}

SPECIAL_STATUS_MAP = {
    "01": "premature",          "02": "low_birth_weight",
    "03": "very_low_birth_weight", "04": "developmental_delay",
    "05": "disability",         "06": "rare_disease",
    "07": "major_illness",      "08": "congenital_heart",
    "09": "low_income",         "10": "middle_low_income",
    "11": "single_parent",      "12": "grandparent_care",
    "13": "domestic_violence",  "14": "special_circumstances",
    "15": "indigenous",         "16": "new_resident",
}
SPECIAL_STATUS_LABEL = {
    "premature": "早產兒", "low_birth_weight": "低出生體重兒",
    "very_low_birth_weight": "極低出生體重兒", "developmental_delay": "發展遲緩",
    "disability": "身心障礙", "rare_disease": "罕見疾病",
    "major_illness": "重大傷病", "congenital_heart": "先天性心臟病",
    "low_income": "低收入戶", "middle_low_income": "中低收入戶",
    "single_parent": "單親家庭", "grandparent_care": "隔代教養",
    "domestic_violence": "受暴家庭", "special_circumstances": "特殊境遇家庭",
    "indigenous": "原住民族", "new_resident": "新住民子女",
}

_SPECIAL_STATUS_PROMPT = (
    "孩子是否有特殊身分？（可多選）\n\n"
    "【醫療類】\n"
    "01. 早產兒（妊娠未滿 37 週）\n"
    "02. 低出生體重兒（未滿 2,500g）\n"
    "03. 極低出生體重兒（未滿 1,500g）\n"
    "04. 發展遲緩（持評估中心證明）\n"
    "05. 身心障礙（持身心障礙證明）\n"
    "06. 罕見疾病\n"
    "07. 重大傷病（持健保重大傷病卡）\n"
    "08. 先天性心臟病\n\n"
    "【社會類】\n"
    "09. 低收入戶\n"
    "10. 中低收入戶\n"
    "11. 單親家庭\n"
    "12. 隔代教養（由祖父母照顧）\n"
    "13. 受暴家庭（持保護令）\n"
    "14. 特殊境遇家庭\n"
    "15. 原住民族\n"
    "16. 新住民子女\n\n"
    "請輸入對應編號（空格分隔），例如：01 05 09\n"
    "或輸入「以上皆無」"
)


# ── Helper ─────────────────────────────────────────────────────────────────────

def _text(text: str, quick_items: list[str] = None) -> TextMessage:
    msg = TextMessage(type="text", text=text)
    if quick_items:
        msg.quick_reply = QuickReply(items=[
            QuickReplyItem(action=MessageAction(label=t, text=t)) for t in quick_items
        ])
    return msg


def _ask_birthday(include_nav: bool = False) -> TextMessage:
    msg = TextMessage(
        type="text",
        text="請問寶寶的生日（或預產期）是什麼時候呢？\n請點選下方按鈕選擇日期 📅",
    )
    items = [QuickReplyItem(
        action=DatetimePickerAction(
            label="📅 選擇日期",
            data="action=set_birthday",
            mode="date",
        )
    )]
    if include_nav:
        items.append(QuickReplyItem(action=MessageAction(label="上一步", text="上一步")))
        items.append(QuickReplyItem(action=MessageAction(label="取消", text="取消")))
    msg.quick_reply = QuickReply(items=items)
    return msg


# ── Entry Points ──────────────────────────────────────────────────────────────

def welcome() -> TextMessage:
    return _text(
        "👋 你好！歡迎加入育兒領航員！\n\n"
        "我可以幫你查詢育兒知識、疫苗時程、補助資訊、托育服務...\n\n"
        f"請問寶寶的名字是什麼？\n（{_MAX_NAME_LEN} 字以內，輸入「跳過」可略過）"
    )


def edit_select_target(children: list[dict]) -> FlexMessage:
    options = ["家長資料"] + _child_options(children)
    return _flex_choice("想修改哪個部分的資料？", options, cancel=True)


def welcome_add_child() -> TextMessage:
    return _text(
        "好的！讓我們來設定新寶寶的資料 👶\n\n"
        f"請問新寶寶的名字是什麼？\n（{_MAX_NAME_LEN} 字以內，輸入「跳過」可略過）"
    )


# ── State Machine ─────────────────────────────────────────────────────────────

def process(user_id: str, text: str, state: str) -> list[TextMessage]:
    text = text.strip()

    # ── 第一步：家長姓名 ───────────────────────────────────────────────────────
    if state == 'waiting_parent_name':
        if text != "跳過":
            if len(text) > _MAX_NAME_LEN:
                return [_text(
                    f"名字太長囉 😅\n請輸入 {_MAX_NAME_LEN} 字以內\n"
                    "（輸入「跳過」可略過）"
                )]
            db.update_user_profile(user_id, parent_name=text)
        db.set_onboarding_state(user_id, 'waiting_phone_number')
        return [_text(
            "請問您的手機號碼？📱\n"
            "格式：09XXXXXXXX（10碼）\n"
            "輸入「跳過」可略過"
        )]

    # ── 第一點五步：手機號碼 ───────────────────────────────────────────────────
    if state == 'waiting_phone_number':
        if text != "跳過":
            if not _is_valid_phone(text):
                return [_text(
                    "手機號碼格式不對 📱\n"
                    "請輸入 10 碼台灣手機號碼，例如：0912345678\n"
                    "（輸入「跳過」可略過）"
                )]
            db.update_user_profile(user_id, phone_number=text)
        db.set_onboarding_state(user_id, 'waiting_city')
        return [_region_carousel()]

    # ── 第二步：縣市（兩層：先選地區，再選縣市） ──────────────────────────────
    if state == 'waiting_city':
        if text in _REGION_NAMES:
            return [_city_carousel(text)]
        if text == "上一步":
            return [_region_carousel()]
        if text not in ALL_CITIES:
            return [_region_carousel()]
        db.update_user_profile(user_id, city=text)
        db.set_onboarding_state(user_id, 'waiting_parental_employment')
        return [_flex_choice("了解！請問家長的就業狀況？", EMPLOYMENT_OPTIONS)]

    # ── 第三步：就業狀況 ──────────────────────────────────────────────────────
    if state == 'waiting_parental_employment':
        if text not in EMPLOYMENT_OPTIONS:
            return [_flex_choice("請選擇就業狀況 😊", EMPLOYMENT_OPTIONS)]
        db.update_user_profile(user_id, parental_employment=EMPLOYMENT_CODE[text])
        db.set_onboarding_state(user_id, 'waiting_child_name')
        return [_text(
            "很好！接下來設定寶寶的資料 👶\n\n請問寶寶的名字是什麼？\n（輸入「跳過」可略過）"
        )]

    # ── 第四步：寶寶名字 ──────────────────────────────────────────────────────
    if state == 'waiting_child_name':
        user = db.get_or_create_user(user_id)
        if not user.get('active_child_id'):
            db.create_child(user_id)  # 首次建立孩子記錄
        if text != "跳過":
            if len(text) > _MAX_NAME_LEN:
                return [_text(
                    f"名字太長囉 😅\n請輸入 {_MAX_NAME_LEN} 字以內\n"
                    "（輸入「跳過」可略過）"
                )]
            db.update_active_child(user_id, child_name=text)
        db.set_onboarding_state(user_id, 'waiting_child_birthday')
        return [_ask_birthday()]

    # ── 第五步：生日（文字 fallback，正常由 DatetimePicker 觸發） ───────────
    if state == 'waiting_child_birthday':
        if text == "確認繼續":
            child = db.get_active_child(user_id)
            if child.get('birth_date'):
                db.set_onboarding_state(user_id, 'waiting_child_gender')
                return [_flex_choice("請選擇寶寶的性別", GENDER_OPTIONS)]
        return [_ask_birthday()]

    # ── 第六步：性別 ──────────────────────────────────────────────────────────
    if state == 'waiting_child_gender':
        if text not in GENDER_OPTIONS:
            return [_flex_choice("請選擇寶寶的性別 😊", GENDER_OPTIONS)]
        db.update_active_child(user_id, gender=GENDER_CODE[text])
        db.set_onboarding_state(user_id, 'waiting_birth_order')
        return [_flex_choice("請問寶寶是第幾胎？", BIRTH_ORDER_OPTIONS)]

    # ── 第七步：胎次 ──────────────────────────────────────────────────────────
    if state == 'waiting_birth_order':
        if text not in BIRTH_ORDER_OPTIONS:
            return [_flex_choice("請選擇寶寶是第幾胎 😊", BIRTH_ORDER_OPTIONS)]
        order_code = BIRTH_ORDER_CODE[text]
        active = db.get_active_child(user_id)
        if _birth_order_taken(user_id, order_code, exclude_child_id=active.get('child_id')):
            return [_flex_choice(
                f"{text}已經有其他寶寶登記了，請重新選擇",
                BIRTH_ORDER_OPTIONS
            )]
        db.update_active_child(user_id, birth_order=order_code)
        db.set_onboarding_state(user_id, 'waiting_special_status')
        return [_text(_SPECIAL_STATUS_PROMPT, ["以上皆無"])]

    # ── 第八步：特殊身分 ──────────────────────────────────────────────────────
    if state == 'waiting_special_status':
        codes = _parse_special_status(text)
        if codes is None:
            return [_text(
                "輸入格式不對喔 😅\n請重新選擇：\n\n" + _SPECIAL_STATUS_PROMPT,
                ["以上皆無"]
            )]
        db.update_active_child(user_id, special_status=','.join(codes))
        db.set_onboarding_state(user_id, 'done')
        child = db.get_active_child(user_id)
        baby = child.get('child_name') or '寶寶'
        return [_text(
            f"✅ 設定完成！\n\n"
            f"我已記住{baby}的資料，現在可以直接問我任何育兒問題 👶\n"
            "例如：「寶寶發燒怎麼辦？」、「有哪些育兒補助？」\n\n"
            "有多位寶寶嗎？輸入「新增寶寶」可再加一位！"
        )]

    # ── 切換孩子 ──────────────────────────────────────────────────────────────
    if state == 'selecting_child':
        children = db.get_children(user_id)
        for i, child in enumerate(children, 1):
            if text.startswith(f"{i}."):
                db.set_active_child(user_id, child['child_id'])
                db.set_onboarding_state(user_id, 'done')
                name = child.get('child_name') or '寶寶'
                return [
                    _child_info_card(child),
                    _text(f"已切換到 {name} 的資料 ✅\n有什麼育兒問題嗎？"),
                ]
        return [_text("請點選要查詢的寶寶：", _child_options(children))]

    # ── 修改資料：選對象（家長 or 哪位寶寶） ─────────────────────────────────
    if state == 'editing_select_child':
        if text == "取消":
            db.set_onboarding_state(user_id, 'done')
            return [_text("好的，沒有修改 😊")]
        if text == "家長資料":
            db.set_onboarding_state(user_id, 'editing_parent_field')
            return [_flex_choice("要修改哪個項目？", _EDIT_PARENT_FIELDS, back=True, cancel=True)]
        children = db.get_children(user_id)
        for i, child in enumerate(children, 1):
            if text.startswith(f"{i}."):
                db.set_active_child(user_id, child['child_id'])
                db.set_onboarding_state(user_id, 'editing_child_field')
                name = child.get('child_name') or '寶寶'
                return [
                    _child_info_card(child),
                    _flex_choice(f"{name} 的哪個項目要修改？", _EDIT_CHILD_FIELDS, back=True, cancel=True),
                ]
        return [edit_select_target(children)]

    # ── 修改資料：選欄位（家長） ──────────────────────────────────────────────
    if state == 'editing_parent_field':
        if text == "取消":
            db.set_onboarding_state(user_id, 'done')
            return [_text("好的，沒有修改 😊")]
        if text == "上一步":
            children = db.get_children(user_id)
            db.set_onboarding_state(user_id, 'editing_select_child')
            return [edit_select_target(children)]
        if text not in _EDIT_PARENT_FIELDS:
            return [_flex_choice("請選擇要修改的項目", _EDIT_PARENT_FIELDS, back=True, cancel=True)]
        next_state = _FIELD_TO_EDIT_STATE[text]
        db.set_onboarding_state(user_id, next_state)
        return [_edit_prompt(next_state)]

    # ── 修改資料：選欄位（寶寶） ──────────────────────────────────────────────
    if state == 'editing_child_field':
        if text == "取消":
            db.set_onboarding_state(user_id, 'done')
            return [_text("好的，沒有修改 😊")]
        if text == "上一步":
            children = db.get_children(user_id)
            db.set_onboarding_state(user_id, 'editing_select_child')
            return [edit_select_target(children)]
        if text not in _EDIT_CHILD_FIELDS:
            return [_flex_choice("請選擇要修改的項目", _EDIT_CHILD_FIELDS, back=True, cancel=True)]
        next_state = _FIELD_TO_EDIT_STATE[text]
        db.set_onboarding_state(user_id, next_state)
        return [_edit_prompt(next_state)]

    # ── 修改資料：欄位輸入層通用導航（上一步 / 取消） ─────────────────────────
    if state in _PARENT_EDIT_STATES | _CHILD_EDIT_STATES:
        if text == "取消":
            db.set_onboarding_state(user_id, 'done')
            return [_text("好的，沒有修改 😊")]
        if text == "上一步":
            if state in _PARENT_EDIT_STATES:
                db.set_onboarding_state(user_id, 'editing_parent_field')
                return [_flex_choice("要修改哪個項目？", _EDIT_PARENT_FIELDS, back=True, cancel=True)]
            else:
                db.set_onboarding_state(user_id, 'editing_child_field')
                return [_flex_choice("要修改哪個項目？", _EDIT_CHILD_FIELDS, back=True, cancel=True)]

    # ── 修改資料：儲存各欄位 ──────────────────────────────────────────────────
    if state == 'edit_parent_name':
        if text != "跳過" and len(text) > _MAX_NAME_LEN:
            return [_text(
                f"名字太長囉 😅\n請輸入 {_MAX_NAME_LEN} 字以內\n"
                "（輸入「跳過」可清除姓名）"
            )]
        db.update_user_profile(user_id, parent_name=None if text == "跳過" else text)
        db.set_onboarding_state(user_id, 'done')
        return [_text("✅ 姓名已更新！\n\n有什麼育兒問題想問我嗎？😊")]

    if state == 'edit_phone_number':
        if text != "跳過" and not _is_valid_phone(text):
            return [_text(
                "手機號碼格式不對 📱\n"
                "請輸入 10 碼台灣手機號碼，例如：0912345678\n"
                "（輸入「跳過」可清除手機號碼）"
            )]
        db.update_user_profile(user_id, phone_number=None if text == "跳過" else text)
        db.set_onboarding_state(user_id, 'done')
        return [_text("✅ 手機號碼已更新！\n\n有什麼育兒問題想問我嗎？😊")]

    if state == 'edit_city':
        if text in _REGION_NAMES:
            return [_city_carousel(text, back_text="重選地區", back_label="← 重選地區")]
        if text == "重選地區":
            return [_region_carousel()]
        if text not in ALL_CITIES:
            return [_region_carousel()]
        db.update_user_profile(user_id, city=text)
        db.set_onboarding_state(user_id, 'done')
        return [_text(f"✅ 縣市已更新為 {text}！\n\n有什麼育兒問題想問我嗎？😊")]

    if state == 'edit_parental_employment':
        if text not in EMPLOYMENT_OPTIONS:
            return [_flex_choice("請點選下方按鈕選擇 😊", EMPLOYMENT_OPTIONS, back=True, cancel=True)]
        db.update_user_profile(user_id, parental_employment=EMPLOYMENT_CODE[text])
        db.set_onboarding_state(user_id, 'done')
        return [_text(f"✅ 就業狀況已更新為 {text}！\n\n有什麼育兒問題想問我嗎？😊")]

    if state == 'edit_child_name':
        if text != "跳過" and len(text) > _MAX_NAME_LEN:
            return [_text(
                f"名字太長囉 😅\n請輸入 {_MAX_NAME_LEN} 字以內\n"
                "（輸入「跳過」可清除名字）"
            )]
        db.update_active_child(user_id, child_name=None if text == "跳過" else text)
        db.set_onboarding_state(user_id, 'done')
        return [_text("✅ 寶寶名字已更新！\n\n有什麼育兒問題想問我嗎？😊")]

    if state == 'edit_child_birthday':
        return [_ask_birthday(include_nav=True)]

    if state == 'edit_child_gender':
        if text not in GENDER_OPTIONS:
            return [_flex_choice("請點選下方按鈕選擇 😊", GENDER_OPTIONS, back=True, cancel=True)]
        db.update_active_child(user_id, gender=GENDER_CODE[text])
        db.set_onboarding_state(user_id, 'done')
        return [_text("✅ 性別已更新！\n\n有什麼育兒問題想問我嗎？😊")]

    if state == 'edit_birth_order':
        if text not in BIRTH_ORDER_OPTIONS:
            return [_flex_choice("請點選下方按鈕選擇 😊", BIRTH_ORDER_OPTIONS, back=True, cancel=True)]
        order_code = BIRTH_ORDER_CODE[text]
        active = db.get_active_child(user_id)
        if _birth_order_taken(user_id, order_code, exclude_child_id=active.get('child_id')):
            return [_flex_choice(
                f"{text}已經有其他寶寶登記了，請重新選擇",
                BIRTH_ORDER_OPTIONS, back=True, cancel=True
            )]
        db.update_active_child(user_id, birth_order=order_code)
        db.set_onboarding_state(user_id, 'done')
        return [_text("✅ 胎次已更新！\n\n有什麼育兒問題想問我嗎？😊")]

    if state == 'edit_special_status':
        codes = _parse_special_status(text)
        if codes is None:
            return [_text("輸入格式不對喔 😅\n" + _SPECIAL_STATUS_PROMPT, ["以上皆無"])]
        db.update_active_child(user_id, special_status=','.join(codes))
        db.set_onboarding_state(user_id, 'done')
        return [_text("✅ 特殊身分已更新！\n\n有什麼育兒問題想問我嗎？😊")]

    return []


def after_birthday_postback(user_id: str, date_str: str, current_state: str = '') -> list[TextMessage]:
    """處理 DatetimePicker 回傳的生日。onboarding 推進到性別；edit 模式直接完成。"""
    db.update_active_child(user_id, birth_date=date_str)
    over_age = is_over_service_age(date_str)

    if current_state == 'edit_child_birthday':
        db.set_onboarding_state(user_id, 'done')
        msgs = [_text(f"✅ 生日已更新為 {date_str}！\n\n有什麼育兒問題想問我嗎？😊")]
        if over_age:
            msgs.append(_text(
                "⚠️ 提醒：育兒小幫手目前主要服務 0～3 歲寶寶，"
                "寶寶已達 3 歲以上，部分資訊可能不完全適用喔！"
            ))
        return msgs

    # onboarding 模式：年齡超限則阻擋，不前進到性別步驟
    if over_age:
        msg = TextMessage(
            type="text",
            text=(
                f"已記錄日期：{date_str}\n\n"
                "⚠️ 育兒小幫手目前主要服務 0～3 歲寶寶，\n"
                "您選擇的生日顯示寶寶已達 3 歲以上。\n\n"
                "填錯了嗎？請重新選擇日期；\n"
                "如果確認是此生日，請點「確認繼續」"
            ),
        )
        msg.quick_reply = QuickReply(items=[
            QuickReplyItem(action=DatetimePickerAction(
                label="📅 重新選擇", data="action=set_birthday", mode="date",
            )),
            QuickReplyItem(action=MessageAction(label="確認繼續", text="確認繼續")),
        ])
        return [msg]

    db.set_onboarding_state(user_id, 'waiting_child_gender')
    return [
        _text(f"已記錄生日：{date_str} 🎂"),
        _flex_choice("請選擇寶寶的性別", GENDER_OPTIONS),
    ]


# ── Profile Display ────────────────────────────────────────────────────────────

def show_profile(user: dict, child: dict) -> TextMessage:
    parent  = user.get('parent_name') or '（未設定）'
    phone   = user.get('phone_number') or '（未設定）'
    city    = user.get('city') or '（未設定）'
    employ  = EMPLOYMENT_LABEL.get(user.get('parental_employment', ''), '（未設定）')
    baby    = child.get('child_name') or '（未設定）'
    bday    = str(child.get('birth_date') or '（未設定）')
    gender  = GENDER_LABEL.get(child.get('gender', ''), '（未設定）')
    order   = BIRTH_ORDER_LABEL.get(child.get('birth_order'), '（未設定）')

    raw_status = child.get('special_status') or ''
    if raw_status:
        status = '、'.join(SPECIAL_STATUS_LABEL.get(c, c) for c in raw_status.split(',') if c)
    else:
        status = '以上皆無'

    text = (
        "📋 我的資料\n"
        "─────────────\n"
        f"家長姓名：{parent}\n"
        f"手機號碼：{phone}\n"
        f"所在縣市：{city}\n"
        f"就業狀況：{employ}\n"
        "─────────────\n"
        f"寶寶名字：{baby}\n"
        f"生日／預產期：{bday}\n"
        f"性別：{gender}\n"
        f"胎次：{order}\n"
        f"特殊身分：{status}\n"
        "─────────────\n"
        "需要修改嗎？"
    )
    return _text(text, ["修改資料", "新增寶寶", "不用，謝謝"])


def child_select_message(children: list[dict]) -> FlexMessage:
    return _child_carousel(children)


# ── Internal Helpers ──────────────────────────────────────────────────────────

def _child_info_card(child: dict) -> TextMessage:
    name   = child.get('child_name') or '寶寶'
    bday   = str(child.get('birth_date') or '（未設定）')
    gender = GENDER_LABEL.get(child.get('gender', ''), '（未設定）')
    order  = BIRTH_ORDER_LABEL.get(child.get('birth_order'), '（未設定）')
    age    = _age_str(child.get('birth_date'))
    raw_status = child.get('special_status') or ''
    status = '、'.join(SPECIAL_STATUS_LABEL.get(c, c) for c in raw_status.split(',') if c) if raw_status else '以上皆無'
    age_str = f"（{age}）" if age else ""
    return _text(
        f"👶 {name}{age_str} 的資料\n"
        f"─────────────\n"
        f"生日／預產期：{bday}\n"
        f"性別：{gender}\n"
        f"胎次：{order}\n"
        f"特殊身分：{status}"
    )


def _child_carousel(children: list[dict]) -> FlexMessage:
    """可左右滑動的寶寶資料卡片選單。每張卡顯示基本資料，點按鈕即切換。"""

    def _row(label: str, value: str) -> dict:
        return {
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#AAAAAA", "flex": 3},
                {"type": "text", "text": value, "size": "sm", "color": "#333333",
                 "flex": 5, "wrap": True},
            ],
        }

    bubbles = []
    for i, child in enumerate(children, 1):
        name       = child.get('child_name') or f'寶寶{i}'
        age        = _age_str(child.get('birth_date'))
        bday       = str(child.get('birth_date') or '（未設定）')
        gender     = GENDER_LABEL.get(child.get('gender', ''), '（未設定）')
        order      = BIRTH_ORDER_LABEL.get(child.get('birth_order'), '（未設定）')
        raw_status = child.get('special_status') or ''
        status     = '、'.join(SPECIAL_STATUS_LABEL.get(c, c)
                               for c in raw_status.split(',') if c) if raw_status else '以上皆無'
        age_text   = f"{age}大" if age and age != "預產中" else (age or "年齡未設定")

        bubbles.append({
            "type": "bubble",
            "size": "kilo",
            "header": {
                "type": "box", "layout": "vertical",
                "backgroundColor": "#FFF0F5", "paddingAll": "18px",
                "contents": [
                    {"type": "text", "text": f"👶 {name}",
                     "weight": "bold", "size": "lg", "color": "#2D3748"},
                    {"type": "text", "text": age_text,
                     "size": "sm", "color": "#AAAAAA", "margin": "xs"},
                ],
            },
            "body": {
                "type": "box", "layout": "vertical",
                "spacing": "xs", "paddingAll": "16px",
                "contents": [
                    _row("生日", bday),
                    _row("性別", gender),
                    _row("胎次", order),
                    {"type": "separator", "margin": "sm"},
                    _row("特殊身分", status),
                ],
            },
            "footer": {
                "type": "box", "layout": "vertical", "paddingAll": "12px",
                "contents": [{
                    "type": "button",
                    "style": "primary",
                    "color": "#FF8FAB",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": f"✓ 選擇{name}",
                        "text": f"{i}. {name}",
                    },
                }],
            },
        })

    return FlexMessage(
        alt_text=f"請左右滑動選擇寶寶（共 {len(children)} 位）",
        contents=FlexContainer.from_dict({"type": "carousel", "contents": bubbles}),
    )


def _flex_choice(title: str, options: list[str],
                 back: bool = False, cancel: bool = False) -> FlexMessage:
    """粉紅卡片選項 Flex Message，風格與寶寶卡片一致。
    back=True 加「上一步」按鈕；cancel=True 加「取消」按鈕。
    """
    body: list[dict] = []
    for opt in options:
        emoji = _OPTION_EMOJIS.get(opt, "")
        label = f"{emoji}  {opt}" if emoji else opt
        body.append({
            "type": "button", "style": "primary", "color": "#FF8FAB",
            "height": "sm", "margin": "xs",
            "action": {"type": "message", "label": label, "text": opt},
        })

    if back or cancel:
        body.append({"type": "separator", "margin": "lg"})
        nav: list[dict] = []
        if back:
            nav.append({
                "type": "button", "style": "secondary", "height": "sm", "flex": 1,
                "action": {"type": "message", "label": "← 上一步", "text": "上一步"},
            })
        if cancel:
            nav.append({
                "type": "button", "style": "secondary", "height": "sm", "flex": 1,
                "action": {"type": "message", "label": "✕ 取消", "text": "取消"},
            })
        body.append({
            "type": "box", "layout": "horizontal",
            "spacing": "sm", "margin": "sm", "contents": nav,
        })

    bubble = {
        "type": "bubble",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": "#FFF0F5", "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": title, "weight": "bold",
                 "size": "md", "color": "#2D3748", "wrap": True},
            ],
        },
        "body": {
            "type": "box", "layout": "vertical",
            "paddingAll": "12px", "spacing": "none",
            "contents": body,
        },
    }
    return FlexMessage(
        alt_text=title,
        contents=FlexContainer.from_dict(bubble),
    )


def _region_carousel() -> FlexMessage:
    """五大地區 Flex 卡片輪播，每張顯示地區名＋所屬縣市清單。"""
    _EMOJI = {"北部": "🏙️", "中部": "🌾", "南部": "☀️", "東部": "🏞️", "離島": "🏝️"}
    bubbles = []
    for region, cities in _REGIONS.items():
        bubbles.append({
            "type": "bubble", "size": "kilo",
            "header": {
                "type": "box", "layout": "vertical",
                "backgroundColor": "#FFF0F5", "paddingAll": "16px",
                "contents": [
                    {"type": "text",
                     "text": f"{_EMOJI.get(region, '')} {region}",
                     "weight": "bold", "size": "lg", "color": "#2D3748"},
                ],
            },
            "body": {
                "type": "box", "layout": "vertical", "paddingAll": "14px",
                "contents": [
                    {"type": "text", "text": "、".join(cities),
                     "size": "sm", "color": "#666666", "wrap": True},
                ],
            },
            "footer": {
                "type": "box", "layout": "vertical", "paddingAll": "12px",
                "contents": [{
                    "type": "button", "style": "primary", "color": "#FF8FAB",
                    "height": "sm",
                    "action": {"type": "message",
                               "label": f"選擇{region}", "text": region},
                }],
            },
        })
    return FlexMessage(
        alt_text="請選擇您所在的地區",
        contents=FlexContainer.from_dict({"type": "carousel", "contents": bubbles}),
    )


def _city_carousel(region: str, back_text: str = "上一步",
                   back_label: str = "← 上一步") -> FlexMessage:
    """指定地區的縣市 Flex 卡片輪播。每張卡含選擇按鈕與返回按鈕。"""
    bubbles = []
    for city in _REGIONS[region]:
        bubbles.append({
            "type": "bubble", "size": "nano",
            "header": {
                "type": "box", "layout": "vertical",
                "backgroundColor": "#FFF0F5", "paddingAll": "16px",
                "contents": [
                    {"type": "text", "text": city, "weight": "bold",
                     "size": "lg", "color": "#2D3748"},
                    {"type": "text", "text": region, "size": "xs",
                     "color": "#AAAAAA", "margin": "xs"},
                ],
            },
            "footer": {
                "type": "box", "layout": "vertical",
                "paddingAll": "10px", "spacing": "xs",
                "contents": [
                    {"type": "button", "style": "primary", "color": "#FF8FAB",
                     "height": "sm",
                     "action": {"type": "message", "label": "✓ 選擇", "text": city}},
                    {"type": "button", "style": "secondary", "height": "sm",
                     "action": {"type": "message",
                                "label": back_label, "text": back_text}},
                ],
            },
        })
    return FlexMessage(
        alt_text=f"請選擇{region}的縣市",
        contents=FlexContainer.from_dict({"type": "carousel", "contents": bubbles}),
    )


def _child_options(children: list[dict]) -> list[str]:
    options = []
    for i, child in enumerate(children, 1):
        name = child.get('child_name') or f'寶寶{i}'
        age  = _age_str(child.get('birth_date'))
        suffix = f"（{age}）" if age else ""
        options.append(f"{i}. {name}{suffix}")
    return options


def is_over_service_age(birth_date) -> bool:
    """寶寶是否已達 3 歲（36 個月）以上——超出目前服務年齡範圍。"""
    if not birth_date:
        return False
    try:
        bd = datetime.strptime(str(birth_date), "%Y-%m-%d").date() if isinstance(birth_date, str) else birth_date
        months = (date.today().year - bd.year) * 12 + (date.today().month - bd.month)
        return months >= 36
    except Exception:
        return False


def _age_str(birth_date) -> str:
    if not birth_date:
        return ""
    try:
        from datetime import datetime
        bd = datetime.strptime(str(birth_date), "%Y-%m-%d").date() if isinstance(birth_date, str) else birth_date
        months = (date.today().year - bd.year) * 12 + (date.today().month - bd.month)
        if months < 0:
            return "預產中"
        return f"{months}個月" if months < 24 else f"{months // 12}歲"
    except Exception:
        return ""


def _edit_prompt(state: str):
    """依照 edit_* state 回傳對應的提問（TextMessage 或 FlexMessage）。"""
    _NAV_HINT = "\n（輸入「上一步」返回，「取消」離開修改）"
    if state == 'edit_child_birthday':
        return _ask_birthday(include_nav=True)
    if state == 'edit_parental_employment':
        return _flex_choice("請選擇就業狀況", EMPLOYMENT_OPTIONS, back=True, cancel=True)
    if state == 'edit_child_gender':
        return _flex_choice("請選擇寶寶的性別", GENDER_OPTIONS, back=True, cancel=True)
    if state == 'edit_birth_order':
        return _flex_choice("請選擇寶寶是第幾胎", BIRTH_ORDER_OPTIONS, back=True, cancel=True)
    if state == 'edit_city':
        return _region_carousel()
    if state == 'edit_special_status':
        return _text(_SPECIAL_STATUS_PROMPT + _NAV_HINT, ["以上皆無", "上一步", "取消"])
    text_prompts = {
        'edit_parent_name':  f"請輸入新的姓名（{_MAX_NAME_LEN} 字以內）：" + _NAV_HINT,
        'edit_phone_number': "請輸入新的手機號碼\n格式：09XXXXXXXX（10碼）" + _NAV_HINT,
        'edit_child_name':   f"請輸入寶寶的新名字（{_MAX_NAME_LEN} 字以內）：" + _NAV_HINT,
    }
    return _text(text_prompts.get(state, "請輸入新的值：" + _NAV_HINT))


def _birth_order_taken(user_id: str, order_code: int, exclude_child_id=None) -> bool:
    """檢查同一用戶是否已有其他孩子使用相同胎次。"""
    for child in db.get_children(user_id):
        if child.get('birth_order') == order_code:
            if exclude_child_id is None or child['child_id'] != exclude_child_id:
                return True
    return False


def _parse_special_status(text: str) -> list[str] | None:
    """解析特殊身分輸入，例如 '01 05 09'，回傳代碼列表；格式錯誤回傳 None。"""
    text = text.strip()
    if text in ("以上皆無", "無", "沒有", "none"):
        return []
    codes = []
    for token in text.split():
        key = token.zfill(2)  # 接受 "1" 或 "01" 兩種格式
        if key not in SPECIAL_STATUS_MAP:
            return None
        code = SPECIAL_STATUS_MAP[key]
        if code not in codes:
            codes.append(code)
    return codes or None
