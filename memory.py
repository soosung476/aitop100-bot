# 대화 기억과 기록(예: 주문서)을 SQLite 파일에 저장한다
# SQLite: 파일 하나로 쓰는 작은 데이터베이스 (파이썬에 기본으로 들어 있어 따로 설치할 필요가 없다)
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# 저장 위치: 기본은 state/bot.db, 시험할 때는 BOT_DB_PATH 환경변수로 다른 파일을 쓸 수 있다
DB_PATH = Path(os.getenv("BOT_DB_PATH", Path(__file__).parent / "state" / "bot.db"))

# 사용자별로 기억할 최근 질문 수 (넘으면 오래된 대화부터 잊는다)
MAX_TURNS = 20
# 이 시간(분) 동안 말이 없으면 새 대화로 시작한다
# (심사위원이 같은 채팅방에서 다른 시나리오를 이어서 시험해도 앞 대화와 섞이지 않게)
SESSION_MINUTES = int(os.getenv("SESSION_MINUTES", "30"))


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 결과를 row["열이름"]으로 꺼낼 수 있게 한다
    conn.execute(
        """CREATE TABLE IF NOT EXISTS conversations (
               user_key   TEXT PRIMARY KEY,
               messages   TEXT NOT NULL,
               updated_at TEXT NOT NULL)"""
    )
    # 지금 처리 중인 케이스 ID(TC ID): 액션 API 헤더에 넣고, 바뀌면 새 대화로 시작한다
    conn.execute(
        """CREATE TABLE IF NOT EXISTS cases (
               user_key   TEXT PRIMARY KEY,
               case_id    TEXT NOT NULL,
               updated_at TEXT NOT NULL)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS records (
               id         INTEGER PRIMARY KEY AUTOINCREMENT,
               user_key   TEXT NOT NULL,
               kind       TEXT NOT NULL,
               content    TEXT NOT NULL,
               created_at TEXT NOT NULL)"""
    )
    return conn


def now():
    return datetime.now().isoformat(timespec="seconds")


# ── 대화 기억 ─────────────────────────────────────────

def load_history(user_key):
    conn = connect()
    row = conn.execute(
        "SELECT messages, updated_at FROM conversations WHERE user_key = ?", (user_key,)
    ).fetchone()
    conn.close()
    if not row:
        return []
    idle = datetime.now() - datetime.fromisoformat(row["updated_at"])
    if idle > timedelta(minutes=SESSION_MINUTES):
        return []
    return json.loads(row["messages"])


def save_history(user_key, messages):
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO conversations (user_key, messages, updated_at) VALUES (?, ?, ?)",
        (user_key, json.dumps(trim_history(messages), ensure_ascii=False), now()),
    )
    conn.commit()
    conn.close()


def clear_history(user_key):
    conn = connect()
    conn.execute("DELETE FROM conversations WHERE user_key = ?", (user_key,))
    conn.execute("DELETE FROM cases WHERE user_key = ?", (user_key,))
    conn.commit()
    conn.close()


def trim_history(messages):
    # 질문(user) 메시지 위치를 찾아 최근 MAX_TURNS개 질문부터 남긴다
    # 질문 단위로 잘라야 '도구 호출'과 '도구 결과'가 짝이 안 맞게 잘리는 일이 없다
    user_positions = [i for i, m in enumerate(messages) if m["role"] == "user"]
    if len(user_positions) <= MAX_TURNS:
        return messages
    return messages[user_positions[-MAX_TURNS]:]


# ── 케이스 ID ─────────────────────────────────────────

def get_case(user_key):
    conn = connect()
    row = conn.execute("SELECT case_id FROM cases WHERE user_key = ?", (user_key,)).fetchone()
    conn.close()
    return row["case_id"] if row else ""


def set_case(user_key, case_id):
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO cases (user_key, case_id, updated_at) VALUES (?, ?, ?)",
        (user_key, case_id, now()),
    )
    conn.commit()
    conn.close()


# ── 기록 (주문서 등) ──────────────────────────────────

def add_record(user_key, kind, content):
    conn = connect()
    cursor = conn.execute(
        "INSERT INTO records (user_key, kind, content, created_at) VALUES (?, ?, ?, ?)",
        (user_key, kind, json.dumps(content, ensure_ascii=False), now()),
    )
    conn.commit()
    record_id = cursor.lastrowid
    conn.close()
    return record_id


def list_records(user_key, kind=""):
    conn = connect()
    if kind:
        rows = conn.execute(
            "SELECT * FROM records WHERE user_key = ? AND kind = ? ORDER BY id", (user_key, kind)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM records WHERE user_key = ? ORDER BY id", (user_key,)).fetchall()
    conn.close()
    return [
        {"기록번호": r["id"], "종류": r["kind"], "내용": json.loads(r["content"]), "저장시각": r["created_at"]}
        for r in rows
    ]
