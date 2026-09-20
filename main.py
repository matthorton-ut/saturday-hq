from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
from functools import lru_cache
import re
import requests

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# =========================================================
# SATURDAY HQ DATA SOURCE
# =========================================================
# ESPN's unofficial site endpoints were returning HTTP 403 from
# the Render deployment.  Saturday HQ now uses the public NCAA
# data proxy for scores/rankings/game data instead.
NCAA_API = "https://ncaa-api.henrygd.me"
REQUEST_TIMEOUT = 20

session = requests.Session()
session.headers.update({
    "User-Agent": "SaturdayHQ/1.0",
    "Accept": "application/json,text/plain,*/*",
})


def ncaa_get(path):
    """GET JSON from the NCAA API proxy with a useful error message."""
    url = f"{NCAA_API}{path}"
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


# =========================================================
# HELPERS
# =========================================================

def clean_school_name(name):
    """Remove AP first-place vote notation, e.g. 'Texas (56)'."""
    if not name:
        return "Unknown"
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(name)).strip()


def safe_score(value):
    if value is None or value == "":
        return ""
    if isinstance(value, dict):
        return str(
            value.get("displayValue")
            or value.get("value")
            or ""
        )
    return str(value)


def game_state_to_display(state):
    state = str(state or "").lower()
    if state in {"live", "in", "i"}:
        return "LIVE", "in"
    if state in {"final", "post", "f"}:
        return "FINAL", "post"
    return "UPCOMING", "pre"


def format_date(date_string):
    if not date_string:
        return ""
    try:
        value = datetime.fromisoformat(
            str(date_string).replace("Z", "+00:00")
        )
        return value.strftime("%b %d").replace(" 0", " ")
    except Exception:
        return str(date_string)


