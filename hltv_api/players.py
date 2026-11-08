"""Parsers for the default statistics listing and player overview pages."""
import re
from urllib.parse import urlparse

from .parser import BASE, ParseError, Tree


def player_path(url):
    parsed = urlparse(url)
    match = re.fullmatch(r"/stats/players/([1-9]\d{0,17})/([a-zA-Z0-9_-]+)", parsed.path)
    if (parsed.scheme != "https" or parsed.netloc != "www.hltv.org"
            or parsed.query or parsed.fragment or not match):
        raise ValueError("Use an unfiltered https://www.hltv.org/stats/players/<id>/<name> URL")
    return parsed.path, int(match[1])


def document(html):
    if re.search(r"just a moment|verify you are human|cf-chl-|access denied|too many requests", html, re.I):
        raise ParseError("HLTV returned a blocked player statistics page")
    return Tree(html).root


def number(text, *, integer=False, percent=False):
    value = text.strip().replace("\u2212", "-")
    if value.lower() in {"-", "n/a", ""}:
        return None
    if percent:
        value = value.removesuffix("%").strip()
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", value):
        raise ParseError("Invalid numeric player statistic")
    if integer and "." in value:
        raise ParseError("Expected an integer player statistic")
    parsed = int(value.replace(",", "")) if integer else float(value.replace(",", ""))
    if percent and not 0 <= parsed <= 100:
        raise ParseError("Invalid percentage player statistic")
    return parsed


def parse_players(html):
    root = document(html)
    table = root.find("player-ratings-table")
    if table is None:
        raise ParseError("Player statistics table not found")
    rating_header = next((n for n in table.walk() if n.tag == "th" and n.has("ratingCol")), None)
    version = re.search(r"\b(\d+\.\d+)\b", rating_header.text()) if rating_header else None
    if not version:
        raise ParseError("Player rating version not found")
    records = {}
    for row in table.walk():
        if row.tag != "tr" or not any(n.tag == "td" for n in row.children if hasattr(n, "tag")):
            continue
        player = row.find("playerCol")
        link = next((n for n in player.walk() if n.tag == "a" and n.attrs.get("href", "").startswith("/stats/players/")), None) if player else None
        if link is None or not link.text():
            raise ParseError("Player row is missing an identity")
        url = BASE + link.attrs["href"]
        try:
            _, player_id = player_path(url)
        except ValueError as exc:
            raise ParseError("Player row has an invalid profile URL") from exc
        details = [n for n in row.walk() if n.tag == "td" and n.has("statsDetail")]
        diff, rating = row.find("kdDiffCol"), row.find("ratingCol")
        if len(details) != 3 or diff is None or rating is None:
            raise ParseError(f"Unexpected statistics layout for player {player_id}")
        teams = []
        team_column = row.find("teamCol")
        if team_column:
            for team in team_column.walk():
                match = re.fullmatch(r"/stats/teams/(\d+)/[a-zA-Z0-9_-]+", team.attrs.get("href", ""))
                if match:
                    image = next((n for n in team.walk() if n.tag == "img"), None)
                    teams.append({"id": int(match[1]), "name": (image.attrs.get("title") if image else None) or team.text() or None})
        flag = player.find("flag")
        summary = {"maps": number(details[0].text(), integer=True),
                   "rounds": number(details[1].text(), integer=True),
                   "kd_difference": number(diff.text(), integer=True),
                   "kd_ratio": number(details[2].text()),
                   "rating": {"version": version[1], "value": number(rating.text())}}
        if any(summary[key] is None for key in ("maps", "rounds", "kd_difference", "kd_ratio")) or summary["rating"]["value"] is None:
            raise ParseError(f"Incomplete statistics for player {player_id}")
        if any(summary[key] < 0 for key in ("maps", "rounds", "kd_ratio")) or summary["rating"]["value"] < 0:
            raise ParseError(f"Invalid statistics for player {player_id}")
        records[player_id] = {"id": player_id, "name": link.text(), "url": url,
                              "country": flag.attrs.get("title") if flag else None,
                              "teams": teams, "summary": summary}
    if not records:
        raise ParseError("Player statistics listing is empty")
    return list(records.values())


def parse_player_stats(html, url):
    _, player_id = player_path(url)
    root = document(html)
    identity_links = [n for n in root.walk() if n.tag == "a" and re.match(rf"^/player/{player_id}(?:/|$)", n.attrs.get("href", ""))]
    canonical = [n.attrs.get("href") for n in root.walk() if n.tag == "link" and n.attrs.get("rel") == "canonical"]
    if not identity_links and url not in canonical:
        raise ParseError("Player page does not match the requested player ID")
    name = root.find("context-item-name") or root.find("summaryNickname")
    if name is None or not name.text():
        raise ParseError("Player nickname not found")
    fields = {
        "total kills": ("kills", True, False), "total deaths": ("deaths", True, False),
        "headshot %": ("headshot_percentage", False, True), "k/d ratio": ("kd_ratio", False, False),
        "damage / round": ("damage_per_round", False, False),
        "grenade dmg / round": ("grenade_damage_per_round", False, False),
        "maps played": ("maps", True, False), "rounds played": ("rounds", True, False),
        "kills / round": ("kills_per_round", False, False),
        "assists / round": ("assists_per_round", False, False),
        "deaths / round": ("deaths_per_round", False, False),
    }
    statistics = {field[0]: None for field in fields.values()}
    statistics["ratings"] = {}
    for row in root.walk():
        if not row.has("stats-row"):
            continue
        spans = [n for n in row.children if hasattr(n, "tag") and n.tag == "span"]
        if len(spans) != 2:
            continue
        label = spans[0].text().casefold()
        if label in fields:
            key, integer, percent = fields[label]
            value = number(spans[1].text(), integer=integer, percent=percent)
            if value is not None and value < 0:
                raise ParseError("Player overview statistic cannot be negative")
            statistics[key] = value
        rating = re.fullmatch(r"rating (\d+\.\d+)", label)
        if rating:
            value = number(spans[1].text())
            if value is not None and value < 0:
                raise ParseError("Player rating cannot be negative")
            statistics["ratings"][rating[1]] = value
    if any(statistics[key] is None for key in ("kills", "deaths", "maps", "rounds", "kd_ratio")):
        raise ParseError("Player overview is missing required statistics")
    return {"id": player_id, "name": name.text(), "url": url, "statistics": statistics}
