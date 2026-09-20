from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import requests
from datetime import datetime

app = FastAPI()

templates = Jinja2Templates(directory="templates")

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"

SCOREBOARD_URL = f"{BASE_URL}/scoreboard"
TEAMS_URL = f"{BASE_URL}/teams"


def espn_get(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=15,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------
# SCOREBOARD
# ---------------------------------------------------------

def get_games():
    today = datetime.now().strftime("%Y%m%d")

    data = espn_get(
        SCOREBOARD_URL,
        {
            "dates": today,
            "limit": 500
        }
    )

    games = []

    for event in data.get("events", []):
        try:
            competition = event["competitions"][0]
            competitors = competition["competitors"]

            home = next(
                team for team in competitors
                if team["homeAway"] == "home"
            )

            away = next(
                team for team in competitors
                if team["homeAway"] == "away"
            )

            status = competition.get("status", {})
            status_type = status.get("type", {})

            games.append({
                "id": event.get("id"),
                "name": event.get("name", ""),
                "short_name": event.get("shortName", ""),

                "away": away["team"].get("displayName", "Unknown"),
                "home": home["team"].get("displayName", "Unknown"),

                "away_id": away["team"].get("id"),
                "home_id": home["team"].get("id"),

                "away_score": away.get("score", "0"),
                "home_score": home.get("score", "0"),

                "status": status_type.get(
                    "description",
                    "Scheduled"
                ),

                "detail": status_type.get(
                    "shortDetail",
                    ""
                ),

                "state": status_type.get(
                    "state",
                    "pre"
                ),

                "date": event.get("date", "")
            })

        except Exception:
            continue

    return games


# ---------------------------------------------------------
# TEAMS
# ---------------------------------------------------------

def get_all_teams():
    data = espn_get(
        TEAMS_URL,
        {
            "limit": 1000
        }
    )

    teams = []

    # ESPN normally puts teams under sports -> leagues -> teams
    for sport in data.get("sports", []):
        for league in sport.get("leagues", []):
            for team in league.get("teams", []):
                team_data = team.get("team", team)

                if team_data.get("id"):
                    teams.append({
                        "id": team_data["id"],
                        "name": team_data.get(
                            "displayName",
                            team_data.get("name", "")
                        ),
                        "short_name": team_data.get(
                            "shortDisplayName",
                            team_data.get("shortName", "")
                        ),
                        "abbreviation": team_data.get(
                            "abbreviation",
                            ""
                        ),
                        "logo": team_data.get("logos", [{}])[0].get(
                            "href", ""
                        ) if team_data.get("logos") else ""
                    })

    # Remove duplicates
    unique = {}

    for team in teams:
        unique[team["id"]] = team

    return list(unique.values())


@app.get("/api/teams")
def api_teams():
    try:
        teams = get_all_teams()
        return {
            "teams": teams
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e)
            }
        )


# ---------------------------------------------------------
# TEAM SCHEDULE
# ---------------------------------------------------------

def get_team_schedule(team_id):
    url = f"{BASE_URL}/teams/{team_id}/schedule"

    data = espn_get(
        url,
        {
            "season": datetime.now().year
        }
    )

    team_info = data.get("team", {})

    games = []

    for event in data.get("events", []):
        try:
            competition = event["competitions"][0]

            competitors = competition.get(
                "competitors",
                []
            )

            team_competitor = None
            opponent = None

            for competitor in competitors:
                if str(
                    competitor.get("team", {}).get("id")
                ) == str(team_id):
                    team_competitor = competitor
                else:
                    opponent = competitor

            if not team_competitor or not opponent:
                continue

            opponent_team = opponent.get(
                "team",
                {}
            )

            status = competition.get(
                "status",
                {}
            )

            status_type = status.get(
                "type",
                {}
            )

            # -------------------------------------------------
            # FIX ESPN SCORE OBJECTS
            # -------------------------------------------------

            team_score = team_competitor.get("score", "")
            opponent_score = opponent.get("score", "")

            if isinstance(team_score, dict):
                team_score = (
                    team_score.get("displayValue")
                    or team_score.get("value")
                    or ""
                )

            if isinstance(opponent_score, dict):
                opponent_score = (
                    opponent_score.get("displayValue")
                    or opponent_score.get("value")
                    or ""
                )

            # -------------------------------------------------
            # DATE
            # -------------------------------------------------

            date_string = event.get("date", "")

            try:
                date_obj = datetime.fromisoformat(
                    date_string.replace("Z", "+00:00")
                )

                game_date = date_obj.strftime(
                    "%b %-d"
                )

            except Exception:
                try:
                    date_obj = datetime.fromisoformat(
                        date_string.replace("Z", "+00:00")
                    )

                    game_date = date_obj.strftime(
                        "%b %#d"
                    )

                except Exception:
                    game_date = date_string

            # -------------------------------------------------
            # HOME / AWAY
            # -------------------------------------------------

            is_home = (
                team_competitor.get("homeAway")
                == "home"
            )

            location_prefix = "vs." if is_home else "@"

            # -------------------------------------------------
            # STATUS
            # -------------------------------------------------

            state = status_type.get(
                "state",
                "pre"
            )

            if state == "post":
                display_status = "FINAL"

            elif state == "in":
                display_status = "LIVE"

            else:
                display_status = "UPCOMING"

            # -------------------------------------------------
            # RESULT
            # -------------------------------------------------

            result = ""

            if state == "post":

                try:
                    team_num = float(team_score)
                    opp_num = float(opponent_score)

                    if team_num > opp_num:
                        result = "W"

                    elif team_num < opp_num:
                        result = "L"

                    else:
                        result = "T"

                except Exception:
                    result = ""

            games.append({
                "id": event.get("id"),

                "date": game_date,

                "date_raw": date_string,

                "status": display_status,

                "state": state,

                "opponent": opponent_team.get(
                    "displayName",
                    "Unknown Opponent"
                ),

                "opponent_id": opponent_team.get(
                    "id"
                ),

                "logo": opponent_team.get(
                    "logos",
                    [{}]
                )[0].get(
                    "href",
                    ""
                ) if opponent_team.get("logos") else "",

                "location": location_prefix,

                "detail": status_type.get(
                    "shortDetail",
                    ""
                ),

                "team_score": team_score,

                "opponent_score": opponent_score,

                "result": result
            })

        except Exception:
            continue

    return {
        "team": {
            "id": team_info.get(
                "id",
                team_id
            ),

            "name": team_info.get(
                "displayName",
                "Team"
            ),

            "logo": (
                team_info.get("logos", [{}])[0].get(
                    "href",
                    ""
                )
                if team_info.get("logos")
                else ""
            )
        },

        "games": games
    }


