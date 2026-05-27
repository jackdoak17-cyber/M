# OddsSearch Weekly Roundup Preview

Standalone mock email preview for the OddsSearch Weekly Roundup + Preview workflow.

Open locally:

```bash
open /Users/jackdoak/M/weekly_roundup_preview/index.html
```

Purpose:

- Keep marketing workflow previews out of the product website repo.
- Use mock data while live football/odds data is unavailable.
- Iterate email layout safely before wiring it to real data.

Later this can be connected to generated JSON from OddsSearch/JXD/Models and rendered into email HTML or screenshots.

## Resend Preview Send

This repo includes a send-preview script that can email the current mock HTML through Resend once you have an account and API key.

Add these values to `.env.local`:

```bash
RESEND_API_KEY=re_...
RESEND_FROM=OddsSearch <weekly@updates.yourdomain.com>
RESEND_NEWSLETTER_FROM=OddsSearch <weekly@updates.yourdomain.com>
RESEND_PREVIEW_TO=you@example.com
ODDSSEARCH_PUBLIC_URL=https://oddssearch.co.uk
NEWSLETTER_UNSUBSCRIBE_URL=https://oddssearch.co.uk/unsubscribe
```

Dry-run the payload without sending:

```bash
python3 -m src.marketing_email.send_weekly_roundup_preview
```

Send one preview email:

```bash
python3 -m src.marketing_email.send_weekly_roundup_preview --send
```

The script sends `weekly_roundup_preview/index.html`, replaces the mock `Sign up` link with `${ODDSSEARCH_PUBLIC_URL}/signup`, and sends only to `RESEND_PREVIEW_TO`.

## Weekly Newsletter Send

The newsletter sender reads an explicit opt-in CSV. It will not pull every website account automatically.

Create the local subscriber file:

```bash
cp data/newsletter_subscribers.example.csv data/newsletter_subscribers.csv
```

Edit `data/newsletter_subscribers.csv` and keep only people who have opted in. Required columns:

- `email`
- `status`, set to `subscribed`

Recommended columns:

- `first_name`
- `source`
- `consent_date`
- `unsubscribe_url`

Dry-run the list:

```bash
python3 -m src.marketing_email.send_weekly_roundup_newsletter
```

Send to one recipient first:

```bash
python3 -m src.marketing_email.send_weekly_roundup_newsletter --send --limit 1
```

Send to every subscribed recipient:

```bash
python3 -m src.marketing_email.send_weekly_roundup_newsletter --send
```

Live sends require an unsubscribe URL in the CSV or `NEWSLETTER_UNSUBSCRIBE_URL` in `.env.local`.
