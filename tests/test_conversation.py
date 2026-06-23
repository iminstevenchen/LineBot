"""
對話流程測試腳本（不需要 LINE / ngrok）
直接在終端機模擬一個完整對話，驗證記憶、RAG、LLM 是否正常運作。

執行方式：
    source venv/bin/activate
    cd tests && python test_conversation.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import llm
import rag_mock

TEST_USER_ID = "test_local_user_001"

# ── 模擬用戶資料（如果 DB 裡沒有，就用這個預設值）─────────────────────────────
MOCK_USER = {
    "line_user_id": TEST_USER_ID,
    "user_nickname": "小寶",
    "baby_birthday_or_due_date": "2025-06-01",
    "baby_gender": "男",
    "region": "台北市",
    "interests": "疫苗,健康檢查",
    "onboarding_state": "done",
}

# ── 測試對話劇本 ───────────────────────────────────────────────────────────────
CONVERSATION = [
    "寶寶最近大便是綠色的，正常嗎？",
    "那我要注意什麼？",           # 追問：測試脈絡記憶
    "寶寶現在要打什麼疫苗？",     # 測試生日 → 計算月齡
    "有育兒補助可以申請嗎？",
]


def get_user_context() -> dict:
    """從 DB 取用戶資料，不存在就用測試假資料。"""
    try:
        db.get_pool()
        user = db.get_or_create_user(TEST_USER_ID)
        if user.get("onboarding_state") != "done":
            db.update_user_profile(
                TEST_USER_ID,
                nickname=MOCK_USER["user_nickname"],
                baby_birthday=str(MOCK_USER["baby_birthday_or_due_date"]),
                baby_gender=MOCK_USER["baby_gender"],
                region=MOCK_USER["region"],
                interests=MOCK_USER["interests"],
            )
            db.set_onboarding_state(TEST_USER_ID, "done")
            user = db.get_or_create_user(TEST_USER_ID)
        return user
    except Exception as e:
        print(f"[警告] DB 連線失敗，使用本地假資料：{e}\n")
        return MOCK_USER


def simulate_message(text: str, user_context: dict, use_db: bool) -> str:
    """模擬一次訊息處理流程，回傳機器人回覆。"""
    if use_db:
        history = db.get_recent_history(TEST_USER_ID, limit=20)
        db.save_message(TEST_USER_ID, "user", text)
    else:
        history = []

    rag_query = llm.build_rag_query(text, user_context, history)
    rag_chunks = rag_mock.query_mock_rag(rag_query)

    reply = llm.generate_reply(text, user_context, rag_chunks, history)

    if use_db:
        db.save_message(TEST_USER_ID, "assistant", reply)

    return reply, len(history), len(rag_chunks)


def main():
    print("=" * 60)
    print("育兒小幫手 對話流程測試")
    print("=" * 60)

    # 檢查 DB 是否可用
    use_db = True
    try:
        db.get_pool()
        print("[DB] Supabase 連線成功\n")
    except Exception:
        use_db = False
        print("[DB] 無法連線，跳過 DB（記憶功能不會測試）\n")

    user_context = get_user_context()
    print(f"[用戶] 暱稱：{user_context.get('user_nickname')}，"
          f"生日：{user_context.get('baby_birthday_or_due_date')}\n")
    print("-" * 60)

    for i, message in enumerate(CONVERSATION, 1):
        print(f"\n[第 {i} 輪] 用戶：{message}")

        reply, history_len, rag_hits = simulate_message(message, user_context, use_db)

        print(f"[記憶]  撈到 {history_len} 筆歷史對話")
        print(f"[RAG]   命中 {rag_hits} 個知識片段")
        print(f"[回覆]  {reply}")
        print("-" * 60)

    print("\n測試完成！")
    if use_db:
        history = db.get_recent_history(TEST_USER_ID, limit=20)
        print(f"DB 中共有 {len(history)} 筆對話記錄（line_user_id={TEST_USER_ID}）")


if __name__ == "__main__":
    main()
