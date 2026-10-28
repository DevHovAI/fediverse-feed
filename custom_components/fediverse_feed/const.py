from datetime import timedelta

DOMAIN = "fediverse_feed"
CONF_PIXELFED_INSTANCE = "pixelfed_instance"
CONF_PIXELFED_TOKEN = "pixelfed_token"
CONF_MASTODON_INSTANCE = "mastodon_instance"
CONF_MASTODON_TOKEN = "mastodon_token"

# Each feed is fetched at most this often, however many cards or browsers ask for it.
CACHE_TTL = timedelta(minutes=30)

CARD_URL = "/fediverse_feed/fediverse-feed-card.js"
