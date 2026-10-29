/*
 * Fediverse Feed Card – the top pictures of a Lemmy community, a Mastodon hashtag or
 * account, or a Pixelfed feed.
 *
 * Posts come from the Fediverse Feed integration over the websocket
 * ("fediverse_feed/posts"); the integration also serves this file, so no dashboard
 * resource is needed. Colors come from the Home Assistant theme.
 */

const VERSION = "0.2.0";
const TAG = "fediverse-feed-card";

// The integration fetches each feed at most every 30 minutes; asking more often only hits its cache.
const REFRESH_MS = 30 * 60 * 1000;

const DEFAULTS = {
  source: "lemmy",
  instance: "",
  query: "memes",
  sort: "top",
  period: "day",
  count: 1,
  nsfw: false,
  images_only: true,
  show_title: true,
  show_meta: false,
  show_credit: true,
  show_text: false,
  max_height: 450,
  rotate: 0,
};

const DEFAULT_INSTANCES = { lemmy: "lemmy.world", mastodon: "mastodon.social", pixelfed: "pixelfed.social" };

const TEXTS = {
  en: {
    loading: "Loading …",
    empty: "No pictures in this feed for the chosen period.",
    not_set_up: "Set up the Fediverse Feed integration first (Settings → Devices & services).",
    auth_required: (i) => `${i} needs an access token. Add it in the Fediverse Feed integration (Configure).`,
    not_found: (q, i) => `“${q}” was not found on ${i}.`,
    cannot_connect: (i) => `${i} cannot be reached right now.`,
    prev: "Previous",
    next: "Next",
    open: "Open post",
  },
  de: {
    loading: "Lädt …",
    empty: "In diesem Feed gibt es für den Zeitraum keine Bilder.",
    not_set_up: "Richte zuerst die Integration Fediverse Feed ein (Einstellungen → Geräte & Dienste).",
    auth_required: (i) => `${i} braucht einen Zugangsschlüssel. Trag ihn in der Integration Fediverse Feed ein (Konfigurieren).`,
    not_found: (q, i) => `„${q}“ gibt es auf ${i} nicht.`,
    cannot_connect: (i) => `${i} ist gerade nicht erreichbar.`,
    prev: "Zurück",
    next: "Weiter",
    open: "Beitrag öffnen",
  },
};

const LABELS = {
  source: "Source",
  instance: "Server (optional)",
  query: "Community, #hashtag or @account – several separated by commas",
  sort: "Sort",
  period: "Period (for Top)",
  count: "Number of posts",
  rotate: "Next post every … seconds (0 = off)",
  nsfw: "Show NSFW posts",
  images_only: "Pictures only",
  show_title: "Title",
  show_meta: "Place, time and score",
  show_credit: "Creator in the picture corner",
  show_text: "Post text",
  max_height: "Maximum picture height (px)",
  title: "Card title (optional)",
};

