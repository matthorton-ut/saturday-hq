from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timezone
import requests
import re

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# =========================================================
# CONFIG
# =========================================================

NCAA_API = "https://ncaa-api.henrygd.me"
REQUEST_TIMEOUT = 20

session = requests.Session()
session.headers.update({
    "User-Agent": "SaturdayHQ/1.0",
    "Accept": "application/json,text/plain,*/*",
})


# =========================================================
# NCAA API
# =========================================================

def ncaa_get(path):
    url = f"{NCAA_API}{path}"

    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# HELPERS
# =========================================================

def clean_school_name(name):
    if not name:
        return "Unknown"

    return re.sub(
        r"\s*\([^)]*\)\s*$",
        "",
        str(name),
    ).strip()


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

    state = str(
        state or ""
    ).lower()

    if state in {
        "live",
        "in",
        "i",
    }:
        return "LIVE", "in"

    if state in {
        "final",
        "post",
        "f",
    }:
        return "FINAL", "post"

    return "UPCOMING", "pre"


# =========================================================
# NORMALIZE NCAA GAME
# =========================================================

def normalize_game(old_game):

    game = (
        old_game.get("game", old_game)
        if isinstance(old_game, dict)
        else {}
    )

    away = game.get(
        "away",
        {}
    ) or {}

    home = game.get(
        "home",
        {}
    ) or {}

    away_names = away.get(
        "names",
        {}
    ) or {}

    home_names = home.get(
        "names",
        {}
    ) or {}

    away_name = (
        away_names.get("full")
        or away_names.get("short")
        or away_names.get("seo")
        or "Unknown"
    )

    home_name = (
        home_names.get("full")
        or home_names.get("short")
        or home_names.get("seo")
        or "Unknown"
    )

    away_name = clean_school_name(
        away_name
    )

    home_name = clean_school_name(
        home_name
    )

    # NCAA uses finalMessage for completed
    # games and various fields for live games.

    final_message = (
        game.get("finalMessage")
        or ""
    )

    game_state = (
        game.get("gameState")
        or ""
    )

    if not game_state:

        if final_message:
            game_state = "final"

        else:
            game_state = "pre"

    display_status, state = (
        game_state_to_display(
            game_state
        )
    )

    # Some NCAA API responses use
    # liveGameState instead.

    if game.get("liveGameState"):

        display_status, state = (
            game_state_to_display(
                game.get(
                    "liveGameState"
                )
            )
        )

    current_period = (
        game.get("currentPeriod")
        or ""
    )

    clock = (
        game.get("contestClock")
        or ""
    )

    detail_parts = []

    if current_period:
        detail_parts.append(
            str(current_period)
        )

    if clock:
        detail_parts.append(
            str(clock)
        )

    if state == "in":

        detail = (
            " • ".join(
                detail_parts
            )
            or "LIVE"
        )

    elif final_message:

        detail = str(
            final_message
        )

    else:

        detail = (
            game.get("startTime")
            or game.get("startDate")
            or "Scheduled"
        )

    game_id = (
        game.get("gameID")
        or game.get("id")
        or ""
    )

    date_value = (
        game.get("date")
        or game.get("startDate")
        or game.get("startTime")
        or ""
    )

    return {
        "id": str(game_id),

        "home": home_name,

        "away": away_name,

        "home_id": (
            home.get("id")
            or home.get("teamID")
            or home.get("teamId")
            or ""
        ),

        "away_id": (
            away.get("id")
            or away.get("teamID")
            or away.get("teamId")
            or ""
        ),

        "home_score": safe_score(
            home.get("score")
        ),

        "away_score": safe_score(
            away.get("score")
        ),

        "state": state,

        "status": display_status,

        "detail": detail,

        "date": str(
            date_value
        ),

        "date_display": str(
            date_value
        ),

        "url": game.get(
            "url",
            ""
        ),

        "title": game.get(
            "title",
            f"{away_name} {home_name}",
        ),
    }


# =========================================================
# NCAA SCOREBOARD
# =========================================================

