import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from flask import Flask, render_template
from functools import lru_cache

app = Flask(__name__)

# FRED API key (hardcoded for convenience)
FRED_API_KEY = "4bfa7711b674526e81033245cc15c439"
if not FRED_API_KEY:
    raise ValueError("FRED_API_KEY must be set")

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

INDICATORS = {
    "GDP": {"name": "Nominal GDP (Billions $)", "series_id": "GDP"},
    "UNRATE": {"name": "Unemployment Rate (%)", "series_id": "UNRATE"},
    "CPI": {"name": "CPI (Index)", "series_id": "CPIAUCSL"},
    "FEDFUNDS": {"name": "Federal Funds Rate (%)", "series_id": "FEDFUNDS"},
    "SP500": {"name": "S&P 500 Index", "series_id": "SP500"}
}

TREASURY_YIELDS = {
    "DGS1MO": {"name": "1-Month Treasury", "series_id": "DGS1MO", "maturity": 1/12},
    "DGS3MO": {"name": "3-Month Treasury", "series_id": "DGS3MO", "maturity": 0.25},
    "DGS6MO": {"name": "6-Month Treasury", "series_id": "DGS6MO", "maturity": 0.5},
    "DGS1": {"name": "1-Year Treasury", "series_id": "DGS1", "maturity": 1},
    "DGS2": {"name": "2-Year Treasury", "series_id": "DGS2", "maturity": 2},
    "DGS5": {"name": "5-Year Treasury", "series_id": "DGS5", "maturity": 5},
    "DGS10": {"name": "10-Year Treasury", "series_id": "DGS10", "maturity": 10},
    "DGS30": {"name": "30-Year Treasury", "series_id": "DGS30", "maturity": 30}
}


def get_cache_key():
    """Generate cache key that changes every hour"""
    return datetime.now().strftime("%Y-%m-%d-%H")


