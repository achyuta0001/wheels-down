# Flight Arrival Notifier

Sends your dad an email ~1 hour before you land. Uses real-time flight tracking (OpenSky), GitHub Actions for scheduling, and Gmail for delivery. **Zero cost.**

## One-time setup

### 1. Create a Gmail App Password
1. Go to [Google Account](https://myaccount.google.com) → Security
2. Turn on 2-Step Verification if not already on
3. Search "App Passwords" → create one named "flight-notifier"
4. Copy the 16-character password (you won't see it again)

### 2. Push this repo to GitHub (private)
```bash
cd wheels-down
git init
git add .
git commit -m "init"
gh repo create wheels-down --private --source=. --push
```

### 3. Add Secrets (Settings → Secrets and variables → Actions → Secrets)
| Name | Value |
|---|---|
| `DAD_EMAIL` | dad's email address |
| `GMAIL_USER` | your Gmail address |
| `GMAIL_APP_PASSWORD` | the 16-char app password from step 1 |

### 4. Add Variables (Settings → Secrets and variables → Actions → Variables)
| Name | Default | Notes |
|---|---|---|
| `FLIGHT_NUMBER` | *(set per flight)* | e.g. `AI302` |
| `ARRIVAL_AIRPORT` | *(set per flight)* | ICAO code e.g. `VOBL` for Bengaluru |
| `NOTIFIED` | `false` | reset to `false` before each flight |
| `LEAD_TIME_MINUTES` | `65` | minutes before landing to send alert |

### 5. Test email delivery
```bash
FLIGHT_NUMBER=AI302 ARRIVAL_AIRPORT=VOBL NOTIFIED=false \
DAD_EMAIL=dad@example.com GMAIL_USER=you@gmail.com GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx" \
python check_flight.py --test
```

---

## Before every flight (30 seconds)

```bash
gh variable set FLIGHT_NUMBER --body "AI302"
gh variable set ARRIVAL_AIRPORT --body "VOBL"
gh variable set NOTIFIED --body "false"
```

Or update them in the GitHub UI: repo → Settings → Secrets and variables → Variables.

That's it. The workflow runs every 15 minutes automatically and sends one email when you're ~65 minutes out.

---

## Supported airports

See `airports.json`. To add a new airport, find its ICAO code and coordinates and add an entry:
```json
"VIGO": { "name": "My Airport", "iata": "XYZ", "lat": 12.345, "lon": 67.890 }
```

---

## How the ETA is calculated

1. OpenSky returns the aircraft's live latitude, longitude, and ground speed (in m/s).
2. The script calculates the straight-line (haversine) distance from the current position to the destination airport.
3. ETA = distance / speed. This is accurate to within a few minutes for final approach.
4. The script also checks vertical rate — if the aircraft is still climbing, it waits.

## Troubleshooting

**Flight not found on OpenSky**: OpenSky relies on community ADS-B receivers. Coverage is excellent over Europe, North America, and major Indian airports. Remote routes may have gaps. The workflow will just skip that run and retry in 15 minutes.

**Already notified**: If you need to re-send, set `NOTIFIED=false` in repo variables.

**GitHub Actions schedule lag**: GitHub's `*/15 * * * *` cron can have up to 15 minutes of delay under heavy load. For critical timing, trigger manually via `workflow_dispatch` in the Actions tab.