def get_scoreboard_for_week(week):

    year = datetime.now().year

    return ncaa_get(
        f"/scoreboard/football/fbs/"
        f"{year}/{int(week)}/all-conf"
    )


# =========================================================
# ALL TEAMS
# =========================================================

def get_all_teams():

    data = ncaa_get(
        "/schools-index"
    )

    teams = []

    if isinstance(
        data,
        list,
    ):

        schools = data

    elif isinstance(
        data,
        dict,
    ):

        schools = data.get(
            "schools",
            []
        )

    else:

        schools = []

    for school in schools:

        slug = (
            school.get("slug")
            or school.get("id")
        )

        name = (
            school.get("long")
            or school.get("name")
            or ""
        )

        short_name = (
            school.get("name")
            or name
        )

        if not slug or not name:
            continue

        teams.append({
            "id": str(slug),

            "name": str(name),

            "short_name": str(
                short_name
            ),

            "abbreviation": "",

            "logo": (
                f"{NCAA_API}/logo/"
                f"{slug}.svg?dark=true"
            ),
        })

    return teams


@app.get("/api/teams")
def api_teams():

    try:

        return {
            "teams": get_all_teams()
        }

    except Exception as exc:

        return JSONResponse(
            status_code=502,
            content={
                "error": str(exc),
                "teams": [],
            },
        )


# =========================================================
# TEAM SEARCH
# =========================================================

@app.get(
    "/api/team-search/{query}"
)
def api_team_search(
    query: str
):

    try:

        q = query.strip().lower()

        if not q:

            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": (
                        "Search query is required."
                    ),
                },
            )

        teams = get_all_teams()

        exact = []
        partial = []

        for team in teams:

            fields = [
                str(
                    team.get(
                        "name",
                        ""
                    )
                ).lower(),

                str(
                    team.get(
                        "short_name",
                        ""
                    )
                ).lower(),

                str(
                    team.get(
                        "abbreviation",
                        ""
                    )
                ).lower(),

                str(
                    team.get(
                        "id",
                        ""
                    )
                ).lower(),
            ]

            if q in fields:
                exact.append(team)

            elif any(
                q in field
                for field in fields
            ):
                partial.append(team)

        matches = (
            exact
            if exact
            else partial
        )

        if not matches:

            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": "Team not found.",
                },
            )

        return {
            "success": True,

            "team_id": matches[0]["id"],

            "team": matches[0],

            "matches": matches[:20],
        }

    except Exception as exc:

        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "error": str(exc),
            },
        )


# =========================================================
# TEAM SCHEDULE
# =========================================================

_team_schedule_cache = {}


def team_matches_game(
    selected,
    game,
):

    target_names = {
        str(
            selected.get(
                "name",
                ""
            )
        ).lower(),

        str(
            selected.get(
                "short_name",
                ""
            )
        ).lower(),

        str(
            selected.get(
                "id",
                ""
            )
        ).lower(),
    }

    home = str(
        game.get(
            "home",
            ""
        )
    ).lower()

    away = str(
        game.get(
            "away",
            ""
        )
    ).lower()

    for target in target_names:

        if not target:
            continue

        if (
            target == home
            or target in home
        ):
            return "home"

        if (
            target == away
            or target in away
        ):
            return "away"

    # Special handling for Tennessee.
    # The NCAA endpoint commonly returns
    # "Tennessee" rather than the full school name.

    if str(
        selected.get("id", "")
    ).lower() == "tennessee":

        if (
            "tennessee"
            in home
        ):
            return "home"

        if (
            "tennessee"
            in away
        ):
            return "away"

    return None


