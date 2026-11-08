# Stock Screener Dashboard

A small Python script that runs every morning, pulls market data and builds a one-page HTML dashboard.

- **US stocks** (Finnhub API): price, analyst consensus and 13-week momentum, combined into a 0–100 signal score (60% analyst consensus, 40% momentum).
- **BIST, metals and USD/TRY** (Yahoo Finance): 1-year daily closes and summary returns.
- Every run appends to a daily history file, so scores can be compared over time.
- Scheduled with Windows Task Scheduler (09:00 daily).

Standard library only, no pip install needed.

## Usage

```
echo YOUR_FINNHUB_KEY > api_key.txt
python takip.py          # fetch data, update history, open dashboard.html
python takip.py --html   # rebuild the page from the last data
python takip.py --test   # scoring self-test, no API calls
```

Tickers are set in `config.json`. This is a personal learning project, not investment advice.
