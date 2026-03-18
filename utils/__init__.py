# utils 패키지 — 하위 모듈 re-export
# bot.py / commands.py 의 "from utils import ..." 는 전부 여기서 해결됨

from utils.storage import (
    ensure_json_files,
    load_json, save_json,
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
    find_next_event, find_next_n_events, find_recent_spurs_match, find_lineup_window_match,
    find_live_match,
    f1_session_label, f1_session_short, f1_gp_name, find_next_gp_sessions,
    _shorten_team, extract_opponent,
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

from utils.market import (
    add_market_subscriber,
    remove_market_subscriber,
    get_market_subscribers,
    get_market_subscribers_for_time,
    get_market_subscriber_mode,
    is_market_subscriber,
    load_market_notified,
    save_market_notified,
    cleanup_market_notified,
    get_nasdaq_open_kst,
    get_nasdaq_close_kst,
    fetch_market_data,
    format_market_message,
)

from utils.ark import (
    add_ark_subscriber,
    remove_ark_subscriber,
    get_ark_subscribers,
    is_ark_subscriber,
    load_ark_notified,
    save_ark_notified,
    cleanup_ark_notified,
    fetch_ark_trades,
    format_ark_message,
)

from utils.lineup_scraper import (
    scrape_bbc_lineup,
    get_cached_lineup,
    clear_old_lineup_cache,
    format_bbc_lineup_message,
)

from utils.injury_scraper import (
    scrape_injuries,
    format_injury_message,
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
    "find_next_event", "find_next_n_events", "find_recent_spurs_match", "find_lineup_window_match",
    "find_live_match",
    "f1_session_label", "f1_session_short", "f1_gp_name", "find_next_gp_sessions",
    "_shorten_team", "extract_opponent",
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
    # market
    "add_market_subscriber", "remove_market_subscriber",
    "get_market_subscribers", "get_market_subscribers_for_time", "get_market_subscriber_mode",
    "is_market_subscriber",
    "load_market_notified", "save_market_notified", "cleanup_market_notified",
    "get_nasdaq_open_kst", "get_nasdaq_close_kst",
    "fetch_market_data", "format_market_message",
    # ark
    "add_ark_subscriber", "remove_ark_subscriber",
    "get_ark_subscribers", "is_ark_subscriber",
    "load_ark_notified", "save_ark_notified", "cleanup_ark_notified",
    "fetch_ark_trades", "format_ark_message",
    # lineup_scraper
    "scrape_bbc_lineup", "get_cached_lineup",
    "clear_old_lineup_cache", "format_bbc_lineup_message",
    # injury_scraper
    "scrape_injuries", "format_injury_message",
]
