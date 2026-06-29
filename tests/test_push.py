"""Test push notification logic and LINE delivery.

Usage:
  # 只測邏輯（不需要 LINE 憑證）
  python tests/test_push.py

  # 測試實際推播到你的 LINE（需要先完成 onboarding）
  python tests/test_push.py <YOUR_LINE_USER_ID>

取得自己的 LINE User ID：在 Bot 聊天室輸入任何訊息，查看 server log 的
  "收到訊息：user=Uxxxxxxxxxx" 那一行。
"""

import os
import sys
import time
from datetime import date, timedelta

# 讓 tests/ 目錄可以 import 專案根目錄的模組
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from push_scheduler import (
    _add_months,
    _due_health_events,
    _build_health_message,
    _get_milestone_message,
    _VACCINE_SCHEDULE,
    _CHECKUP_SCHEDULE,
    _MILESTONE_SCHEDULE,
)


# ── 輔助：用今天往回推算一個「正好命中」的生日 ──────────────────────────────────

def _birth_for_months_ago(months: int) -> date:
    """Return a birth_date such that today is exactly `months` months after birth."""
    today = date.today()
    y = today.year - (1 if today.month <= months % 12 else 0)
    m = (today.month - months - 1) % 12 + 1
    import calendar
    d = min(today.day, calendar.monthrange(y, m)[1])
    return date(y, m, d)


# ── 測試 1：邏輯驗證（不需要 LINE 憑證） ────────────────────────────────────────

def test_logic():
    today = date.today()
    print(f"今天：{today}\n")

    # 驗證每個疫苗月齡的 due_date 計算是否正確
    print("=== 疫苗到期日計算 ===")
    birth = date(2024, 10, 15)  # 任意生日
    for months, vaccines in _VACCINE_SCHEDULE.items():
        due = _add_months(birth, months)
        print(f"  {months:2d} 個月 → {due}  {', '.join(vaccines)}")

    # 模擬：寶寶恰好是「2 個月前」出生 → 應觸發 2 個月接種提醒（days_until == 0）
    print("\n=== days_until == 0 測試（2 個月里程碑）===")
    birth_2mo = _birth_for_months_ago(2)
    events = _due_health_events(birth_2mo, today)
    if events:
        msg = _build_health_message("小明", events, today)
        print(msg)
        print("✅ 成功觸發健康提醒")
    else:
        print(f"  生日 {birth_2mo} → 今天沒有命中任何健康事件")
        print("  （若生日月份的天數不同可能差 1 天，屬正常）")

    # 模擬：7 天後是 4 個月里程碑 → 應觸發 7 天前提醒
    print("\n=== days_until == 7 測試（4 個月里程碑，提前 7 天）===")
    four_month_due = _add_months(today, 4) if False else None
    birth_4mo_7d = _birth_for_months_ago(4) + timedelta(days=7)  # 往後推 7 天讓 due 落在 today+7
    # 直接手動製造 days_until==7 的情境：birth = today + 7 天 - 4個月
    from push_scheduler import _add_months as am
    test_birth = date(today.year, today.month, today.day)
    # birth such that birth + 4mo = today + 7
    target_due = today + timedelta(days=7)
    y = target_due.year - (1 if target_due.month <= 4 else 0)
    m = (target_due.month - 5) % 12 + 1
    import calendar
    d = min(target_due.day, calendar.monthrange(y, m)[1])
    birth_7d_before_4mo = date(y, m, d)
    events7 = _due_health_events(birth_7d_before_4mo, today)
    if events7:
        msg7 = _build_health_message("小花", events7, today)
        print(msg7)
        print("✅ 成功觸發 7 天前提醒")
    else:
        print(f"  生日 {birth_7d_before_4mo} → 今天沒有命中（日期邊界可能差 1 天）")

    # 里程碑：寶寶恰好今天滿 6 個月
    print("\n=== 里程碑測試（滿 6 個月）===")
    birth_6mo = _birth_for_months_ago(6)
    msg = _get_milestone_message(birth_6mo, "小明", today)
    if msg:
        print(msg)
        print("✅ 成功觸發里程碑")
    else:
        print(f"  生日 {birth_6mo} → 今天不是精確滿月日（差 1 天則不觸發，屬正常）")

    # 顯示所有里程碑訊息樣本
    print("\n=== 里程碑訊息範本（全部月齡）===")
    for age, desc in _MILESTONE_SCHEDULE.items():
        fake_birth = _birth_for_months_ago(age)
        fake_today = _add_months(fake_birth, age)  # 假設今天就是那天
        sample = _get_milestone_message(fake_birth, "小明", fake_today)
        if sample:
            print(f"\n[{age:2d} 個月]\n{sample}")