def get_team_schedule(
    team_id
):

    cache_key = str(
        team_id
    ).lower()

    now = datetime.now().timestamp()

    cached = _team_schedule_cache.get(
        cache_key
    )

    if (
        cached
        and now - cached["timestamp"]
        < 300
    ):

        return cached["data"]

    teams = get_all_teams()

    selected = next(
        (
            team
            for team in teams
            if str(
                team.get("id", "")
            ).lower()
            == cache_key
        ),
        None,
    )

    if not selected:

        raise ValueError(
            f"Team not found: {team_id}"
        )

    games = []

    # NCAA has weekly FBS scoreboards.
    # Check the entire season.

    for week in range(
        1,
        19
    ):

        try:

            data = (
                get_scoreboard_for_week(
                    week
                )
            )

        except Exception:

            continue

        for raw_game in data.get(
            "games",
            []
        ):

            try:

                game = normalize_game(
                    raw_game
                )

            except Exception:

                continue

            if not game.get(
                "id"
            ):

                continue

            side = team_matches_game(
                selected,
                game
            )

            if side is None:
                continue

            if side == "home":

                opponent = game.get(
                    "away",
                    "Unknown"
                )

                opponent_id = game.get(
                    "away_id"
                )

                team_score = game.get(
                    "home_score",
                    ""
                )

                opponent_score = game.get(
                    "away_score",
                    ""
                )

                location = "vs."

            else:

                opponent = game.get(
                    "home",
                    "Unknown"
                )

                opponent_id = game.get(
                    "home_id"
                )

                team_score = game.get(
                    "away_score",
                    ""
                )

                opponent_score = game.get(
                    "home_score",
                    ""
                )

                location = "@"

            result = ""

            if game.get(
                "state"
            ) == "post":

                try:

                    team_points = int(
                        float(
                            team_score
                        )
                    )

                    opponent_points = int(
                        float(
                            opponent_score
                        )
                    )

                    if (
                        team_points
                        > opponent_points
                    ):
                        result = "W"

                    elif (
                        team_points
                        < opponent_points
                    ):
                        result = "L"

                    else:
                        result = "T"

                except Exception:

                    result = ""

            games.append({

                "id": game.get(
                    "id"
                ),

                "date": (
                    game.get(
                        "date_display"
                    )
                    or game.get(
                        "date"
                    )
                    or ""
                ),

                "date_raw": game.get(
                    "date"
                ),

                "status": game.get(
                    "status",
                    "UPCOMING"
                ),

                "state": game.get(
                    "state",
                    "pre"
                ),

                "opponent": opponent,

                "opponent_id": (
                    opponent_id
                ),

                "logo": (
                    f"{NCAA_API}/logo/"
                    f"{opponent_id}.svg?dark=true"
                    if opponent_id
                    else ""
                ),

                "location": location,

                "detail": game.get(
                    "detail",
                    ""
                ),

                "team_score": (
                    team_score
                ),

                "opponent_score": (
                    opponent_score
                ),

                "result": result,

                "url": game.get(
                    "url",
                    ""
                ),

                "title": game.get(
                    "title",
                    ""
                ),

                "home": game.get(
                    "home",
                    ""
                ),

                "away": game.get(
                    "away",
                    ""
                ),

                "home_id": game.get(
                    "home_id"
                ),

                "away_id": game.get(
                    "away_id"
                ),
            })

    # =====================================================
    # REMOVE DUPLICATES
    # =====================================================

    unique = {}

    for game in games:

        unique[
            str(
                game.get(
                    "id"
                )
            )
        ] = game

    games = list(
        unique.values()
    )

    # =====================================================
    # SORT
    # =====================================================

    games.sort(
        key=lambda item:
            str(
                item.get(
                    "date_raw",
                    ""
                )
            )
    )

    result = {
        "team": {
            "id": selected.get(
                "id"
            ),

            "name": selected.get(
                "name"
            ),

            "short_name": selected.get(
                "short_name"
            ),

            "logo": selected.get(
                "logo"
            ),
        },

        "games": games,

        # Alias for frontend compatibility.
        "schedule": games,

        "season": datetime.now().year,
    }

    _team_schedule_cache[
        cache_key
    ] = {
        "timestamp": now,
        "data": result,
    }

    return result


@app.get(
    "/api/team/{team_id}/schedule"
)
def api_team_schedule(
    team_id: str
):

    try:

        return get_team_schedule(
            team_id
        )

    except Exception as exc:

        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "error": str(exc),
                "games": [],
                "schedule": [],
            },
        )


