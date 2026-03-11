from datetime import datetime, timezone

from config import FOOTBALL_DATA_TEAM_ID, KST


def _kickoff_str(match: dict) -> str:
    utc_date = match.get("utcDate", "")
    if not utc_date:
        return "?"
    try:
        dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        return dt.astimezone(KST).strftime("%Y-%m-%d (%a) %H:%M")
    except Exception:
        return "?"


def _player_line(p: dict) -> str:
    shirt = p.get("shirtNumber")
    name = p.get("player", {}).get("name", "?")
    return f"`{shirt:>2}` {name}" if shirt else name


def format_previous_result(match: dict) -> str:
    """단일 경기 결과 요약 (bbtt 이전 경기용)."""
    home_name = match.get("homeTeam", {}).get("name", "?")
    away_name = match.get("awayTeam", {}).get("name", "?")
    score = match.get("score", {}).get("fullTime", {})
    h = score.get("home") or 0
    a = score.get("away") or 0
    tournament = match.get("competition", {}).get("name", "?")
    date_str = (match.get("utcDate") or "")[:10]

    is_home = match.get("homeTeam", {}).get("id") == FOOTBALL_DATA_TEAM_ID
    spurs_g = h if is_home else a
    opp_g = a if is_home else h
    icon = "✅" if spurs_g > opp_g else ("🟡" if spurs_g == opp_g else "❌")

    return (
        f"📋 **이전 경기 결과**\n"
        f"**{home_name} {h} - {a} {away_name}**\n"
        f"{tournament} | {date_str} | 결과: {icon}"
    )


def format_recent_form(matches: list[dict]) -> str:
    """최근 N경기 폼 — 승무패 카운트 + 이모지 (오래된 순 → 최근 순)."""
    if not matches:
        return ""

    wins = draws = losses = 0
    emojis = []
    for m in matches:
        score = (m.get("score") or {}).get("fullTime") or {}
        h = score.get("home")
        a = score.get("away")
        if h is None or a is None:
            continue
        is_home = (m.get("homeTeam") or {}).get("id") == FOOTBALL_DATA_TEAM_ID
        spurs_g = h if is_home else a
        opp_g = a if is_home else h
        if spurs_g > opp_g:
            wins += 1
            emojis.append("✅")
        elif spurs_g == opp_g:
            draws += 1
            emojis.append("🟡")
        else:
            losses += 1
            emojis.append("❌")

    emoji_str = " ".join(reversed(emojis))  # 오래된 순 → 최근 순
    return f"**최근 {len(emojis)}경기 폼** {wins}승 {draws}무 {losses}패\n{emoji_str}"


def format_lineup_message(match: dict, lineup_data: dict, is_home: bool) -> str:
    """단축 라인업 — 토트넘 선발+교체만, 등번호+포메이션 포함. (DM 알림, /bbtt용)"""
    side = "homeTeam" if is_home else "awayTeam"
    home_name = match.get("homeTeam", {}).get("name", "?")
    away_name = match.get("awayTeam", {}).get("name", "?")

    team_lineup = lineup_data.get(side, {})
    formation = team_lineup.get("formation", "")
    starters = team_lineup.get("startingXI", [])
    subs = team_lineup.get("substitutes", [])

    formation_str = f" [{formation}]" if formation else ""
    lines = [
        f"⚽ **토트넘 라인업{formation_str}**", "",
        f"**{home_name} vs {away_name}**",
        f"Kickoff: {_kickoff_str(match)} KST", "",
        "**Starting XI**",
    ]
    for p in starters:
        lines.append(_player_line(p))
    lines += ["", "**Substitutes**"]
    for p in subs:
        lines.append(_player_line(p))

    return "\n".join(lines)


def format_lineup_message_full(match: dict, lineup_data: dict) -> str:
    """풀 라인업 — 홈/어웨이 양 팀 모두, 등번호+포메이션 포함. (/bblineup용)"""
    home_name = match.get("homeTeam", {}).get("name", "?")
    away_name = match.get("awayTeam", {}).get("name", "?")

    lines = [
        "⚽ **오피셜 라인업**", "",
        f"**{home_name} vs {away_name}**",
        f"Kickoff: {_kickoff_str(match)} KST",
    ]

    for side_key, team_name in [("homeTeam", home_name), ("awayTeam", away_name)]:
        team_lineup = lineup_data.get(side_key, {})
        formation = team_lineup.get("formation", "")
        starters = team_lineup.get("startingXI", [])
        subs = team_lineup.get("substitutes", [])

        formation_str = f" [{formation}]" if formation else ""
        lines += ["", f"**{team_name}{formation_str}**", "Starting XI:"]
        for p in starters:
            lines.append(_player_line(p))
        lines.append("Substitutes:")
        for p in subs:
            lines.append(_player_line(p))

    return "\n".join(lines)