const HELPERS = {
  instance: "Empty: lemmy.world, mastodon.social or pixelfed.social",
  query:
    "Lemmy: community such as memes or memes@lemmy.ml (empty = whole server). " +
    "Mastodon/Pixelfed: #hashtag, @account or @account@server (empty = trends / public timeline). " +
    "Several feeds with commas, each with its own source if you like: memes, mastodon:#cats, pixelfed:@name. " +
    "Number of posts then counts per feed, mixed at random.",
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// Only http(s) links go into href/src, never javascript: or data: from a remote server.
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");

// A factory, because the class has to extend whatever HTMLElement is current (see define()).
const createCardClass = (Base) =>
  class FediverseFeedCard extends Base {
    static getStubConfig() {
      return { source: "lemmy", query: "memes", sort: "top", period: "day" };
    }

    static getConfigForm() {
      const select = (options) => ({ select: { mode: "dropdown", options } });
      return {
        schema: [
          {
            type: "grid",
            name: "",
            schema: [
              {
                name: "source",
                selector: select([
                  { value: "lemmy", label: "Lemmy" },
                  { value: "mastodon", label: "Mastodon" },
                  { value: "pixelfed", label: "Pixelfed" },
                ]),
              },
              { name: "instance", selector: { text: {} } },
            ],
          },
          { name: "query", selector: { text: {} } },
          {
            type: "grid",
            name: "",
            schema: [
              {
                name: "sort",
                selector: select([
                  { value: "top", label: "Top" },
                  { value: "hot", label: "Hot" },
                  { value: "new", label: "New" },
                  { value: "active", label: "Active (Lemmy)" },
                ]),
              },
              {
                name: "period",
                selector: select([
                  { value: "hour", label: "Hour" },
                  { value: "day", label: "Day" },
                  { value: "week", label: "Week" },
                  { value: "month", label: "Month" },
                  { value: "year", label: "Year" },
                  { value: "all", label: "All time" },
                ]),
              },
            ],
          },
          {
            type: "grid",
            name: "",
            schema: [
              { name: "count", selector: { number: { min: 1, max: 20, mode: "box" } } },
              { name: "rotate", selector: { number: { min: 0, max: 3600, mode: "box", unit_of_measurement: "s" } } },
            ],
          },
          {
            type: "grid",
            name: "",
            schema: [
              { name: "nsfw", selector: { boolean: {} } },
              { name: "images_only", selector: { boolean: {} } },
              { name: "show_title", selector: { boolean: {} } },
              { name: "show_meta", selector: { boolean: {} } },
              { name: "show_credit", selector: { boolean: {} } },
              { name: "show_text", selector: { boolean: {} } },
            ],
          },
          { name: "max_height", selector: { number: { min: 100, max: 2000, mode: "box", unit_of_measurement: "px" } } },
          { name: "title", selector: { text: {} } },
        ],
        computeLabel: (s) => LABELS[s.name],
        computeHelper: (s) => HELPERS[s.name],
      };
    }

    setConfig(config) {
      this._config = { ...DEFAULTS, ...config };
      this._index = 0;
      this._startRotation();
      this._render();
      this._load();
    }

    set hass(hass) {
      const first = !this._hass;
      const language = this._hass?.language;
      this._hass = hass;
      if (first) this._load();
      else if (hass.language !== language) this._render();
    }

    connectedCallback() {
      this._refresh = setInterval(() => this._load(true), REFRESH_MS);
      this._startRotation();
    }

    disconnectedCallback() {
      clearInterval(this._refresh);
      clearInterval(this._rotation);
    }

    getCardSize() {
      return 6;
    }

    getGridOptions() {
      return { columns: 12, min_columns: 4, rows: "auto" };
    }

    get _t() {
      return (this._hass?.language || "").startsWith("de") ? TEXTS.de : TEXTS.en;
    }

    get _instance() {
      return this._config.instance || DEFAULT_INSTANCES[this._config.source] || "";
    }

    // The fields that decide what the integration has to fetch.
    get _request() {
      const c = this._config;
      return {
        type: "fediverse_feed/posts",
        source: c.source,
        instance: c.instance || "",
        query: c.query || "",
        sort: c.sort,
        period: c.period,
        nsfw: !!c.nsfw,
        images_only: c.images_only !== false,
        count: Math.min(Math.max(parseInt(c.count, 10) || 1, 1), 20),
      };
    }

    async _load(background = false) {
      if (!this._hass || !this._config) return;
      const request = this._request;
      const key = JSON.stringify(request);
      // An edit in the card editor while a request is running: only the newest answer counts.
      this._pending = key;
      if (!background || key !== this._key) {
        this._state = { status: "loading" };
        this._render();
      }
      let state;
      try {
        const result = await this._hass.callWS(request);
        state = { status: "ok", posts: result.posts || [] };
      } catch (err) {
        state = { status: "error", code: err?.code || "cannot_connect" };
      }
      if (this._pending !== key) return;
      // A failed background refresh keeps the pictures that are already there.
      if (background && state.status === "error" && this._state?.status === "ok") return;
      this._key = key;
      this._state = state;
      if (this._index >= (state.posts?.length || 0)) this._index = 0;
      this._render();
    }

    _startRotation() {
      clearInterval(this._rotation);
      const seconds = Number(this._config?.rotate) || 0;
      if (seconds > 0) this._rotation = setInterval(() => this._step(1), seconds * 1000);
    }

    _step(delta) {
      const n = this._state?.posts?.length || 0;
      if (n < 2) return;
      this._index = (this._index + delta + n) % n;
      this._render();
    }

    _age(iso) {
      const then = Date.parse(iso);
      if (Number.isNaN(then)) return "";
      const seconds = (then - Date.now()) / 1000;
      const units = [
        ["year", 31536000],
        ["month", 2592000],
        ["week", 604800],
        ["day", 86400],
        ["hour", 3600],
        ["minute", 60],
      ];
      const rtf = new Intl.RelativeTimeFormat(this._hass?.language || undefined, { numeric: "auto" });
      for (const [unit, size] of units) {
        if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
      }
      return rtf.format(0, "minute");
    }

    _message() {
      const t = this._t;
      const s = this._state || { status: "loading" };
      if (s.status === "loading") return t.loading;
      if (s.status === "error") {
        if (s.code === "not_set_up") return t.not_set_up;
        if (s.code === "auth_required") return t.auth_required(this._instance);
        if (s.code === "not_found") return t.not_found(this._config.query, this._instance);
        return t.cannot_connect(this._instance);
      }
      return s.posts.length ? "" : t.empty;
    }

    _postHtml(post) {
      const c = this._config;
      const t = this._t;
      const url = safeUrl(post.url);
      const image = safeUrl(post.image);
      // Creator as a small watermark in the picture corner saves a line below it.
      const lemmy = (post.source || c.source) === "lemmy";
      const creator = lemmy ? (post.author || "").split("@")[0] : post.place || (post.author || "").split("@")[0];
      const credit = image && c.show_credit && creator;
      // With the watermark, Lemmy keeps only the community below; Mastodon/Pixelfed need nothing more.
      const who = credit
        ? [lemmy ? post.place : ""]
        : [post.place, post.author !== post.place ? post.author : ""];
      const meta = [...who, this._age(post.created)]
        .filter(Boolean)
        .map(esc)
        .join(" · ");
      const height = Math.max(Number(c.max_height) || DEFAULTS.max_height, 100);
      return `
        ${
          image
            ? `<a class="media" href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="${esc(t.open)}">
                 <span class="frame">
                   <img src="${esc(image)}" alt="${esc(post.image_alt || post.title)}" style="max-height:${height}px">
                   ${credit ? `<span class="credit" title="${esc(post.author)}">${esc(creator)}</span>` : ""}
                 </span>
               </a>`
            : ""
        }
        <div class="info">
          ${
            c.show_title && post.title
              ? `<a class="post-title" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(post.title)}</a>`
              : ""
          }
          ${c.show_text && post.text && post.text !== post.title ? `<div class="text">${esc(post.text)}</div>` : ""}
          ${c.show_meta ? `<div class="meta">${meta}${post.score ? ` · ▲ ${esc(post.score)}` : ""}</div>` : ""}
        </div>`;
    }

    _render() {
      if (!this._config) return;
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      const t = this._t;
      const posts = this._state?.posts || [];
      const message = this._message();
      const post = posts[this._index];
      const nav =
        posts.length > 1
          ? `<div class="nav">
               <button class="arrow" data-step="-1" aria-label="${esc(t.prev)}">‹</button>
               <div class="dots">${posts
                 .map((_, i) => `<span class="dot${i === this._index ? " on" : ""}" data-index="${i}"></span>`)
                 .join("")}</div>
               <button class="arrow" data-step="1" aria-label="${esc(t.next)}">›</button>
             </div>`
          : "";
      const title = this._config.title;

      this.shadowRoot.innerHTML = `
        <style>${STYLE}</style>
        <ha-card>
          ${title ? `<div class="title">${esc(title)}</div>` : ""}
          ${message ? `<div class="empty">${esc(message)}</div>` : this._postHtml(post)}
          ${nav}
        </ha-card>`;

      this.shadowRoot.querySelectorAll("[data-step]").forEach((b) =>
        b.addEventListener("click", () => this._step(Number(b.dataset.step))),
      );
      this.shadowRoot.querySelectorAll("[data-index]").forEach((d) =>
        d.addEventListener("click", () => {
          this._index = Number(d.dataset.index);
          this._render();
        }),
      );
      const media = this.shadowRoot.querySelector(".media");
      if (media && posts.length > 1) this._swipe(media);
    }

    // Swipe left/right on the picture; a tap still opens the post.
    _swipe(el) {
      let x0 = null;
      el.addEventListener("pointerdown", (e) => (x0 = e.clientX));
      el.addEventListener("click", (e) => {
        if (this._swiped) {
          e.preventDefault();
          this._swiped = false;
        }
      });
      el.addEventListener("pointerup", (e) => {
        if (x0 === null) return;
        const dx = e.clientX - x0;
        x0 = null;
        if (Math.abs(dx) > 40) {
          this._swiped = true;
          this._step(dx < 0 ? 1 : -1);
        }
      });
      el.addEventListener("dragstart", (e) => e.preventDefault());
    }
  };

