import json
import os
import re
from datetime import datetime, timedelta, timezone

from config import (
    ARK_NOTIFIED_PATH,
    ARK_SUB_PATH,
    GUILD_SETTINGS_PATH,
    LINEUP_PATH,
    MARKET_NOTIFIED_PATH,
    MARKET_SUB_PATH,
    RESULT_PATH,
    STATE_CLEANUP_DAYS,
    STATE_PATH,
    SUB_PATH,
)

_ISO_RE = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)?')


def ensure_json_files():
    for path, default in [
        (STATE_PATH, {}),
        (SUB_PATH, {"users": {}}),
        (GUILD_SETTINGS_PATH, {}),
        (LINEUP_PATH, {}),
        (RESULT_PATH, {}),
        (MARKET_SUB_PATH, {"users": []}),
        (MARKET_NOTIFIED_PATH, {}),
        (ARK_SUB_PATH, {"users": []}),
        (ARK_NOTIFIED_PATH, {}),
    ]:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)


def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_state():         return _load_json(STATE_PATH, {})
def save_state(s):        _save_json(STATE_PATH, s)
def load_lineup_state():  return _load_json(LINEUP_PATH, {})
def save_lineup_state(s): _save_json(LINEUP_PATH, s)
def load_result_state():  return _load_json(RESULT_PATH, {})
def save_result_state(s): _save_json(RESULT_PATH, s)

def load_guild_settings():     return _load_json(GUILD_SETTINGS_PATH, {})
def save_guild_settings(data): _save_json(GUILD_SETTINGS_PATH, data)


def set_guild_channel(guild_id: int, channel_id: int):
    data = load_guild_settings()
    data[str(guild_id)] = {"channel_id": channel_id}
    save_guild_settings(data)


def get_guild_channel_id(guild_id: int):
    return load_guild_settings().get(str(guild_id), {}).get("channel_id")


# ── 구독자 관리 ────────────────────────────────────────────
def load_subscribers() -> dict:
    data = _load_json(SUB_PATH, {"users": {}})
    if isinstance(data.get("users"), list):
        data["users"] = {str(uid): "all" for uid in data["users"]}
        _save_json(SUB_PATH, data)
    return data


def save_subscribers(data):
    _save_json(SUB_PATH, data)


def add_subscriber(user_id: int, mode: str = "all"):
    data = load_subscribers()
    data["users"][str(user_id)] = mode
    save_subscribers(data)


def remove_subscriber(user_id: int):
    data = load_subscribers()
    data["users"].pop(str(user_id), None)
    save_subscribers(data)


def get_subscribers_for_source(source: str) -> list[int]:
    users = load_subscribers().get("users", {})
    return [
        int(uid_str)
        for uid_str, mode in users.items()
        if mode == "all" or mode == source
    ]


def get_subscriber_mode(user_id: int) -> str | None:
    return load_subscribers().get("users", {}).get(str(user_id))


# ── 상태 정리 ──────────────────────────────────────────────
def make_key(source: str, uid: str, start_iso: str, kind: str) -> str:
    return f"{source}:{uid}:{start_iso}:{kind}"


def cleanup_old_state(state: dict, days: int = STATE_CLEANUP_DAYS) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = {}
    for k, v in state.items():
        m = _ISO_RE.search(k)
        if not m:
            result[k] = v
            continue
        try:
            dt = datetime.fromisoformat(m.group())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt > cutoff:
                result[k] = v
        except ValueError:
            result[k] = v
    return result
