"""봉봉뉴스 구독자 관리."""

from config import KST, BONGNEWS_SUB_PATH
from utils.storage import load_json as _load_json, save_json as _save_json


def _load() -> dict:
    return _load_json(BONGNEWS_SUB_PATH, {"users": []})


def _save(data: dict):
    _save_json(BONGNEWS_SUB_PATH, data)


def add_bongnews_subscriber(user_id: int):
    data = _load()
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"].append(uid)
        _save(data)


def remove_bongnews_subscriber(user_id: int):
    data = _load()
    uid = str(user_id)
    if uid in data["users"]:
        data["users"].remove(uid)
        _save(data)


def get_bongnews_subscribers() -> list[int]:
    return [int(u) for u in _load().get("users", [])]


def is_bongnews_subscriber(user_id: int) -> bool:
    return str(user_id) in _load().get("users", [])
