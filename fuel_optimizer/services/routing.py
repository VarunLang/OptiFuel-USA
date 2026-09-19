import os
import re
import requests
from typing import Dict, Any, Tuple, Optional

OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "http://router.project-osrm.org/route/v1/driving").rstrip("/")
NOMINATIM_BASE_URL = os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org/search")
NOMINATIM_USER_AGENT = os.getenv("NOMINATIM_USER_AGENT", "OptiFuelUSA/1.0 (contact: admin@fuelrouteoptimizer.local)")

_GEOCODE_CACHE: Dict[str, Tuple[float, float, str]] = {
    "new york": (40.712728, -74.006015, "New York, NY, USA"),
    "new york, ny": (40.712728, -74.006015, "New York, NY, USA"),
    "los angeles": (34.053691, -118.242766, "Los Angeles, CA, USA"),
    "los angeles, ca": (34.053691, -118.242766, "Los Angeles, CA, USA"),
    "chicago": (41.875562, -87.624421, "Chicago, IL, USA"),
    "chicago, il": (41.875562, -87.624421, "Chicago, IL, USA"),
    "houston": (29.758938, -95.367697, "Houston, TX, USA"),
    "houston, tx": (29.758938, -95.367697, "Houston, TX, USA"),
    "dallas": (32.776272, -96.796856, "Dallas, TX, USA"),
    "dallas, tx": (32.776272, -96.796856, "Dallas, TX, USA"),
    "miami": (25.774173, -80.193620, "Miami, FL, USA"),
    "miami, fl": (25.774173, -80.193620, "Miami, FL, USA"),
    "seattle": (47.603832, -122.330062, "Seattle, WA, USA"),
    "seattle, wa": (47.603832, -122.330062, "Seattle, WA, USA"),
    "san francisco": (37.779026, -122.419906, "San Francisco, CA, USA"),
    "san francisco, ca": (37.779026, -122.419906, "San Francisco, CA, USA"),
    "atlanta": (33.748992, -84.390264, "Atlanta, GA, USA"),
    "atlanta, ga": (33.748992, -84.390264, "Atlanta, GA, USA"),
    "denver": (39.739236, -104.984862, "Denver, CO, USA"),
    "denver, co": (39.739236, -104.984862, "Denver, CO, USA"),
    "las vegas": (36.167256, -115.148516, "Las Vegas, NV, USA"),
    "las vegas, nv": (36.167256, -115.148516, "Las Vegas, NV, USA"),
}

_ROUTE_CACHE: Dict[str, Dict[str, Any]] = {}

def geocode_location(query: str) -> Tuple[float, float, str]:
    cleaned = query.strip()
    if not cleaned:
        raise ValueError("Location query cannot be empty.")
    
    coord_match = re.match(r"^([-+]?\d+(?:\.\d+)?)\s*,\s*([-+]?\d+(?:\.\d+)?)$", cleaned)
    if coord_match:
        lat = float(coord_match.group(1))
        lon = float(coord_match.group(2))
        return lat, lon, f"{lat:.4f}, {lon:.4f}"
    
    norm_key = cleaned.lower()
    if norm_key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[norm_key]
    
    url = NOMINATIM_BASE_URL
    headers = {
        "User-Agent": NOMINATIM_USER_AGENT
    }
    params = {
        "q": cleaned,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise ValueError(f"Location not found in the USA: '{query}'. Please check the spelling or specify city and state.")
        
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        display_name = data[0].get("display_name", cleaned)
        _GEOCODE_CACHE[norm_key] = (lat, lon, display_name)
        return lat, lon, display_name
    except requests.RequestException as exc:
        raise RuntimeError(f"Geocoding service error for '{query}': {str(exc)}")

def get_osrm_route(start_lat: float, start_lon: float, dest_lat: float, dest_lon: float) -> Dict[str, Any]:
    cache_key = f"{start_lat:.4f},{start_lon:.4f};{dest_lat:.4f},{dest_lon:.4f}"
    if cache_key in _ROUTE_CACHE:
        return _ROUTE_CACHE[cache_key]
    
    url = f"{OSRM_BASE_URL}/{start_lon},{start_lat};{dest_lon},{dest_lat}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
        "annotations": "false",
    }
    
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get("code") != "Ok" or not data.get("routes"):
            msg = data.get("message", "No route found between the specified locations.")
            raise ValueError(f"OSRM routing error: {msg}")
        
        route = data["routes"][0]
        distance_meters = float(route["distance"])
        distance_miles = distance_meters / 1609.344
        duration_seconds = float(route["duration"])
        duration_hours = duration_seconds / 3600.0
        geometry = route["geometry"]
        
        result = {
            "distance_miles": round(distance_miles, 2),
            "duration_hours": round(duration_hours, 2),
            "geometry": geometry,
            "coordinates": geometry["coordinates"],
        }
        
        _ROUTE_CACHE[cache_key] = result
        return result
    except requests.RequestException as exc:
        raise RuntimeError(f"Routing service error: {str(exc)}")