def format_h2h_message(h2h_data: dict) -> str:
    """최근 상대 전적 포맷 (최대 5경기, 최신순)."""
    matches = h2h_data.get("matches", [])
    if not matches:
        return ""

    recent = sorted(matches, key=lambda m: m.get("utcDate", ""), reverse=True)[:5]

    lines = ["", "**📊 최근 상대 전적**"]
    for m in recent:
        home_name = (m.get("homeTeam") or {}).get("shortName") or (m.get("homeTeam") or {}).get("name", "?")
        away_name = (m.get("awayTeam") or {}).get("shortName") or (m.get("awayTeam") or {}).get("name", "?")
        score = (m.get("score") or {}).get("fullTime") or {}
        h = score.get("home")
        a = score.get("away")
        date_str = (m.get("utcDate") or "")[:10]

        is_spurs_home = (m.get("homeTeam") or {}).get("id") == FOOTBALL_DATA_TEAM_ID
        if h is not None and a is not None:
            spurs_g = h if is_spurs_home else a
            opp_g = a if is_spurs_home else h
            icon = "✅" if spurs_g > opp_g else ("🟡" if spurs_g == opp_g else "❌")
            lines.append(f"{icon} `{date_str}` {home_name} {h}-{a} {away_name}")
        else:
            lines.append(f"❓ `{date_str}` {home_name} vs {away_name}")

    return "\n".join(lines)


def format_opponent_brief(standing_row: dict) -> str:
    """상대팀 리그 현황 한 줄 요약."""
    team_name = (
        standing_row.get("team", {}).get("shortName")
        or standing_row.get("team", {}).get("name", "?")
    )
    pos = standing_row.get("position", "?")
    pts = standing_row.get("points", "?")
    played = standing_row.get("playedGames", "?")
    gd = standing_row.get("goalDifference", 0)
    gd_str = f"+{gd}" if isinstance(gd, int) and gd > 0 else str(gd)
    return f"🔍 **상대 현황** | {team_name} | {pos}위 | 승점 {pts} | {played}경기 | 골득실 {gd_str}"


def format_standings_mini(table: list, spurs_pos: int) -> str:
    """토트넘 기준 ±n 구간 미니 순위표 (코드블록)."""
    if not table:
        return ""
    lines = ["", "🏆 **프리미어리그 순위**", "```"]
    for row in table:
        pos = row.get("position", "?")
        name = (
            row.get("team", {}).get("shortName")
            or row.get("team", {}).get("name", "?")
        )
        played = row.get("playedGames", "-")
        pts = row.get("points", "-")
        gd = row.get("goalDifference", 0)
        gd_str = f"+{gd}" if isinstance(gd, int) and gd > 0 else str(gd)
        marker = "◀" if pos == spurs_pos else "  "
        lines.append(f"{pos:>2}{marker} {name:<18} {played:>2}경기  {pts:>3}pt  {gd_str:>4}")
    lines.append("```")
    return "\n".join(lines)


def format_result_message(
    match: dict,
    is_home: bool,
    standings_data: tuple[list, int | None],
    next_fixtures: list,
) -> str:
    home_name = match.get("homeTeam", {}).get("name", "?")
    away_name = match.get("awayTeam", {}).get("name", "?")
    score = match.get("score", {}).get("fullTime", {})
    home_score = score.get("home") or 0
    away_score = score.get("away") or 0
    tournament = match.get("competition", {}).get("name", "?")

    spurs_score = home_score if is_home else away_score
    opp_score = away_score if is_home else home_score

    if spurs_score > opp_score:
        result_str = "승 ✅"
    elif spurs_score == opp_score:
        result_str = "무 🟡"
    else:
        result_str = "패 ❌"

    lines = [
        "📊 **경기 종료**", "",
        f"**{home_name} {home_score} - {away_score} {away_name}**",
        f"{tournament}", "",
        f"결과: {result_str}",
    ]

    goals = match.get("goals") or []
    if goals:
        spurs_goals, opp_goals = [], []
        for g in goals:
            scorer = (g.get("scorer") or {}).get("name", "?")
            minute = g.get("minute", "?")
            team_id = (g.get("team") or {}).get("id")
            entry = f"{scorer} {minute}'"
            if team_id == FOOTBALL_DATA_TEAM_ID:
                spurs_goals.append(entry)
            else:
                opp_goals.append(entry)

        if spurs_goals or opp_goals:
            lines += ["", "**⚽ 득점**"]
            if spurs_goals:
                lines.append(f"토트넘: {' · '.join(spurs_goals)}")
            if opp_goals:
                opp_name = away_name if is_home else home_name
                lines.append(f"{opp_name}: {' · '.join(opp_goals)}")

    mini_table, spurs_pos = standings_data if standings_data else ([], None)
    standings_str = format_standings_mini(mini_table, spurs_pos) if mini_table else ""
    if standings_str:
        lines.append(standings_str)
    elif spurs_pos is not None:
        lines.append(f"현재 순위: **{spurs_pos}위**")

    if next_fixtures:
        lines += ["", "📅 **다음 일정**"]
        for i, fx in enumerate(next_fixtures, 1):
            t = fx["start_kst"].strftime("%m/%d (%a) %H:%M")
            lines.append(f"{i}. {fx['summary']} | {t} KST")

    return "\n".join(lines)
