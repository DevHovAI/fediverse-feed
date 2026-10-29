# Changelog

## 0.2.0

- Several comma-separated feeds per card, each optionally with its own source
  (`memes, mastodon:#cats`); the number of posts counts per feed, mixed at random
- Mastodon/Pixelfed accounts also without the leading `@` (`name@server`)
- One failing feed no longer empties the card

## 0.1.0

First version.

- Pictures from Lemmy communities, Mastodon hashtags, accounts and trends, and Pixelfed
  hashtags, accounts and the public timeline
- Card editor with source, server, community/hashtag/account, sort and period
- One or several posts, arrows, swipe and optional rotation
- Creator as a small watermark on the picture; info line below optional
- NSFW switch; videos are skipped
- Feeds cached for 30 minutes; the last good result stays when a server is unreachable
- Access tokens for Pixelfed (and locked-down Mastodon servers), checked during setup