@app.get("/api/team/{team_id}/schedule")
def api_team_schedule(team_id: str):

    try:
        return get_team_schedule(team_id)

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e)
            }
        )


@app.get("/schedule/{team_id}", response_class=HTMLResponse)
def schedule_page(
    request: Request,
    team_id: str
):

    return templates.TemplateResponse(
        request=request,
        name="schedule.html",
        context={
            "team_id": team_id
        }
    )


# ---------------------------------------------------------
# RANKINGS
# ---------------------------------------------------------

def get_rankings():

    # First try today's scoreboard because ESPN often
    # includes rankings directly in the scoreboard response.

    try:
        today = datetime.now().strftime("%Y%m%d")

        data = espn_get(
            SCOREBOARD_URL,
            {
                "dates": today,
                "limit": 500
            }
        )

        rankings = data.get(
            "rankings",
            []
        )

        if rankings:
            ranking_list = []

            # Prefer AP poll when available
            selected = None

            for ranking in rankings:

                name = str(
                    ranking.get("name", "")
                ).lower()

                if "ap" in name:
                    selected = ranking
                    break

            if selected is None:
                selected = rankings[0]

            for item in selected.get(
                "ranks",
                []
            ):

                team = item.get(
                    "team",
                    {}
                )

                rank = item.get(
                    "current",
                    item.get(
                        "rank",
                        item.get(
                            "value",
                            None
                        )
                    )
                )

                if rank is None:
                    continue

                ranking_list.append({
                    "rank": rank,
                    "name": team.get(
                        "displayName",
                        team.get(
                            "name",
                            "Unknown"
                        )
                    ),
                    "id": team.get(
                        "id"
                    ),
                    "logo": (
                        team.get("logos", [{}])[0].get(
                            "href",
                            ""
                        )
                        if team.get("logos")
                        else ""
                    )
                })

            if ranking_list:
                return ranking_list[:25]

    except Exception:
        pass

    # -----------------------------------------------------
    # Fallback
    # -----------------------------------------------------

    fallback = [
        "Ohio State",
        "Texas",
        "Penn State",
        "Georgia",
        "Oregon",
        "Notre Dame",
        "Alabama",
        "Clemson",
        "LSU",
        "Miami",
        "Texas A&M",
        "Tennessee",
        "Oklahoma",
        "Michigan",
        "Florida",
        "Ole Miss",
        "USC",
        "Indiana",
        "BYU",
        "Iowa State",
        "South Carolina",
        "SMU",
        "Arizona",
        "Utah",
        "Kansas State"
    ]

    return [
        {
            "rank": index + 1,
            "name": name,
            "id": None,
            "logo": ""
        }

        for index, name in enumerate(fallback)
    ]


@app.get("/api/rankings")
def api_rankings():

    try:
        return {
            "rankings": get_rankings()
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e)
            }
        )


# ---------------------------------------------------------
# HOME
# ---------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):

    try:
        games = get_games()
        error = None

    except Exception as e:
        games = []
        error = str(e)

    live_games = sum(
        1
        for game in games
        if game["state"] == "in"
    )

    final_games = sum(
        1
        for game in games
        if game["state"] == "post"
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "games": games,
            "live_games": live_games,
            "final_games": final_games,
            "error": error
        }
    )