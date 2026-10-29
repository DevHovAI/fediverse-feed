from datetime import UTC, datetime, timedelta

from custom_components.fediverse_feed.api import (
    Post,
    Query,
    clean_instance,
    html_to_text,
    parse_lemmy,
    parse_status,
    rank,
    split_feeds,
    strip_hashtag_lines,
)


def lemmy(view, **kw):
    return parse_lemmy(view, Query(source="lemmy", instance="lemmy.example", **kw))


def test_lemmy_keeps_pictures_and_drops_videos(lemmy_posts):
    posts = [p for v in lemmy_posts["posts"] if (p := lemmy(v))]
    assert [p.title for p in posts] == ["Picture", "Link with preview"]
    first = posts[0]
    assert first.image == "https://lemmy.example/pictrs/image/a.png"
    assert first.url == "https://lemmy.example/post/1"
    assert first.place == "memes@lemmy.example"
    assert first.author == "alice@lemmy.example"
    assert first.score == 600
    # A link post shows the preview picture of the linked page
    assert posts[1].image == "https://lemmy.example/pictrs/image/t.jpg"


def test_lemmy_nsfw_and_text_posts_on_request(lemmy_posts):
    posts = [p for v in lemmy_posts["posts"] if (p := lemmy(v, nsfw=True, images_only=False))]
    titles = [p.title for p in posts]
    assert "Spicy" in titles and "Text only" in titles
    assert "Video" not in titles and "YouTube" not in titles and "Removed" not in titles
    assert next(p for p in posts if p.title == "Spicy").nsfw is True


def test_lemmy_community_nsfw_counts(lemmy_posts):
    view = lemmy_posts["posts"][0]
    view["community"]["nsfw"] = True
    assert lemmy(view) is None


def mastodon(statuses, **kw):
    q = Query(source="mastodon", instance="masto.example", **kw)
    return [p for s in statuses if (p := parse_status(s, q))]


def test_mastodon_pictures_only(mastodon_tag):
    posts = mastodon(mastodon_tag)
    # 12 video, 13 sensitive, 15 no media, 16 gifv are dropped
    assert [p.id for p in posts] == ["10", "11", "14", "17"]
    assert posts[0].title == "Hello world"
    assert posts[0].image == "https://files.example/10.image"
    assert posts[0].image_alt == "alt"
    assert posts[0].author == "bob@masto.example"
    assert posts[3].author == "carol@other.example"


def test_mastodon_sensitive_on_request(mastodon_tag):
    posts = mastodon(mastodon_tag, nsfw=True, images_only=False)
    assert {"13", "15"} <= {p.id for p in posts}
    assert "12" not in {p.id for p in posts} and "16" not in {p.id for p in posts}


def test_mastodon_boost_shows_original(mastodon_tag):
    boost = {"id": "99", "reblog": mastodon_tag[0], "media_attachments": [], "account": {"acct": "eve"}}
    (post,) = mastodon([boost])
    assert post.id == "10"


def _post(pid, hours, score, now):
    created = (now - timedelta(hours=hours)).isoformat()
    return Post(pid, "", "", "x", "", "", "", "", created, score, False)


def test_rank_top_filters_by_period():
    now = datetime(2026, 10, 28, 12, tzinfo=UTC)
    posts = [_post("a", 1, 5, now), _post("b", 30, 500, now), _post("c", 2, 50, now)]
    assert [p.id for p in rank(posts, "top", "day", now)] == ["c", "a"]
    assert [p.id for p in rank(posts, "top", "week", now)] == ["b", "c", "a"]
    assert [p.id for p in rank(posts, "new", "day", now)] == ["a", "c", "b"]


def test_rank_hot_prefers_recent():
    now = datetime(2026, 10, 28, 12, tzinfo=UTC)
    posts = [_post("old", 48, 100, now), _post("new", 1, 20, now)]
    assert rank(posts, "hot", "day", now)[0].id == "new"


def test_helpers():
    assert clean_instance("https://Lemmy.World/", "lemmy") == "lemmy.world"
    assert clean_instance("", "pixelfed") == "pixelfed.social"
    assert html_to_text("<p>One<br>Two</p><p>Three</p>") == "One\nTwo\n\nThree"
    assert strip_hashtag_lines("#meme #funny\nWhen it works\n\n#dev") == "When it works"


def test_split_feeds():
    base = Query(source="lemmy", instance="lemmy.example", query="")
    assert split_feeds(base) == [base]
    feeds = split_feeds(Query(source="lemmy", instance="lemmy.example",
                              query="memes, cats@lemmy.ml ,Mastodon:#cats, pixelfed:@name,lemmy:, ,"))
    assert [(f.source, f.instance, f.query) for f in feeds] == [
        ("lemmy", "lemmy.example", "memes"),
        ("lemmy", "lemmy.example", "cats@lemmy.ml"),
        ("mastodon", "mastodon.social", "#cats"),
        ("pixelfed", "pixelfed.social", "@name"),
        ("lemmy", "lemmy.example", ""),
    ]
