# utils 패키지 — 하위 모듈 re-export
# bot.py / commands.py 의 "from utils import ..." 는 전부 여기서 해결됨

from utils.storage import (
    ensure_json_files,
    load_state, save_state,
    load_lineup_state, save_lineup_state,
    load_result_state, save_result_state,
    load_guild_settings, save_guild_settings,
    set_guild_channel, get_guild_channel_id,
    load_subscribers, save_subscribers,
    add_subscriber, remove_subscriber,
    get_subscribers_for_source, get_subscriber_mode,
    make_key, cleanup_old_state,
)

from utils.ics import (
    fetch_ics_bytes, fetch_ics_bytes_cached,
    parse_events,
    find_next_event, find_next_n_events, find_recent_spurs_match,
    f1_session_label, f1_session_short, f1_gp_name, find_next_gp_sessions,
    _shorten_team, _extract_opponent,
    fmt_next, fmt_dm, fmt_bbf1,
)

from utils.football_data import (
    fetch_football_data,
    find_fd_match, find_fd_match_cached,
    fetch_fd_match, fetch_fd_lineups, fetch_fd_h2h,
    fetch_spurs_recent_matches,
    fetch_opponent_standing,
    fetch_standings_mini,
)

from utils.formatters import (
    format_previous_result,
    format_recent_form,
    format_lineup_message,
    format_lineup_message_full,
    format_h2h_message,
    format_result_message,
    format_opponent_brief,
    format_standings_mini,
)

__all__ = [
    # storage
    "ensure_json_files",
    "load_state", "save_state",
    "load_lineup_state", "save_lineup_state",
    "load_result_state", "save_result_state",
    "load_guild_settings", "save_guild_settings",
    "set_guild_channel", "get_guild_channel_id",
    "load_subscribers", "save_subscribers",
    "add_subscriber", "remove_subscriber",
    "get_subscribers_for_source", "get_subscriber_mode",
    "make_key", "cleanup_old_state",
    # ics
    "fetch_ics_bytes", "fetch_ics_bytes_cached",
    "parse_events",
    "find_next_event", "find_next_n_events", "find_recent_spurs_match",
    "f1_session_label", "f1_session_short", "f1_gp_name", "find_next_gp_sessions",
    "_shorten_team", "_extract_opponent",
    "fmt_next", "fmt_dm", "fmt_bbf1",
    # football_data
    "fetch_football_data",
    "find_fd_match", "find_fd_match_cached",
    "fetch_fd_match", "fetch_fd_lineups", "fetch_fd_h2h",
    "fetch_spurs_recent_matches",
    "fetch_opponent_standing",
    "fetch_standings_mini",
    # formatters
    "format_previous_result",
    "format_recent_form",
    "format_lineup_message",
    "format_lineup_message_full",
    "format_h2h_message",
    "format_result_message",
    "format_opponent_brief",
    "format_standings_mini",
]
