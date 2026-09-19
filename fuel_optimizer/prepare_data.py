import os
import json
import requests
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, "documemnts", "fuel-prices-for-be-assessment.csv")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_JSON = os.path.join(DATA_DIR, "fuel_stations.json")
CITIES_CACHE = os.path.join(DATA_DIR, "us_cities.csv")

US_CITIES_URL = "https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv"

CITY_OVERRIDES = {
    ("PORT WENTWORTH", "GA"): (32.1494, -81.1632),
    ("ELIZABETHPORT", "NJ"): (40.6559, -74.1957),
    ("BROOKPARK", "OH"): (41.3981, -81.8257),
    ("EVERGREEN", "AL"): (31.4338, -86.9541),
    ("HENRICO", "VA"): (37.5385, -77.3486),
    ("UNIVERSITY PARK", "IL"): (41.4442, -87.6898),
}

def ensure_us_cities_csv():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CITIES_CACHE):
        print(f"Downloading US cities reference dataset from {US_CITIES_URL}...")
        resp = requests.get(US_CITIES_URL, timeout=30)
        resp.raise_for_status()
        with open(CITIES_CACHE, "wb") as f:
            f.write(resp.content)
        print("US cities dataset cached successfully.")
    return CITIES_CACHE

def build_fuel_stations_dataset():
    ensure_us_cities_csv()
    
    print("Loading datasets...")
    df_fuel = pd.read_csv(CSV_PATH)
    df_cities = pd.read_csv(CITIES_CACHE)
    
    df_fuel["City_clean"] = df_fuel["City"].astype(str).str.strip().str.upper()
    df_fuel["State_clean"] = df_fuel["State"].astype(str).str.strip().str.upper()
    
    df_cities["City_clean"] = df_cities["CITY"].astype(str).str.strip().str.upper()
    df_cities["State_clean"] = df_cities["STATE_CODE"].astype(str).str.strip().str.upper()
    df_cities_dedup = df_cities.drop_duplicates(subset=["City_clean", "State_clean"])
    
    merged = pd.merge(df_fuel, df_cities_dedup, on=["City_clean", "State_clean"], how="left")
    
    for (city, state), (lat, lon) in CITY_OVERRIDES.items():
        mask = (merged["City_clean"] == city) & (merged["State_clean"] == state)
        merged.loc[mask, "LATITUDE"] = lat
        merged.loc[mask, "LONGITUDE"] = lon
    
    us_states = set(df_cities["State_clean"].unique())
    us_stations = merged[
        merged["State_clean"].isin(us_states) & 
        merged["LATITUDE"].notna() & 
        merged["LONGITUDE"].notna() & 
        (merged["Retail Price"] > 0)
    ].copy()
    
    records = []
    for _, row in us_stations.iterrows():
        records.append({
            "id": int(row["OPIS Truckstop ID"]),
            "name": str(row["Truckstop Name"]).strip(),
            "address": str(row["Address"]).strip(),
            "city": str(row["City"]).strip(),
            "state": str(row["State"]).strip(),
            "rack_id": int(row["Rack ID"]),
            "price": round(float(row["Retail Price"]), 4),
            "lat": round(float(row["LATITUDE"]), 6),
            "lon": round(float(row["LONGITUDE"]), 6),
        })
    
    print(f"Total valid US fuel stations: {len(records)}")
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    print(f"Saved to {OUTPUT_JSON}")
    return records

if __name__ == "__main__":
    build_fuel_stations_dataset()
