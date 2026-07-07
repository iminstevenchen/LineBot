import logging
from contextlib import contextmanager
from typing import Optional

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

import config

logger = logging.getLogger(__name__)

_pool: Optional[ThreadedConnectionPool] = None


def get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        if not config.DATABASE_URL:
            raise RuntimeError("DATABASE_URL 未設定，請檢查 .env 檔案")
        _pool = ThreadedConnectionPool(
            minconn=config.DB_POOL_MIN,
            maxconn=config.DB_POOL_MAX,
            dsn=config.DATABASE_URL,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
        )
        logger.info("PostgreSQL 連線池初始化完成")
    return _pool


@contextmanager
def get_conn():
    global _pool
    pool = get_pool()
    conn = pool.getconn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    try:
        # Ping to detect stale connections; replace if broken
        try:
            conn.cursor().execute("SELECT 1")
        except psycopg2.Error:
            pool.putconn(conn, close=True)
            conn = pool.getconn()
            conn.cursor_factory = psycopg2.extras.RealDictCursor
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── 建表 ────────────────────────────────────────────────────────────────────────

def init_tables() -> None:
    create_sql = """
        CREATE TABLE IF NOT EXISTS user_profiles (
            line_user_id         VARCHAR(64)  PRIMARY KEY,
            parent_name          VARCHAR(50),
            phone_number         VARCHAR(20),
            city                 VARCHAR(50),
            parental_employment  VARCHAR(30),
            active_child_id      BIGINT,
            onboarding_state     VARCHAR(30)  NOT NULL DEFAULT 'new',
            created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            -- legacy columns kept for backward compat
            user_nickname        VARCHAR(50),
            baby_birthday_or_due_date DATE,
            baby_gender          VARCHAR(10),
            region               VARCHAR(50),
            interests            JSONB
        );

        CREATE TABLE IF NOT EXISTS children (
            child_id       BIGSERIAL    PRIMARY KEY,
            line_user_id   VARCHAR(64)  NOT NULL REFERENCES user_profiles(line_user_id),
            child_name     VARCHAR(50),
            birth_date     DATE,
            gender         VARCHAR(10),
            birth_order    INT,
            special_status TEXT,
            created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS chat_histories (
            message_id   BIGSERIAL    PRIMARY KEY,
            line_user_id VARCHAR(64)  NOT NULL REFERENCES user_profiles(line_user_id),
            role         VARCHAR(10)  NOT NULL CHECK (role IN ('user', 'assistant')),
            content      TEXT         NOT NULL,
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """
    alter_sql = """
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS parent_name         VARCHAR(50);
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS phone_number        VARCHAR(20);
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS city                VARCHAR(50);
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS parental_employment VARCHAR(30);
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS active_child_id     BIGINT;
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS user_nickname       VARCHAR(50);
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS baby_birthday_or_due_date DATE;
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS baby_gender         VARCHAR(10);
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS region              VARCHAR(50);
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS interests           JSONB;
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS onboarding_state   VARCHAR(30) NOT NULL DEFAULT 'new';
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW();
        ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW();
    """
    index_sql = """
        CREATE INDEX IF NOT EXISTS idx_chat_histories_user_time
            ON chat_histories (line_user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_children_user
            ON children (line_user_id);
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(create_sql)
            cur.execute(alter_sql)
            cur.execute(index_sql)
        conn.commit()
    logger.info("資料表初始化完成")


# ── user_profiles ───────────────────────────────────────────────────────────────

def get_or_create_user(line_user_id: str) -> dict:
    sql_select = "SELECT * FROM user_profiles WHERE line_user_id = %s"
    sql_insert = """
        INSERT INTO user_profiles (line_user_id)
        VALUES (%s)
        ON CONFLICT (line_user_id) DO NOTHING
        RETURNING *
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_select, (line_user_id,))
            row = cur.fetchone()
            if row is None:
                cur.execute(sql_insert, (line_user_id,))
                row = cur.fetchone()
                conn.commit()
                logger.info("新用戶建立：%s", line_user_id)
    return dict(row) if row else {"line_user_id": line_user_id}


def update_user_profile(line_user_id: str,
                        parent_name: str = None,
                        phone_number: str = None,
                        city: str = None,
                        parental_employment: str = None) -> None:
    sql = """
        UPDATE user_profiles
        SET parent_name          = COALESCE(%s, parent_name),
            phone_number         = COALESCE(%s, phone_number),
            city                 = COALESCE(%s, city),
            parental_employment  = COALESCE(%s, parental_employment),
            updated_at           = NOW()
        WHERE line_user_id = %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (parent_name, phone_number, city, parental_employment, line_user_id))
        conn.commit()
    logger.info("update_user_profile %s parent=%s phone=%s city=%s employ=%s",
                line_user_id, parent_name, phone_number, city, parental_employment)


def set_onboarding_state(line_user_id: str, state: str) -> None:
    sql = "UPDATE user_profiles SET onboarding_state = %s, updated_at = NOW() WHERE line_user_id = %s"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (state, line_user_id))
        conn.commit()


# ── children ─────────────────────────────────────────────────────────────────────

def create_child(line_user_id: str) -> int:
    """建立新孩子記錄並設為活躍孩子，回傳 child_id。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO children (line_user_id) VALUES (%s) RETURNING child_id",
                (line_user_id,)
            )
            child_id = cur.fetchone()['child_id']
            cur.execute(
                "UPDATE user_profiles SET active_child_id = %s WHERE line_user_id = %s",
                (child_id, line_user_id)
            )
        conn.commit()
    logger.info("建立孩子記錄：user=%s child_id=%d", line_user_id, child_id)
    return child_id