@lru_cache(maxsize=128)
def fetch_fred_data_cached(series_id, cache_key):
    """Fetch data from FRED API with caching"""
    # For S&P 500, fetch full historical data
    observation_start = "1871-01-01" if series_id == "SP500" else None

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json"
    }
    if observation_start:
        params["observation_start"] = observation_start

    try:
        resp = requests.get(FRED_BASE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        app.logger.error("Error fetching data for %s: %s", series_id, e)
        return pd.DataFrame(columns=["date", "value"])
    except Exception as e:
        app.logger.error("Error parsing JSON for %s: %s", series_id, e)
        return pd.DataFrame(columns=["date", "value"])

    if "observations" not in data:
        app.logger.warning("Observations missing for %s: %s", series_id, data.keys())
        return pd.DataFrame(columns=["date", "value"])

    df = pd.DataFrame(data["observations"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date", ascending=False).reset_index(drop=True)
    df["value"] = df["value"].where(pd.notna(df["value"]), None)
    return df


def fetch_fred_data(series_id, full_history=False):
    """Wrapper for cached fetch with optional full history"""
    cache_key = "full_" + series_id if full_history else get_cache_key()
    return fetch_fred_data_cached(series_id, cache_key)


def get_data(key):
    """Get indicator data as list of (date, value) tuples"""
    info = INDICATORS.get(key)
    if not info:
        return []
    df = fetch_fred_data(info["series_id"], full_history=(key=="SP500"))
    if df.empty:
        return []
    return list(zip(df["date"].dt.strftime("%Y-%m-%d"), df["value"]))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    summary = []
    for key, info in INDICATORS.items():
        df = fetch_fred_data(info["series_id"], full_history=(key=="SP500"))
        if not df.empty:
            latest = df.iloc[0]
            previous = df.iloc[1] if len(df) > 1 else None
            change = pct_change = trend = None
            if previous is not None and latest["value"] is not None and previous["value"] is not None:
                change = latest["value"] - previous["value"]
                pct_change = (change / previous["value"]) * 100
                trend = "up" if change > 0 else "down" if change < 0 else "stable"
            summary.append({
                "key": key,
                "name": info["name"],
                "current": latest["value"],
                "date": latest["date"].strftime("%Y-%m-%d") if latest["value"] is not None else "N/A",
                "change": change,
                "pct_change": pct_change,
                "trend": trend
            })

    # Yield curve data
    yield_curve_data = []
    for key, info in TREASURY_YIELDS.items():
        df = fetch_fred_data(info["series_id"])
        if not df.empty and df.iloc[0]["value"] is not None:
            yield_curve_data.append({
                "maturity": info["maturity"],
                "maturity_name": info["name"],
                "yield": df.iloc[0]["value"]
            })
    yield_curve_data.sort(key=lambda x: x["maturity"])

    # 2y / 10y spread
    dgs2 = fetch_fred_data("DGS2")
    dgs10 = fetch_fred_data("DGS10")
    is_inverted = False
    spread_2_10 = None
    if (not dgs2.empty) and (not dgs10.empty):
        r2 = dgs2.iloc[0]["value"]
        r10 = dgs10.iloc[0]["value"]
        if r2 is not None and r10 is not None:
            spread_2_10 = r10 - r2
            is_inverted = spread_2_10 < 0

    return render_template("dashboard.html", summary=summary,
                           yield_curve_data=yield_curve_data,
                           is_inverted=is_inverted, spread_2_10=spread_2_10)


@app.route("/gdp")
def gdp():
    return render_template("indicator.html",
                           indicator=INDICATORS["GDP"]["name"],
                           rows=get_data("GDP"))


@app.route("/unemployment")
def unemployment():
    return render_template("indicator.html",
                           indicator=INDICATORS["UNRATE"]["name"],
                           rows=get_data("UNRATE"))


@app.route("/cpi")
def cpi():
    return render_template("indicator.html",
                           indicator=INDICATORS["CPI"]["name"],
                           rows=get_data("CPI"))


@app.route("/fedfunds")
def fedfunds():
    return render_template("indicator.html",
                           indicator=INDICATORS["FEDFUNDS"]["name"],
                           rows=get_data("FEDFUNDS"))


@app.route("/sp500")
def sp500():
    df = fetch_fred_data("SP500", full_history=True)
    rows = [] if df.empty else list(zip(df["date"].dt.strftime("%Y-%m-%d"), df["value"]))
    return render_template("indicator.html",
                           indicator=INDICATORS["SP500"]["name"],
                           rows=rows)


@app.route("/yield-curve")
def yield_curve():
    treasury_data = {}
    for key, info in TREASURY_YIELDS.items():
        df = fetch_fred_data(info["series_id"])
        if not df.empty:
            treasury_data[key] = {
                "name": info["name"],
                "maturity": info["maturity"],
                "current": df.iloc[0]["value"],
                "date": df.iloc[0]["date"].strftime("%Y-%m-%d"),
                "historical": list(zip(df["date"].dt.strftime("%Y-%m-%d"), df["value"]))
            }

    sorted_treasuries = sorted(treasury_data.items(), key=lambda x: x[1]["maturity"])

    # 2y/10y spread
    is_inverted = False
    spread_2_10 = None
    if "DGS2" in treasury_data and "DGS10" in treasury_data:
        r2 = treasury_data["DGS2"]["current"]
        r10 = treasury_data["DGS10"]["current"]
        if r2 is not None and r10 is not None:
            spread_2_10 = r10 - r2
            is_inverted = spread_2_10 < 0

    return render_template("yield_curve.html", treasuries=sorted_treasuries,
                           is_inverted=is_inverted, spread_2_10=spread_2_10)


@app.route("/compare")
def compare():
    return render_template(
        "compare.html",
        gdp=get_data("GDP"),
        unrate=get_data("UNRATE"),
        cpi=get_data("CPI"),
        fedfunds=get_data("FEDFUNDS"),
        sp500=get_data("SP500"),
        indicators=INDICATORS
    )


@app.route("/calendar")
def calendar():
    today = datetime.now()

    fed_meetings = [
        {"date": "2024-12-17", "type": "FOMC Meeting", "description": "Federal Reserve interest rate decision"},
        {"date": "2024-12-18", "type": "FOMC Press Conference", "description": "Fed Chair press conference"},
        {"date": "2025-01-28", "type": "FOMC Meeting", "description": "Federal Reserve interest rate decision"},
        {"date": "2025-01-29", "type": "FOMC Press Conference", "description": "Fed Chair press conference"},
        {"date": "2025-03-18", "type": "FOMC Meeting", "description": "Federal Reserve interest rate decision"},
        {"date": "2025-03-19", "type": "FOMC Press Conference", "description": "Fed Chair press conference"},
    ]

    economic_releases = [
        {"name": "Employment Situation (Jobs Report)", "frequency": "First Friday of each month", "description": "Unemployment rate, non-farm payrolls, wage growth", "importance": "High", "color": "#f44336"},
        {"name": "Consumer Price Index (CPI)", "frequency": "Mid-month (around 13th)", "description": "Inflation data - changes in consumer prices", "importance": "High", "color": "#ff9800"},
        {"name": "Retail Sales", "frequency": "Mid-month", "description": "Consumer spending at retail stores", "importance": "Medium", "color": "#2196f3"},
        {"name": "GDP Report", "frequency": "End of each quarter", "description": "Total economic output and growth rate", "importance": "High", "color": "#4caf50"},
    ]

    # Filter upcoming Fed meetings (next 180 days)
    upcoming_fed = []
    for meeting in fed_meetings:
        meeting_date = datetime.strptime(meeting["date"], "%Y-%m-%d")
        if today <= meeting_date <= (today + timedelta(days=180)):
            meeting["days_until"] = (meeting_date - today).days
            meeting["date_obj"] = meeting_date
            upcoming_fed.append(meeting)
    upcoming_fed.sort(key=lambda x: x["date_obj"])

    return render_template("calendar.html", fed_meetings=upcoming_fed,
                           economic_releases=economic_releases)


# Error handlers
@app.errorhandler(404)
def not_found(e):
    return render_template("index.html"), 404


@app.errorhandler(500)
def server_error(e):
    app.logger.error("Server error: %s", e)
    return render_template("index.html"), 500


if __name__ == "__main__":
    app.run(debug=True)
