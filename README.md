# M

This repo contains two automated workflows:

1) Premier League prop sheets and weekend player posts (text outputs in `output/`)
2) A multi-league prop betting bot that generates top 10 value picks (JSON in `picks/`)

## Local Setup

Create a `.env.local` (or export env vars) with:

```
SUPABASE_DB_URL=postgresql://...
ANTHROPIC_API_KEY=...
```

Optional:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
PROP_INCLUDE_SIMILAR=0
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

## GitHub Actions

`Generate Premier League Prop Sheets` runs the existing prop sheets workflow.  
`Daily Prop Picks` generates JSON picks daily.  
`Check Prop Results` updates results once fixtures complete.