def update_active_child(line_user_id: str,
                        child_name: str = None,
                        birth_date: str = None,
                        gender: str = None,
                        birth_order: int = None,
                        special_status: str = None) -> None:
    """更新活躍孩子欄位。"""
    sql = """
        UPDATE children
        SET child_name     = COALESCE(%s, child_name),
            birth_date     = COALESCE(%s, birth_date),
            gender         = COALESCE(%s, gender),
            birth_order    = COALESCE(%s, birth_order),
            special_status = COALESCE(%s, special_status)
        WHERE child_id = (
            SELECT active_child_id FROM user_profiles WHERE line_user_id = %s
        )
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (child_name, birth_date, gender, birth_order, special_status, line_user_id))
        conn.commit()


def get_active_child(line_user_id: str) -> dict:
    """取得活躍孩子資料；無孩子時回傳空 dict。"""
    sql = """
        SELECT c.* FROM children c
        JOIN user_profiles u ON c.child_id = u.active_child_id
        WHERE u.line_user_id = %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (line_user_id,))
            row = cur.fetchone()
    return dict(row) if row else {}


def get_children(line_user_id: str) -> list[dict]:
    """取得此用戶所有孩子資料（由建立時間舊到新）。"""
    sql = "SELECT * FROM children WHERE line_user_id = %s ORDER BY created_at ASC"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (line_user_id,))
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def set_active_child(line_user_id: str, child_id: int) -> None:
    """切換活躍孩子。"""
    sql = "UPDATE user_profiles SET active_child_id = %s WHERE line_user_id = %s"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (child_id, line_user_id))
        conn.commit()


# ── chat_histories ──────────────────────────────────────────────────────────────

def save_message(line_user_id: str, role: str, content: str) -> None:
    sql = "INSERT INTO chat_histories (line_user_id, role, content) VALUES (%s, %s, %s)"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (line_user_id, role, content))
        conn.commit()


def get_recent_history(line_user_id: str, limit: int = 10) -> list[dict]:
    """取得最近 N 筆對話紀錄（由舊到新）。"""
    sql = """
        SELECT role, content, created_at
        FROM chat_histories
        WHERE line_user_id = %s
        ORDER BY created_at DESC
        LIMIT %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (line_user_id, limit))
            rows = cur.fetchall()
    return [dict(r) for r in reversed(rows)]


def get_all_active_users_with_children() -> list[tuple[dict, dict]]:
    """Return (user_dict, child_dict) for every completed-onboarding user with a birth_date."""
    sql = """
        SELECT
            u.line_user_id, u.parent_name, u.city, u.parental_employment,
            c.child_id, c.child_name, c.birth_date, c.gender, c.birth_order, c.special_status
        FROM user_profiles u
        JOIN children c ON c.child_id = u.active_child_id
        WHERE u.onboarding_state = 'done'
          AND c.birth_date IS NOT NULL
    """
    _user_keys  = {"line_user_id", "parent_name", "city", "parental_employment"}
    _child_keys = {"child_id", "child_name", "birth_date", "gender", "birth_order", "special_status"}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    result = []
    for row in rows:
        row = dict(row)
        result.append(
            ({k: row[k] for k in _user_keys},
             {k: row[k] for k in _child_keys})
        )
    return result


def lookup_website_profile_by_phone(phone: str) -> dict:
    """查詢網站 users 表中是否有此手機號碼的資料；找不到或表不存在則回傳 {}。"""
    sql = """
        SELECT user_nickname, baby_name, baby_birthday_or_due_date,
               baby_gender, region
        FROM users
        WHERE phone = %s
        LIMIT 1
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (phone,))
                row = cur.fetchone()
        return dict(row) if row else {}
    except Exception as e:
        logger.warning("查詢網站用戶失敗（users 表可能不存在）: %s", e)
        return {}


def import_website_profile(line_user_id: str, phone: str) -> bool:
    """
    從網站 users 表匯入用戶資料至 LINE bot 資料表，並在 users 表寫入 line_user_id。
    回傳 True 若成功匯入。
    """
    website_user = lookup_website_profile_by_phone(phone)
    if not website_user:
        return False

    _GENDER = {'male': '男', 'female': '女'}
    gender = _GENDER.get(website_user.get('baby_gender') or '', '') or None

    update_user_profile(
        line_user_id,
        parent_name=website_user.get('user_nickname') or None,
        city=website_user.get('region') or None,
    )

    baby_name = website_user.get('baby_name')
    baby_birthday = website_user.get('baby_birthday_or_due_date')
    if baby_name or baby_birthday:
        create_child(line_user_id)
        update_active_child(
            line_user_id,
            child_name=baby_name or None,
            birth_date=str(baby_birthday) if baby_birthday else None,
            gender=gender,
        )

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET line_user_id = %s WHERE phone = %s",
                    (line_user_id, phone)
                )
            conn.commit()
    except Exception as e:
        logger.warning("寫入 line_user_id 至 users 表失敗: %s", e)

    return True


def trim_chat_history(line_user_id: str, keep: int = 30) -> None:
    """只保留最近 keep 筆對話，超出的舊訊息刪除。"""
    sql = """
        DELETE FROM chat_histories
        WHERE line_user_id = %s
          AND message_id NOT IN (
              SELECT message_id FROM chat_histories
              WHERE line_user_id = %s
              ORDER BY created_at DESC
              LIMIT %s
          )
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (line_user_id, line_user_id, keep))
            deleted = cur.rowcount
        conn.commit()
    if deleted > 0:
        logger.info("清理舊對話：%s 刪除 %d 筆，保留最近 %d 筆", line_user_id, deleted, keep)
