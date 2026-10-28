"""Clients for Lemmy and for Mastodon-compatible servers (Mastodon, Pixelfed).

Every source is reduced to the same small post dict, which is all the card needs.
Videos are dropped everywhere: the card shows pictures only.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urlparse

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=20)
USER_AGENT = "HomeAssistant-FediverseFeed/0.1 (+https://github.com/DevHovAI/fediverse-feed)"

SOURCES = ("lemmy", "mastodon", "pixelfed")
DEFAULT_INSTANCES = {"lemmy": "lemmy.world", "mastodon": "mastodon.social", "pixelfed": "pixelfed.social"}
SORTS = ("top", "hot", "new", "active")
PERIODS = ("hour", "day", "week", "month", "year", "all")
PERIOD_DELTAS = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}

_LEMMY_TOP = {
    "hour": "TopHour",
    "day": "TopDay",
    "week": "TopWeek",
    "month": "TopMonth",
    "year": "TopYear",
    "all": "TopAll",
}
_LEMMY_SORT = {"hot": "Hot", "new": "New", "active": "Active"}

_IMAGE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|avif)(\?|$)", re.I)
_VIDEO_EXT = re.compile(r"\.(mp4|webm|mov|m4v|gifv|mkv)(\?|$)", re.I)
_VIDEO_HOSTS = ("youtube.com", "youtu.be", "v.redd.it", "redgifs.com", "streamable.com", "vimeo.com",
                "tiktok.com", "peertube")
# Mastodon timelines return at most 40 statuses per page.
_PAGE = 40


class FeedError(Exception):
    """The server could not be reached or answered with an error."""


class AuthRequired(FeedError):
    """The server wants an access token (Pixelfed, locked-down Mastodon servers)."""


class NotFound(FeedError):
    """Community, hashtag or account does not exist on that server."""


@dataclass
class Post:
    id: str
    title: str
    text: str
    image: str | None
    image_alt: str
    url: str
    author: str
    place: str
    created: str
    score: int
    nsfw: bool

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Query:
    source: str
    instance: str
    query: str = ""
    sort: str = "top"
    period: str = "day"
    nsfw: bool = False
    images_only: bool = True
    count: int = 1

    @property
    def key(self) -> tuple:
        # count is applied after the cache, so one fetch serves cards with different counts
        return (self.source, self.instance.lower(), self.query.strip().lower(), self.sort, self.period,
                self.nsfw, self.images_only)


class _Text(HTMLParser):
    """HTML of a status → plain text with line breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "p":
            self.parts.append("\n\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html or "")
    text = "".join(parser.parts)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def strip_hashtag_lines(text: str) -> str:
    """Drop lines that are nothing but hashtags – common on Mastodon, useless as a title."""
    lines = [line for line in text.split("\n") if not re.fullmatch(r"\s*(#\w+\s*)+", line)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def clean_instance(instance: str, source: str) -> str:
    """'https://Lemmy.World/' → 'lemmy.world'; empty → the default server of the source."""
    value = (instance or "").strip()
    if "://" in value:
        value = urlparse(value).netloc
    value = value.strip("/").lower()
    return value or DEFAULT_INSTANCES[source]


def _is_video_url(url: str | None) -> bool:
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return bool(_VIDEO_EXT.search(url)) or any(h in host for h in _VIDEO_HOSTS)


def _host(url: str | None) -> str:
    return urlparse(url or "").netloc


class FeedClient:
    def __init__(self, session: aiohttp.ClientSession, tokens: dict[str, str] | None = None) -> None:
        self._session = session
        # {instance: access token}
        self._tokens = {k.lower(): v for k, v in (tokens or {}).items() if v}

    async def _get(self, instance: str, path: str, params: dict | None = None) -> object:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if token := self._tokens.get(instance):
            headers["Authorization"] = f"Bearer {token}"
        url = f"https://{instance}{path}"
        try:
            async with self._session.get(url, params=params, headers=headers, timeout=TIMEOUT) as resp:
                if resp.status in (401, 403):
                    raise AuthRequired(f"{instance} needs an access token")
                if resp.status == 404:
                    raise NotFound(path)
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise FeedError(f"{url}: {err}") from err

    async def verify(self, instance: str) -> None:
        """Raise AuthRequired if the token for instance is not accepted."""
        await self._get(instance, "/api/v1/accounts/verify_credentials")

    async def posts(self, q: Query) -> list[Post]:
        if q.source == "lemmy":
            return await self._lemmy(q)
        return await self._mastodon(q)

    # --- Lemmy -------------------------------------------------------------------------

    async def _lemmy(self, q: Query) -> list[Post]:
        sort = _LEMMY_TOP[q.period] if q.sort == "top" else _LEMMY_SORT.get(q.sort, "Hot")
        params = {"sort": sort, "limit": "50", "type_": "All", "show_nsfw": "true" if q.nsfw else "false"}
        community = q.query.strip().lstrip("!")
        community = community[2:] if community.lower().startswith("c/") else community
        if community:
            params["community_name"] = community
        data = await self._get(q.instance, "/api/v3/post/list", params)
        posts = []
        for view in data.get("posts", []):
            if post := parse_lemmy(view, q):
                posts.append(post)
        return posts

    # --- Mastodon and Pixelfed ---------------------------------------------------------

    async def _mastodon(self, q: Query) -> list[Post]:
        query = q.query.strip()
        pixelfed = q.source == "pixelfed"
        if not query or query.lower() == "trends":
            # Pixelfed has no trends endpoint; its public timeline comes closest.
            if pixelfed:
                statuses = await self._timeline(q, "/api/v1/timelines/public", {})
            else:
                statuses = await self._timeline(q, "/api/v1/trends/statuses", None)
        elif query.startswith("@"):
            account = await self._account(q.instance, query[1:])
            statuses = await self._timeline(q, f"/api/v1/accounts/{account}/statuses",
                                            {"exclude_replies": "true"})
        else:
            tag = query.lstrip("#").strip()
            statuses = await self._timeline(q, f"/api/v1/timelines/tag/{tag}", {})
        posts = [p for s in statuses if (p := parse_status(s, q))]
        return rank(posts, q.sort, q.period)

    async def _timeline(self, q: Query, path: str, params: dict | None) -> list[dict]:
        """Up to three pages for "top" and "hot" (ranked here), one page otherwise.

        params None means the endpoint takes no paging (trends).
        """
        if params is None:
            return list(await self._get(q.instance, path, {"limit": "40"}) or [])
        params = {**params, "limit": str(_PAGE)}
        if q.source == "mastodon":
            params["only_media"] = "true"
        pages = 3 if q.sort in ("top", "hot") else 1
        since = datetime.now(UTC) - PERIOD_DELTAS.get(q.period, timedelta(days=36500))
        statuses: list[dict] = []
        for _ in range(pages):
            page = list(await self._get(q.instance, path, params) or [])
            statuses += page
            if len(page) < _PAGE or _created(page[-1]) < since:
                break
            params["max_id"] = page[-1]["id"]
        return statuses

    async def _account(self, instance: str, acct: str) -> str:
        """Account id for 'name' or 'name@server'."""
        try:
            data = await self._get(instance, "/api/v1/accounts/lookup", {"acct": acct})
            return str(data["id"])
        except NotFound:
            pass
        # Pixelfed has no lookup endpoint; search returns the account among others.
        found = await self._get(instance, "/api/v1/accounts/search", {"q": acct, "limit": "5"})
        name = acct.lower()
        for account in found or []:
            if str(account.get("acct", "")).lower() in (name, name.split("@")[0]):
                return str(account["id"])
        raise NotFound(acct)


def parse_lemmy(view: dict, q: Query) -> Post | None:
    post, community = view.get("post", {}), view.get("community", {})
    if post.get("deleted") or post.get("removed"):
        return None
    nsfw = bool(post.get("nsfw") or community.get("nsfw"))
    if nsfw and not q.nsfw:
        return None
    url = post.get("url")
    content_type = post.get("url_content_type") or ""
    if content_type.startswith("video/") or _is_video_url(url):
        return None
    if content_type.startswith("image/") or (url and _IMAGE_EXT.search(url)):
        image = url
    else:
        # Link posts: the preview picture of the linked page, if any
        image = post.get("thumbnail_url")
    if q.images_only and not image:
        return None
    creator = view.get("creator", {})
    return Post(
        id=str(post.get("id")),
        title=post.get("name", ""),
        text=(post.get("body") or "")[:500],
        image=image,
        image_alt=post.get("alt_text") or "",
        url=post.get("ap_id") or url or "",
        author=f"{creator.get('name', '')}@{_host(creator.get('actor_id'))}".rstrip("@"),
        place=f"{community.get('name', '')}@{_host(community.get('actor_id'))}".rstrip("@"),
        created=post.get("published", ""),
        score=int(view.get("counts", {}).get("score", 0)),
        nsfw=nsfw,
    )


def parse_status(status: dict, q: Query) -> Post | None:
    status = status.get("reblog") or status
    nsfw = bool(status.get("sensitive"))
    if nsfw and not q.nsfw:
        return None
    media = status.get("media_attachments") or []
    images = [m for m in media if m.get("type") == "image"]
    if media and not images:
        return None  # video, gifv or audio only
    if q.images_only and not images:
        return None
    first = images[0] if images else {}
    text = strip_hashtag_lines(html_to_text(status.get("content", "")))
    title = status.get("spoiler_text") or text.split("\n", 1)[0]
    account = status.get("account", {})
    acct = account.get("acct", "")
    if acct and "@" not in acct:
        acct = f"{acct}@{q.instance}"
    return Post(
        id=str(status.get("id")),
        title=title[:300],
        text=text[:500],
        image=first.get("url") or first.get("preview_url"),
        image_alt=first.get("description") or "",
        url=status.get("url") or status.get("uri") or "",
        author=acct,
        place=account.get("display_name") or acct,
        created=status.get("created_at", ""),
        score=int(status.get("favourites_count", 0)) + int(status.get("reblogs_count", 0)),
        nsfw=nsfw,
    )


def _created(item: dict | Post) -> datetime:
    value = item.created if isinstance(item, Post) else (item.get("created_at") or "")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def rank(posts: list[Post], sort: str, period: str, now: datetime | None = None) -> list[Post]:
    """Mastodon has no "top of the day": filter by age and sort by favourites + boosts here."""
    now = now or datetime.now(UTC)
    if sort == "top":
        if delta := PERIOD_DELTAS.get(period):
            posts = [p for p in posts if _created(p) >= now - delta]
        return sorted(posts, key=lambda p: p.score, reverse=True)
    if sort == "hot":
        def hot(p: Post) -> float:
            hours = max((now - _created(p)).total_seconds() / 3600, 0)
            return (p.score + 1) / (hours + 2) ** 1.5

        return sorted(posts, key=hot, reverse=True)
    return sorted(posts, key=_created, reverse=True)