# =========================================================
# SCHEDULE PAGE
# =========================================================

@app.get(
    "/schedule/{team_id}",
    response_class=HTMLResponse,
)
def schedule_page(
    request: Request,
    team_id: str
):

    return templates.TemplateResponse(
        request=request,
        name="schedule.html",
        context={
            "team_id": team_id,
        },
    )


# =========================================================
# LIVE / GAME CENTER
# =========================================================

def get_game_detail(
    game_id
):

    # NCAA game endpoint.
    # This gives us the individual game
    # information needed for the Game Center.

    paths = [
        f"/game/{game_id}",
        f"/game/{game_id}/boxscore",
    ]

    last_error = None

    for path in paths:

        try:

            return ncaa_get(
                path
            )

        except Exception as exc:

            last_error = exc

    raise last_error or Exception(
        "Unable to load game."
    )


@app.get(
    "/api/game/{game_id}"
)
def api_game(
    game_id: str
):

    try:

        return get_game_detail(
            game_id
        )

    except Exception as exc:

        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "error": str(exc),
            },
        )


# =========================================================
# RANKINGS
# =========================================================

def get_rankings():

    try:

        data = ncaa_get(
            "/rankings"
        )

        if isinstance(
            data,
            dict
        ):

            rankings = (
                data.get(
                    "rankings"
                )
                or data.get(
                    "polls"
                )
                or []
            )

        else:

            rankings = data

        if not isinstance(
            rankings,
            list
        ):

            return []

        result = []

        for poll in rankings:

            if not isinstance(
                poll,
                dict
            ):
                continue

            ranks = (
                poll.get(
                    "ranks"
                )
                or poll.get(
                    "teams"
                )
                or []
            )

            if not isinstance(
                ranks,
                list
            ):
                continue

            for item in ranks:

                if not isinstance(
                    item,
                    dict
                ):
                    continue

                team = (
                    item.get(
                        "team"
                    )
                    or {}
                )

                rank = (
                    item.get(
                        "rank"
                    )
                    or item.get(
                        "current"
                    )
                    or item.get(
                        "position"
                    )
                )

                if rank is None:
                    continue

                name = (
                    team.get(
                        "name"
                    )
                    or team.get(
                        "displayName"
                    )
                    or item.get(
                        "name"
                    )
                    or "Unknown"
                )

                result.append({
                    "rank": rank,

                    "name": name,

                    "id": (
                        team.get(
                            "id"
                        )
                    ),

                    "logo": (
                        f"{NCAA_API}/logo/"
                        f"{team.get('id')}.svg?dark=true"
                        if team.get(
                            "id"
                        )
                        else ""
                    ),
                })

            if result:
                break

        return result[:25]

    except Exception:

        return []


@app.get(
    "/api/rankings"
)
def api_rankings():

    try:

        return {
            "rankings":
                get_rankings()
        }

    except Exception as exc:

        return JSONResponse(
            status_code=502,
            content={
                "error": str(exc)
            },
        )


# =========================================================
# HOME
# =========================================================

@app.get(
    "/",
    response_class=HTMLResponse,
)
def home(
    request: Request
):

    try:

        today = datetime.now().strftime(
            "%Y/%m/%d"
        )

        data = ncaa_get(
            f"/scoreboard/football/fbs/"
            f"{datetime.now().year}/"
            f"{datetime.now().isocalendar().week}/"
            f"all-conf"
        )

        games = []

        for raw_game in data.get(
            "games",
            []
        ):

            try:

                games.append(
                    normalize_game(
                        raw_game
                    )
                )

            except Exception:

                continue

    except Exception as exc:

        games = []

    live_games = sum(
        1
        for game in games
        if game.get(
            "state"
        ) == "in"
    )

    final_games = sum(
        1
        for game in games
        if game.get(
            "state"
        ) == "post"
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "games": games,

            "live_games":
                live_games,

            "final_games":
                final_games,

            "local_date":
                datetime.now().strftime(
                    "%Y-%m-%d"
                ),
        },
    )