# ── 測試 2：實際 LINE 推播（需要真實憑證 + LINE User ID）───────────────────────

def test_line_push(user_id: str):
    import config
    if not config.LINE_CHANNEL_ACCESS_TOKEN:
        print("❌ LINE_CHANNEL_ACCESS_TOKEN 未設定，請確認 config.ini 或環境變數")
        return

    from push_scheduler import _line_push

    today = date.today()

    # 1. 健康提醒（疫苗 + 健檢合併，使用假資料）
    fake_events = {
        today: [
            ("vaccine", "五合一疫苗（第2劑）【測試】"),
            ("vaccine", "13價肺炎鏈球菌疫苗（第2劑）【測試】"),
            ("checkup", "第3次兒童預防保健（嬰兒期）【測試】"),
        ],
        today + timedelta(days=7): [
            ("vaccine", "B型肝炎疫苗（第3劑）【7天前預告測試】"),
        ],
    }
    health_msg = _build_health_message("測試寶寶", fake_events, today)
    _line_push(user_id, health_msg)
    print("✅ 健康提醒推播完成")
    time.sleep(0.5)

    # 2. 里程碑
    milestone_msg = (
        "🌟 測試寶寶 滿 6 個月了！【測試】\n\n"
        "這個月的發展里程碑：\n"
        "• 扶著可以坐、可以開始嘗試副食品\n\n"
        "每個寶寶步調不同，以上為一般參考。\n"
        "若有疑慮請諮詢兒科醫師 😊"
    )
    _line_push(user_id, milestone_msg)
    print("✅ 里程碑推播完成")
    time.sleep(0.5)

    # 3. 政策提醒（固定假訊息，不呼叫 RAG，避免依賴外部服務）
    policy_msg = (
        "📋 本週政策申請提醒【測試】\n\n"
        "• 台北市育兒津貼：本月底截止\n"
        "• 托育補助：出生後 6 個月內申請\n\n"
        "（資料每週一自動更新，以政府最新公告為準）"
    )
    _line_push(user_id, policy_msg)
    print("✅ 政策提醒推播完成（假資料）")


# ── 測試 3：完整流程（從 DB 撈真實用戶，走真正的推播邏輯）─────────────────────

def test_full_pipeline():
    """觸發與 server 相同的完整推播流程，但不受時間限制（疫苗/里程碑條件要符合才會推）。"""
    print("=== 完整推播流程（等同 /admin/push-now）===")
    from push_scheduler import run_daily_push
    run_daily_push()
    print("完成。若無輸出代表目前沒有用戶符合推播條件。")


# ── 入口 ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("Step 1：測試推播邏輯（不需要 LINE 憑證）")
    print("=" * 50)
    test_logic()

    if len(sys.argv) > 1:
        user_id = sys.argv[1]
        print("\n" + "=" * 50)
        print(f"Step 2：測試實際 LINE 推播 → {user_id}")
        print("=" * 50)
        test_line_push(user_id)

        print("\n" + "=" * 50)
        print("Step 3：完整推播流程（走 DB 真實資料）")
        print("=" * 50)
        test_full_pipeline()
    else:
        print("\n" + "=" * 50)
        print("提示：傳入你的 LINE User ID 可測試實際推播")
        print("用法：python tests/test_push.py U1234567890abcdef")
        print("\n取得 LINE User ID 方式：")
        print("  1. 啟動 server：python main.py")
        print("  2. 在 LINE Bot 聊天室送任意訊息")
        print("  3. 查看 server log 的「收到訊息：user=Uxxxxxxxxxx」")
        print("=" * 50)