def season_week_for_date(date_value=None):
    """Approximate FBS week number from the season's first Saturday.

    NCAA's football scoreboard route is week-based.  This keeps the
    app automatic instead of requiring a daily code change.
    """
    if date_value is None:
        date_value = datetime.now()

    year = date_value.year

    # College football's regular season begins around the last Saturday
    # in August. Find that Saturday for the current calendar year.
    cursor = datetime(year, 8, 25)
    while cursor.weekday() != 5:
        cursor += timedelta(days=1)

    if date_value < cursor:
        return 1

    delta_days = (date_value.date() - cursor.date()).days
    return max(1, min(18, (delta_days // 7) + 1))


def get_scoreboard_for_week(week):
    return ncaa_get(
        f"/scoreboard/football/fbs/{datetime.now().year}/{int(week)}/all-conf"
    )


def normalize_game(old_game):
    """Convert NCAA proxy's old-format game into Saturday HQ fields."""
    game = old_game.get("game", old_game) if isinstance(old_game, dict) else {}

    away = game.get("away") or {}
    home = game.get("home") or {}

    away_names = away.get("names") or {}
    home_names = home.get("names") or {}

    away_name = (
        away_names.get("full")
        or away_names.get("short")
        or "Unknown"
    )
    home_name = (
        home_names.get("full")
        or home_names.get("short")
        or "Unknown"
    )

    display_status, state = game_state_to_display(
        game.get("gameState")
    )

    final_message = game.get("finalMessage") or ""
    current_period = game.get("currentPeriod") or ""
    clock = game.get("contestClock") or ""

    if state == "in":
        detail_parts = []
        if current_period:
            detail_parts.append(str(current_period))
        if clock:
            detail_parts.append(str(clock))
        detail = " • ".join(detail_parts) or "LIVE"
    elif state == "post":
        detail = final_message or "Final"
    else:
        start_time = game.get("startTime") or ""
        detail = start_time or "Scheduled"

    return {
        "id": str(game.get("gameID") or ""),
        "name": f"{away_name} at {home_name}",
        "short_name": f"{away_names.get('short', away_name)} at {home_names.get('short', home_name)}",
        "away": away_name,
        "home": home_name,
        "away_id": away_names.get("seo") or away_names.get("short") or "",
        "home_id": home_names.get("seo") or home_names.get("short") or "",
        "away_score": safe_score(away.get("score")),
        "home_score": safe_score(home.get("score")),
        "status": display_status,
        "detail": detail,
        "state": state,
        "date": game.get("startDate") or "",
        "date_display": format_date(game.get("startDate")),
        "start_time": game.get("startTime") or "",
        "current_period": current_period,
        "contest_clock": clock,
        "network": game.get("network") or "",
        "url": game.get("url") or "",
    }


# =========================================================
# SCOREBOARD
# =========================================================

def get_games():
    week = season_week_for_date()
    data = get_scoreboard_for_week(week)
    games = []

    for raw_game in data.get("games", []):
        try:
            games.append(normalize_game(raw_game))
        except Exception:
            continue

    # Keep games in chronological order.
    games.sort(key=lambda game: game.get("date", ""))
    return games


@app.get("/api/games")
def api_games():
    try:
        games = get_games()
        return {"games": games}
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": str(exc), "games": []},
        )


# =========================================================
# SCHOOLS / TEAMS
# =========================================================

@lru_cache(maxsize=1)
def get_all_teams():
    """Get NCAA school index and normalize it for the existing UI."""
    data = ncaa_get("/schools-index")
    teams = []

    if isinstance(data, list):
        schools = data
    elif isinstance(data, dict):
        schools = data.get("schools", [])
    else:
        schools = []

    for school in schools:
        slug = school.get("slug") or school.get("id")
        name = school.get("long") or school.get("name") or ""
        short_name = school.get("name") or name

        if not slug or not name:
            continue

        teams.append({
            "id": str(slug),
            "name": name,
            "short_name": short_name,
            "abbreviation": "",
            "logo": f"{NCAA_API}/logo/{slug}.svg?dark=true",
        })

    return teams


@app.get("/api/teams")
def api_teams():
    try:
        return {"teams": get_all_teams()}
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": str(exc), "teams": []},
        )


# =========================================================
# TEAM SEARCH
# =========================================================

@app.get("/api/team-search/{query}")
def api_team_search(query: str):
    try:
        q = query.strip().lower()
        if not q:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Search query is required."},
            )

        teams = get_all_teams()
        exact = []
        partial = []

        for team in teams:
            fields = [
                str(team.get("name", "")).lower(),
                str(team.get("short_name", "")).lower(),
                str(team.get("abbreviation", "")).lower(),
                str(team.get("id", "")).lower(),
            ]

            if q in fields:
                exact.append(team)
            elif any(q in field for field in fields):
                partial.append(team)

        matches = exact or partial

        if not matches:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Team not found."},
            )

        return {
            "success": True,
            "team_id": matches[0]["id"],
            "team": matches[0],
            "matches": matches[:10],
        }

    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"success": False, "error": str(exc)},
        )


# =========================================================
# TEAM SCHEDULE
# =========================================================

_team_schedule_cache = {}


