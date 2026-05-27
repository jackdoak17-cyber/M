# M

This repo contains two automated workflows:

1) Premier League prop sheets and weekend player posts (text outputs in `output/`)
2) A multi-league prop betting bot that generates top 10 value picks (JSON in `picks/`)
3) A Polymarket tracker for selected markets (JSON + markdown snapshots in `output/polymarket/`)

## Local Setup

Create a `.env.local` (or export env vars) with:

```
SUPABASE_DB_URL=postgresql://...
ANTHROPIC_API_KEY=...
PROP_MIN_APPEARANCES=5
```

Optional:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
PROP_INCLUDE_SIMILAR=1
POLYMARKET_GAMMA_BASE_URL=https://gamma-api.polymarket.com
RESEND_API_KEY=...
RESEND_FROM=OddsSearch <weekly@updates.yourdomain.com>
RESEND_NEWSLETTER_FROM=OddsSearch <weekly@updates.yourdomain.com>
RESEND_PREVIEW_TO=you@example.com
NEWSLETTER_UNSUBSCRIBE_URL=https://oddssearch.co.uk/unsubscribe
```

Temporary availability overrides:

```
# manual_player_exclusions.txt
5666458,2026-03-01,2026-03-08 # temporary suspension override
```

Install dependencies:

```
pip install -r requirements.txt
```

## Run Prop Sheets (Existing)

```
python -m src.main --output-dir output
```

## Run Prop Bot (New)

Generate picks:

```
python -m src.prop_bot.main
```

Check results:

```
python -m src.prop_bot.check_results
```

## Run Polymarket Tracker

Track selected markets (excluding EPL Top Goalscorer) and write snapshots:

```
python -m src.polymarket_tracker
```

Generate a midweek-style post block with custom wording:

```
python -m src.polymarket_tracker --window-label "after this weekend"
```

Artifacts:

- `output/polymarket/snapshots/{date}_snapshot.json`
- `output/polymarket/snapshots/latest.json`
- `output/polymarket/tracker/{date}_tracker.md`
- `output/polymarket/tracker/{date}_midweek_posts.txt`

## Run Polymarket Weekly Posts

Generate Tuesday posts and update weekly baseline:

```
python -m src.polymarket_posts --generate
```

Preview posts without updating baseline:

```
python -m src.polymarket_posts --preview
```

Force a specific baseline file:

```
python -m src.polymarket_posts --generate --baseline output/polymarket/weekly_baseline.json
```

Artifacts:

- `output/polymarket/weekly/{date}_market_watch.txt`
- `output/polymarket/weekly/{date}_biggest_mover_*.txt` (if triggered)
- `output/polymarket/weekly/{date}_summary.json`
- `output/polymarket/weekly_baseline.json`

## Preview Weekly Roundup Email

Open the static mock email preview:

```
open /Users/jackdoak/M/weekly_roundup_preview/index.html
```

Dry-run the Resend payload:

```
python3 -m src.marketing_email.send_weekly_roundup_preview
```

Send one preview email through Resend:

```
python3 -m src.marketing_email.send_weekly_roundup_preview --send
```

The send command requires `RESEND_API_KEY`, `RESEND_FROM`, and `RESEND_PREVIEW_TO` in `.env.local` or your shell environment.

Dry-run the opt-in newsletter list:

```
cp data/newsletter_subscribers.example.csv data/newsletter_subscribers.csv
python3 -m src.marketing_email.send_weekly_roundup_newsletter
```

Send to the first recipient only:

```
python3 -m src.marketing_email.send_weekly_roundup_newsletter --send --limit 1
```

Send to all `status=subscribed` rows in `data/newsletter_subscribers.csv`:

```
python3 -m src.marketing_email.send_weekly_roundup_newsletter --send
```

Only add people to `data/newsletter_subscribers.csv` if they have explicitly opted in to receive weekly OddsSearch emails. The live newsletter sender requires an unsubscribe URL before it will send.

## GitHub Actions

`Generate Premier League Prop Sheets` runs the existing prop sheets workflow.  
`Daily Prop Picks` generates JSON picks daily.  
`Check Prop Results` updates results once fixtures complete.
`Track Polymarket Markets` snapshots selected Polymarket probabilities every 6 hours.
`Generate Polymarket Weekly Posts` builds Tuesday-ready post copy and updates weekly baseline.