const STYLE = `
  ha-card { overflow: hidden; }
  .title { font-size: 1.25rem; font-weight: 500; padding: 12px 16px 0; color: var(--primary-text-color); }
  .media { display: flex; justify-content: center; background: var(--secondary-background-color); margin-top: 12px; touch-action: pan-y; }
  .title + .media { margin-top: 12px; }
  ha-card > .media:first-child { margin-top: 0; }
  /* The frame is as wide as the picture, so the watermark sits on the picture, not on the bars beside it. */
  .frame { position: relative; display: block; max-width: 100%; }
  .media img { display: block; max-width: 100%; width: auto; height: auto; user-select: none; }
  .credit { position: absolute; right: 6px; bottom: 6px; max-width: 60%; overflow: hidden; text-overflow: ellipsis;
            white-space: nowrap; font-size: 0.7rem; line-height: 1.4; padding: 0 6px; border-radius: 4px;
            color: rgba(255, 255, 255, 0.9); background: rgba(0, 0, 0, 0.35); pointer-events: none; }
  .info { padding: 10px 16px 14px; }
  .post-title { display: block; color: var(--primary-text-color); text-decoration: none; font-weight: 500; line-height: 1.35; }
  .text { margin-top: 6px; white-space: pre-line; color: var(--primary-text-color); font-size: 0.9rem; line-height: 1.4;
          display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; overflow: hidden; }
  .meta { margin-top: 4px; font-size: 0.8rem; color: var(--secondary-text-color); }
  .empty { padding: 16px; color: var(--secondary-text-color); }
  .nav { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 0 8px 10px; }
  .arrow { font: inherit; font-size: 1.4rem; line-height: 1; cursor: pointer; border: none; background: none;
           color: var(--secondary-text-color); padding: 2px 10px; border-radius: 999px; }
  .arrow:hover { background: var(--secondary-background-color); }
  .dots { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--divider-color); cursor: pointer; }
  .dot.on { background: var(--primary-color); }
`;