def get_team_schedule(team_id):
    """Build a team's season schedule from NCAA weekly scoreboards.

    The cache prevents opening a team page from making the same 18
    upstream requests repeatedly.
    """
    cache_key = str(team_id).lower()
    cached = _team_schedule_cache.get(cache_key)
    now = datetime.now().timestamp()

    if cached and now - cached["timestamp"] < 900:
        return cached["data"]

    teams = get_all_teams()
    selected = next(
        (team for team in teams if str(team["id"]).lower() == cache_key),
        None,
    )

    if not selected:
        raise ValueError("Team not found.")

    target_names = {
        selected["name"].lower(),
        selected["short_name"].lower(),
        selected["id"].lower(),
    }

    games = []

    # FBS regular-season weeks plus postseason weeks.
    for week in range(1, 19):
        try:
            data = get_scoreboard_for_week(week)
        except Exception:
            continue

        for raw_game in data.get("games", []):
            game = normalize_game(raw_game)

            home = game["home"].lower()
            away = game["away"].lower()
            home_short = home.split(" ")
            away_short = away.split(" ")

            matches_home = (
                home in target_names
                or selected["name"].lower() in home
                or selected["short_name"].lower() in home
                or selected["name"].lower() in " ".join(home_short)
            )
            matches_away = (
                away in target_names
                or selected["name"].lower() in away
                or selected["short_name"].lower() in away
                or selected["name"].lower() in " ".join(away_short)
            )

            if not (matches_home or matches_away):
                continue

            is_home = matches_home
            opponent = game["away"] if is_home else game["home"]
            opponent_id = game["away_id"] if is_home else game["home_id"]

            result = ""
            if game["state"] == "post":
                try:
                    team_score = int(float(
                        game["home_score"] if is_home else game["away_score"]
                    ))
                    opponent_score = int(float(
                        game["away_score"] if is_home else game["home_score"]
                    ))
                    if team_score > opponent_score:
                        result = "W"
                    elif team_score < opponent_score:
                        result = "L"
                    else:
                        result = "T"
                except Exception:
                    pass

            games.append({
                "id": game["id"],
                "date": game["date_display"] or game["date"],
                "date_raw": game["date"],
                "status": game["status"],
                "state": game["state"],
                "opponent": opponent,
                "opponent_id": opponent_id,
                "logo": (
                    f"{NCAA_API}/logo/{opponent_id}.svg?dark=true"
                    if opponent_id else ""
                ),
                "location": "vs." if is_home else "@",
                "detail": game["detail"],
                "team_score": (
                    game["home_score"] if is_home else game["away_score"]
                ),
                "opponent_score": (
                    game["away_score"] if is_home else game["home_score"]
                ),
                "result": result,
            })

    # Remove duplicates and sort by date.
    unique = {}
    for game in games:
        unique[game["id"]] = game

    games = list(unique.values())
    games.sort(key=lambda item: item.get("date_raw", ""))

    result = {
        "team": {
            "id": selected["id"],
            "name": selected["name"],
            "logo": selected["logo"],
        },
        "games": games,
    }

    _team_schedule_cache[cache_key] = {
        "timestamp": now,
        "data": result,
    }

    return result


@app.get("/api/team/{team_id}/schedule")
def api_team_schedule(team_id: str):
    try:
        return get_team_schedule(team_id)
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": str(exc)},
        )


@app.get("/schedule/{team_id}", response_class=HTMLResponse)
def schedule_page(request: Request, team_id: str):
    return templates.TemplateResponse(
        request=request,
        name="schedule.html",
        context={"team_id": team_id},
    )


# =========================================================
# GAME CENTER / PLAY-BY-PLAY
# =========================================================

def get_game_data(event_id):
    return ncaa_get(f"/game/{event_id}")


def get_game_play_by_play(event_id):
    try:
        return ncaa_get(f"/game/{event_id}/play-by-play")
    except Exception:
        return {}


@app.get("/api/game/{event_id}")
def api_game(event_id: str):
    """Return game-center data plus NCAA play-by-play when available."""
    try:
        game = get_game_data(event_id)
        pbp = get_game_play_by_play(event_id)

        return {
            "event_id": str(event_id),
            "game": game,
            "play_by_play": pbp,
        }
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": str(exc), "event_id": str(event_id)},
        )


# =========================================================
# RANKINGS
# =========================================================

@lru_cache(maxsize=1)
def get_rankings():
    data = ncaa_get("/rankings/football/fbs/associated-press")
    ranking_list = []

    for item in data.get("data", []):
        try:
            rank = int(str(item.get("RANK", "")).strip())
        except Exception:
            continue

        name = clean_school_name(item.get("SCHOOL", "Unknown"))
        ranking_list.append({
            "rank": rank,
            "name": name,
            "id": None,
            "logo": "",
            "record": item.get("RECORD", ""),
            "points": item.get("POINTS", ""),
            "previous": item.get("PREVIOUS RANKING", ""),
        })

    return ranking_list[:25]


@app.get("/api/rankings")
def api_rankings():
    try:
        return {"rankings": get_rankings()}
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": str(exc), "rankings": []},
        )


# =========================================================
# HOME
# =========================================================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    try:
        games = get_games()
        error = None
    except Exception as exc:
        games = []
        error = str(exc)

    live_games = sum(
        1 for game in games if game.get("state") == "in"
    )

    final_games = sum(
        1 for game in games if game.get("state") == "post"
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "games": games,
            "live_games": live_games,
            "final_games": final_games,
            "error": error,
        },
    )
