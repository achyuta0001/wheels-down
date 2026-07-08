#!/usr/bin/env python3
"""
Flight arrival notifier.
Polls OpenSky Network for live flight position, calculates ETA,
and sends an email when the flight is within LEAD_TIME_MINUTES of landing.

Usage (local test):  python check_flight.py --test
GitHub Actions:      runs via env vars set in repo variables/secrets
"""

import json
import math
import os
import smtplib
import sys
import urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText

AIRPORTS_FILE = os.path.join(os.path.dirname(__file__), "airports.json")
OPENSKY_URL = "https://opensky-network.org/api/states/all?callsign={callsign}"

# IATA airline prefix → ICAO callsign prefix.
# OpenSky tracks by ICAO callsign, not the public flight number.
# e.g. IndiGo's public code is "6E" but OpenSky sees "IGO107" for flight 6E107.
IATA_TO_ICAO = {
    "6E": "IGO",   # IndiGo
    "AI": "AIC",   # Air India
    "IX": "AXB",   # Air India Express
    "SG": "SEJ",   # SpiceJet
    "UK": "VTI",   # Vistara (now Air India)
    "G8": "GOW",   # Go First (defunct but may appear in data)
    "QP": "ABW",   # Akasa Air
    "EK": "UAE",   # Emirates
    "QR": "QTR",   # Qatar Airways
    "EY": "ETD",   # Etihad
    "BA": "BAW",   # British Airways
    "LH": "DLH",   # Lufthansa
}

# State vector field positions from OpenSky docs
IDX_CALLSIGN       = 1
IDX_LON            = 5
IDX_LAT            = 6
IDX_BARO_ALTITUDE  = 7
IDX_ON_GROUND      = 8
IDX_VELOCITY       = 9   # m/s
IDX_VERTICAL_RATE  = 11  # m/s, negative = descending


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def load_airports():
    with open(AIRPORTS_FILE) as f:
        return json.load(f)


def to_icao_callsign(flight_number: str) -> str:
    """Convert a public flight number (e.g. '6E107') to its OpenSky ICAO callsign ('IGO107')."""
    flight_number = flight_number.strip().upper()
    for iata_prefix, icao_prefix in IATA_TO_ICAO.items():
        if flight_number.startswith(iata_prefix):
            return icao_prefix + flight_number[len(iata_prefix):]
    return flight_number  # already ICAO, or unknown airline


def find_aircraft(flight_number: str):
    """Return the first matching state vector for a callsign, or None."""
    icao_callsign = to_icao_callsign(flight_number)
    if icao_callsign != flight_number.upper():
        print(f"  Mapped {flight_number.upper()} → OpenSky callsign {icao_callsign}")

    url = OPENSKY_URL.format(callsign=icao_callsign)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "flight-notifier/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"OpenSky request failed: {e}")
        return None

    states = data.get("states") or []
    for sv in states:
        if sv[IDX_CALLSIGN] and sv[IDX_CALLSIGN].strip().upper() == icao_callsign.upper():
            return sv
    return None


def eta_minutes(lat, lon, speed_ms, dest_icao, airports):
    if speed_ms is None or speed_ms < 1:
        return None
    airport = airports.get(dest_icao.upper())
    if not airport:
        print(f"Unknown airport ICAO: {dest_icao}. Add it to airports.json.")
        return None
    dist_km = haversine_km(lat, lon, airport["lat"], airport["lon"])
    speed_kmh = speed_ms * 3.6
    return (dist_km / speed_kmh) * 60  # minutes


def send_email(gmail_user, gmail_app_password, dad_email, message_body, subject):
    msg = MIMEText(message_body)
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = dad_email
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_user, gmail_app_password)
        server.send_message(msg)
    print(f"Email sent to {dad_email}")


def set_gha_output(key, value):
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{key}={value}\n")
    else:
        print(f"::set-output name={key}::{value}")  # fallback


def main():
    test_mode = "--test" in sys.argv

    flight_number    = os.environ.get("FLIGHT_NUMBER", "").strip()
    arrival_airport  = os.environ.get("ARRIVAL_AIRPORT", "").strip()
    dad_email        = os.environ.get("DAD_EMAIL", "").strip()
    gmail_user       = os.environ.get("GMAIL_USER", "").strip()
    gmail_password   = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    already_notified = os.environ.get("NOTIFIED", "false").strip().lower() == "true"
    lead_time        = int(os.environ.get("LEAD_TIME_MINUTES", "65"))

    if not all([flight_number, arrival_airport, dad_email, gmail_user, gmail_password]):
        print("Missing required env vars. See README.")
        sys.exit(1)

    if already_notified and not test_mode:
        print("Already notified for this flight. Nothing to do.")
        return

    airports = load_airports()

    if test_mode:
        print(f"[TEST MODE] Sending test email to {dad_email}...")
        airport_name = airports.get(arrival_airport, {}).get("name", arrival_airport)
        send_email(
            gmail_user, gmail_password, dad_email,
            f"This is a test notification.\n\nWhen real: Achyuta lands at {airport_name} soon. Leave to pick them up!",
            f"[TEST] Flight Notifier — {flight_number}"
        )
        return

    print(f"Checking flight {flight_number} → {arrival_airport}...")
    state = find_aircraft(flight_number)

    if state is None:
        print("Flight not found on OpenSky. May not be airborne yet, or already landed.")
        return

    lat            = state[IDX_LAT]
    lon            = state[IDX_LON]
    altitude_m     = state[IDX_BARO_ALTITUDE]
    on_ground      = state[IDX_ON_GROUND]
    velocity_ms    = state[IDX_VELOCITY]
    vertical_rate  = state[IDX_VERTICAL_RATE]

    print(f"  Position: {lat:.4f}, {lon:.4f}  |  Alt: {altitude_m}m  |  Speed: {velocity_ms}m/s  |  V-rate: {vertical_rate}m/s")

    if on_ground:
        print("Aircraft is on the ground. Already landed or not yet departed.")
        return

    if altitude_m and altitude_m > 4000 and vertical_rate and vertical_rate > 0:
        print("Aircraft is still climbing/cruising. Too early to notify.")
        return

    minutes = eta_minutes(lat, lon, velocity_ms, arrival_airport, airports)
    if minutes is None:
        print("Could not calculate ETA.")
        return

    print(f"  ETA to {arrival_airport}: {minutes:.0f} minutes")

    if minutes <= lead_time:
        now_utc = datetime.now(timezone.utc)
        landing_time = datetime.fromtimestamp(
            now_utc.timestamp() + minutes * 60,
            tz=timezone.utc
        )
        airport_info = airports.get(arrival_airport.upper(), {})
        airport_name = airport_info.get("name", arrival_airport)
        iata = airport_info.get("iata", arrival_airport)
        landing_str = landing_time.strftime("%H:%M UTC")

        body = (
            f"Hi,\n\n"
            f"Achyuta's flight {flight_number} is about {minutes:.0f} minutes from landing.\n\n"
            f"Estimated landing: {landing_str} at {airport_name} ({iata})\n\n"
            f"Please leave now to pick them up!\n\n"
            f"— Flight Notifier"
        )
        subject = f"Leave now! {flight_number} lands at {iata} in ~{minutes:.0f} min"

        send_email(gmail_user, gmail_password, dad_email, body, subject)
        set_gha_output("should_notify", "true")
    else:
        print(f"  ETA is {minutes:.0f} min — more than {lead_time} min threshold. Waiting.")


if __name__ == "__main__":
    main()