/**
 * browser_mod and card-tools load the @webcomponents/scoped-custom-element-registry
 * polyfill, which swaps window.customElements and window.HTMLElement. Anything defined
 * in the old registry is then unknown to HA ("Custom element doesn't exist"), and a
 * class extending the old HTMLElement is refused by the new one. So build the class
 * from the live globals and register again whenever the registry may have changed.
 */
const define = () => {
  const registry = window.customElements;
  if (registry && !registry.get(TAG)) registry.define(TAG, createCardClass(window.HTMLElement));
};
const retry = () => {
  try {
    define();
  } catch (_) {
    // A swap in the middle of a pass; the next one settles it.
  }
};

define();
[250, 1000, 2000, 4000, 8000, 15000, 30000, 60000].forEach((ms) => setTimeout(retry, ms));
window.addEventListener("location-changed", retry);
document.addEventListener("visibilitychange", retry);

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === TAG)) {
  window.customCards.push({
    type: TAG,
    name: "Fediverse Feed",
    description: "Top pictures from a Lemmy community, a Mastodon hashtag or a Pixelfed feed",
    preview: true,
    documentationURL: "https://github.com/DevHovAI/fediverse-feed",
  });
}
console.info(`%c FEDIVERSE-FEED-CARD %c ${VERSION} `, "color:#fff;background:#6364ff", "");
