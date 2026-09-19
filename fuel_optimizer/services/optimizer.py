import numpy as np
from scipy.spatial import cKDTree
from typing import List, Dict, Any, Tuple

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_miles = 3958.8
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2.0) ** 2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2.0) ** 2
    c = 2.0 * np.arcsin(np.sqrt(a))
    return float(r_miles * c)

def compute_cumulative_distances(coordinates: List[List[float]]) -> np.ndarray:
    if not coordinates:
        return np.array([0.0])
    
    lons = np.array([pt[0] for pt in coordinates])
    lats = np.array([pt[1] for pt in coordinates])
    
    r_miles = 3958.8
    dlat = np.radians(lats[1:] - lats[:-1])
    dlon = np.radians(lons[1:] - lons[:-1])
    a = np.sin(dlat / 2.0) ** 2 + np.cos(np.radians(lats[:-1])) * np.cos(np.radians(lats[1:])) * np.sin(dlon / 2.0) ** 2
    seg_dists = 2.0 * r_miles * np.arcsin(np.sqrt(a))
    cum_dists = np.concatenate([[0.0], np.cumsum(seg_dists)])
    return cum_dists

def find_candidate_stations_along_route(
    coordinates: List[List[float]],
    cum_distances: np.ndarray,
    stations: List[Dict[str, Any]],
    station_tree: cKDTree,
    corridor_radius_miles: float = 12.0
) -> List[Dict[str, Any]]:
    if not coordinates or not stations:
        return []

    route_lats = np.array([pt[1] for pt in coordinates])
    route_lons = np.array([pt[0] for pt in coordinates])
    route_points = np.column_stack([route_lats, route_lons])
    
    total_dist = cum_distances[-1]
    step = max(1, len(coordinates) // 250)
    sample_indices = np.arange(0, len(coordinates), step)
    if sample_indices[-1] != len(coordinates) - 1:
        sample_indices = np.append(sample_indices, len(coordinates) - 1)
    
    sample_points = route_points[sample_indices]
    
    radius_deg = corridor_radius_miles / 69.0
    matched_lists = station_tree.query_ball_point(sample_points, r=radius_deg)
    
    candidate_indices = set()
    for sublist in matched_lists:
        candidate_indices.update(sublist)
        
    if not candidate_indices:
        return []

    candidate_stations_coords = np.array([
        [stations[i]["lat"], stations[i]["lon"]] for i in candidate_indices
    ])
    
    route_tree = cKDTree(route_points)
    dists_deg, route_idx_matches = route_tree.query(candidate_stations_coords)
    
    candidates = []
    seen_ids = set()
    for idx_in_subset, station_idx in enumerate(candidate_indices):
        st = stations[station_idx]
        st_id = st["id"]
        if st_id in seen_ids:
            continue
        seen_ids.add(st_id)
        
        route_idx = route_idx_matches[idx_in_subset]
        dist_to_route_miles = dists_deg[idx_in_subset] * 69.0
        
        if dist_to_route_miles <= corridor_radius_miles:
            mile_marker = float(cum_distances[route_idx])
            candidates.append({
                "id": st["id"],
                "name": st["name"],
                "address": st["address"],
                "city": st["city"],
                "state": st["state"],
                "price": float(st["price"]),
                "lat": float(st["lat"]),
                "lon": float(st["lon"]),
                "mile_marker": round(mile_marker, 2),
                "corridor_dist_miles": round(dist_to_route_miles, 2),
            })

    candidates.sort(key=lambda x: x["mile_marker"])
    return candidates

def optimize_fuel_stops(
    coordinates: List[List[float]],
    total_dist_miles: float,
    stations: List[Dict[str, Any]],
    station_tree: cKDTree,
    max_range_miles: float = 500.0,
    mpg: float = 10.0,
    safe_buffer_miles: float = 40.0,
) -> Dict[str, Any]:
    cum_distances = compute_cumulative_distances(coordinates)
    actual_total_dist = float(cum_distances[-1]) if cum_distances.size > 0 else total_dist_miles
    
    candidates = find_candidate_stations_along_route(
        coordinates, cum_distances, stations, station_tree, corridor_radius_miles=12.0
    )
    
    if len(candidates) < 3 and total_dist_miles > max_range_miles:
        candidates = find_candidate_stations_along_route(
            coordinates, cum_distances, stations, station_tree, corridor_radius_miles=25.0
        )

    effective_max_leg = max(100.0, max_range_miles - safe_buffer_miles)
    
    if actual_total_dist <= max_range_miles:
        total_gallons = round(actual_total_dist / mpg, 2)
        ref_price = candidates[0]["price"] if candidates else 3.25
        total_money = round(total_gallons * ref_price, 2)
        
        return {
            "total_distance_miles": round(actual_total_dist, 2),
            "max_vehicle_range_miles": max_range_miles,
            "fuel_efficiency_mpg": mpg,
            "total_gallons_consumed": total_gallons,
            "total_money_spent": total_money,
            "average_price_per_gallon": round(ref_price, 3),
            "fuel_stops_count": 0,
            "fuel_stops": [],
            "candidate_stations_count": len(candidates),
        }

    selected_stops: List[Dict[str, Any]] = []
    curr_mile = 0.0
    
    while (curr_mile + effective_max_leg) < actual_total_dist:
        max_reach = min(actual_total_dist, curr_mile + effective_max_leg)
        min_progress = min(curr_mile + 80.0, max_reach - 30.0)
        window = [s for s in candidates if min_progress <= s["mile_marker"] <= max_reach]
        
        if not window:
            hard_max_reach = min(actual_total_dist, curr_mile + max_range_miles)
            window = [s for s in candidates if curr_mile + 10.0 <= s["mile_marker"] <= hard_max_reach]
            
        if not window:
            ahead = [s for s in candidates if s["mile_marker"] > curr_mile]
            if ahead:
                best_stop = ahead[0]
            else:
                break
        else:
            best_stop = min(
                window,
                key=lambda s: (s["price"] * 1.0) - (0.0003 * (s["mile_marker"] - curr_mile))
            )
            
        selected_stops.append(dict(best_stop))
        curr_mile = best_stop["mile_marker"]
        
        if (actual_total_dist - curr_mile) <= effective_max_leg:
            break

    leg_start_mile = 0.0
    total_money = 0.0
    total_gallons = round(actual_total_dist / mpg, 2)
    
    enriched_stops = []
    for i, stop in enumerate(selected_stops):
        leg_dist = stop["mile_marker"] - leg_start_mile
        gallons_for_leg = leg_dist / mpg
        cost_for_leg = gallons_for_leg * stop["price"]
        
        is_last = (i == len(selected_stops) - 1)
        final_leg_dist = 0.0
        final_leg_gallons = 0.0
        final_leg_cost = 0.0
        
        if is_last:
            final_leg_dist = actual_total_dist - stop["mile_marker"]
            final_leg_gallons = final_leg_dist / mpg
            final_leg_cost = final_leg_gallons * stop["price"]
            
        total_stop_gallons = gallons_for_leg + final_leg_gallons
        total_stop_cost = cost_for_leg + final_leg_cost
        total_money += total_stop_cost
        
        enriched_stops.append({
            "stop_number": i + 1,
            "truckstop_id": stop["id"],
            "name": stop["name"],
            "address": stop["address"],
            "city": stop["city"],
            "state": stop["state"],
            "price_per_gallon": round(stop["price"], 3),
            "location": {
                "latitude": stop["lat"],
                "longitude": stop["lon"],
            },
            "mile_marker": round(stop["mile_marker"], 1),
            "leg_distance_miles": round(leg_dist, 1),
            "gallons_refueled": round(total_stop_gallons, 2),
            "cost_at_stop": round(total_stop_cost, 2),
            "next_leg_distance_miles": round(final_leg_dist if is_last else (selected_stops[i+1]["mile_marker"] - stop["mile_marker"]), 1)
        })
        
        leg_start_mile = stop["mile_marker"]

    avg_price = (total_money / total_gallons) if total_gallons > 0 else 0.0

    return {
        "total_distance_miles": round(actual_total_dist, 2),
        "max_vehicle_range_miles": max_range_miles,
        "fuel_efficiency_mpg": mpg,
        "total_gallons_consumed": total_gallons,
        "total_money_spent": round(total_money, 2),
        "average_price_per_gallon": round(avg_price, 3),
        "fuel_stops_count": len(enriched_stops),
        "fuel_stops": enriched_stops,
        "candidate_stations_count": len(candidates),
    }

def build_route_geojson(
    route_geometry: Dict[str, Any],
    start_info: Dict[str, Any],
    finish_info: Dict[str, Any],
    fuel_stops: List[Dict[str, Any]]
) -> Dict[str, Any]:
    features = [
        {
            "type": "Feature",
            "geometry": route_geometry,
            "properties": {
                "role": "route_path",
                "stroke": "#2563EB",
                "stroke-width": 4,
                "stroke-opacity": 0.85
            }
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [start_info["lon"], start_info["lat"]]
            },
            "properties": {
                "role": "origin",
                "name": start_info["display_name"],
                "marker-color": "#10B981",
                "marker-symbol": "star"
            }
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [finish_info["lon"], finish_info["lat"]]
            },
            "properties": {
                "role": "destination",
                "name": finish_info["display_name"],
                "marker-color": "#EF4444",
                "marker-symbol": "destination"
            }
        }
    ]

    for stop in fuel_stops:
        loc = stop["location"]
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [loc["longitude"], loc["latitude"]]
            },
            "properties": {
                "role": "fuel_stop",
                "stop_number": stop["stop_number"],
                "name": stop["name"],
                "address": f"{stop['address']}, {stop['city']}, {stop['state']}",
                "price_per_gallon": stop["price_per_gallon"],
                "mile_marker": stop["mile_marker"],
                "gallons_refueled": stop["gallons_refueled"],
                "cost_at_stop": stop["cost_at_stop"],
                "marker-color": "#F59E0B",
                "marker-symbol": "fuel"
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features
    }
