# Deploying narrator.guru on a VPS

One server runs everything: Caddy (HTTPS), the web app, and the narrator, all through Docker Compose. Data (SQLite database, uploads, finished audiobooks) lives in `./data` next to the code.

## 1. Server

- Any Linux VPS with Docker. Narration is the heavy part: more CPU cores means faster books. Measure it (step 6) and set `NARRATION_SPEED`.
- Open ports 80 and 443 only (plus SSH).
- Install Docker: `curl -fsSL https://get.docker.com | sh`

## 2. Domain

Point an `A` record (and `AAAA` for IPv6) for `narrator.guru` and `www.narrator.guru` at the server. Caddy gets the HTTPS certificate on first start, once DNS resolves.

## 3. Code and settings

```sh
git clone https://github.com/CarlosVitorino/ebook-to-audiobook-web-converter.git narrator
cd narrator
cp .env.example .env
```

Edit `.env`. For launch, at least:

| Setting | Value |
|---|---|
| `BASE_URL` | `https://narrator.guru` |
| `DOMAIN` | `narrator.guru` |
| `SECRET_KEY` | `openssl rand -hex 32` |
| `STATS_PASSWORD` | anything long |
| `GOOGLE_CLIENT_ID/SECRET` | Google Cloud Console → OAuth client (Web). Redirect URI: `https://narrator.guru/signin/google/callback` |
| `SMTP_*`, `MAIL_FROM` | from your email provider (Resend, Postmark…). Set up SPF/DKIM for the domain as the provider explains, or sign-in emails land in spam |
| `CREEM_*` | see step 5 |
| `LEGAL_OWNER`, `LEGAL_LAW` | your legal name/company and country; the legal pages say "Draft" until set |
| `NARRATION_SPEED` | measured in step 6 |

## 4. Start

```sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The first build downloads the voice model (~350 MB). Then open https://narrator.guru.

Update later with `git pull` and the same command. The narrator runs as its own service, so redeploying the web app doesn't interrupt a book. Rebuilding the `worker` service does: a book in progress starts again from the beginning when the worker comes back.

Logs: `docker compose logs -f web worker`.

## 5. Payments (Creem)

1. Test mode first. In Creem (Test Mode on), create three **one-time** products: 1 book €2.99, 5 books €9.95, 15 books €24.95.
2. Developers → API key → `CREEM_API_KEY`. Product IDs → `CREEM_PRODUCT_ONE/FIVE/FIFTEEN`. The app talks to the test API because test keys start with `creem_test_`.
3. Developers → Webhooks → add `https://narrator.guru/webhooks/creem` → copy its secret into `CREEM_WEBHOOK_SECRET`.
4. Restart, buy a pack with Creem's test card, check `/stats`.
5. Going live: submit the store for Creem's review (it checks the site, the product description and the Terms/Privacy/Refunds pages). After approval, repeat 1–3 in live mode: live API key, the three live product IDs and a live webhook with its own secret. All five values change; the API address follows the key.

## 6. Measure the speed

Convert a real book, then open `/stats` (password from `STATS_PASSWORD`). "Speed" shows how many times faster than real time the server narrates. Put that number in `NARRATION_SPEED` and restart; the confirm page's "ready in about" uses it. If the landing page's Gatsby line ("about 40 minutes for … 4 hours", about 6×) doesn't match, tell Claude to change it.

## 7. Backups

The database holds accounts and purchases. Back it up daily:

```sh
crontab -e
# add:
15 3 * * * cd /root/narrator && docker compose exec -T web python -m app.backup >> data/backup.log 2>&1
```

That keeps 14 daily copies in `data/backups/`. Copy them off the server too, for example with Hetzner's automatic server backups or a Storage Box. Audiobooks themselves don't need backups: they're deleted after 7 days anyway.

## 8. Search engines

The site already serves `robots.txt`, `sitemap.xml`, `llms.txt` (for AI assistants), page descriptions, social-share cards and schema.org data (product, prices, FAQ). After launch:

1. [Google Search Console](https://search.google.com/search-console): add `narrator.guru` (DNS verification), then submit `https://narrator.guru/sitemap.xml`.
2. [Bing Webmaster Tools](https://www.bing.com/webmasters): import from Google Search Console. Bing also feeds ChatGPT search and Copilot.
3. Check the structured data with Google's [Rich Results Test](https://search.google.com/test/rich-results) and a share preview with [opengraph.xyz](https://www.opengraph.xyz/).

## 9. Before you announce it

- [ ] HTTPS works, `www.` redirects
- [ ] Google sign-in and email sign-in both work (check the email isn't in spam)
- [ ] A real book converts; the "ready" email arrives; downloads play in Apple Books / a podcast app
- [ ] `/stats` asks for the password
- [ ] Legal pages show your name and country, no "Draft"
- [ ] Creem test purchase adds books; then live mode after review
