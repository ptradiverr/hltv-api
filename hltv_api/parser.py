"""Pure HTML parsing, independent of network and database access."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
from urllib.parse import urljoin

BASE = "https://www.hltv.org"


class ParseError(ValueError):
    pass


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def has(self, name):
        return name in self.attrs.get("class", "").split()

    def find(self, name):
        return next((n for n in self.walk() if n.has(name)), None)

    def text(self):
        return " ".join(" ".join(c.text() if isinstance(c, Node) else c
                                 for c in self.children).split())


class Tree(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_matches(html: str, kind: str) -> list[dict]:
    if kind not in {"upcoming", "results"}:
        raise ValueError("kind must be upcoming or results")
    if re.search(r"just a moment|verify you are human|cf-chl-|access denied", html, re.I):
        raise ParseError("HLTV returned a challenge or access-denied page")
    root = Tree(html).root
    row_class = "upcomingMatch" if kind == "upcoming" else "result-con"
    rows = [n for n in root.walk() if n.has(row_class)]
    if kind == "upcoming" and not rows:
        rows = [n for n in root.walk() if n.has("match-wrapper")
                and n.attrs.get("live") == "false"]
    # An empty listing is ambiguous: preserve stored data and fail visibly.
    if not rows:
        raise ParseError(f"No {row_class} rows found; page may be empty or markup changed")
    records = {}
    for row in rows:
        link = next((n for n in row.walk()
                     if n.tag == "a" and re.match(r"^/matches/\d+(?:/|$)", n.attrs.get("href", ""))), None)
        if link is None:
            raise ParseError("Match row is missing its match link")
        match_id = int(re.match(r"^/matches/(\d+)", link.attrs["href"])[1])
        teams = [n.text() for n in row.walk() if n.has("matchTeamName" if kind == "upcoming" else "team")]
        if kind == "upcoming" and not teams:
            teams = [n.text() for n in row.walk() if n.has("match-teamname")]
        if kind == "results" and len(teams) != 2:
            raise ParseError(f"Result {match_id} has an unexpected team layout")
        if len(teams) > 2:
            raise ParseError(f"Match {match_id} has too many teams")
        event = row.find("matchEventName" if kind == "upcoming" else "event-name")
        if event is None and kind == "upcoming":
            event = row.find("match-event")
        timestamp = next((n.attrs["data-unix"] for n in row.walk() if n.attrs.get("data-unix")), None)
        try:
            starts_at = datetime.fromtimestamp(int(timestamp) / 1000, timezone.utc).isoformat() if timestamp else None
        except (ValueError, OverflowError, OSError) as exc:
            raise ParseError(f"Invalid timestamp for match {match_id}") from exc
        score = row.find("result-score")
        scores = re.fullmatch(r"(\d+)\s*[-:]\s*(\d+)", score.text()) if score else None
        if kind == "results" and not scores:
            raise ParseError(f"Result {match_id} is missing a valid score")
        records[match_id] = {
            "id": match_id, "url": urljoin(BASE, link.attrs["href"]),
            "status": "scheduled" if kind == "upcoming" else "finished",
            "team1": teams[0] if teams else None,
            "team2": teams[1] if len(teams) > 1 else None,
            "event": (event.attrs.get("data-event-headline") or event.text()) if event else None,
            "starts_at": starts_at,
            "score1": int(scores[1]) if scores else None,
            "score2": int(scores[2]) if scores else None,
        }
    return list(records.values())
