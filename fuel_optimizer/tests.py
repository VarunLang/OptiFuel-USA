from django.test import SimpleTestCase, Client
from django.urls import reverse
import numpy as np
from scipy.spatial import cKDTree

from fuel_optimizer.services.routing import geocode_location
from fuel_optimizer.services.optimizer import (
    haversine_miles,
    compute_cumulative_distances,
    find_candidate_stations_along_route,
    optimize_fuel_stops,
    build_route_geojson
)
from fuel_optimizer.apps import FuelOptimizerConfig

class FuelOptimizerUnitTests(SimpleTestCase):
    def test_haversine_distance(self):
        dist = haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
        self.assertTrue(2400 < dist < 2500, f"Unexpected air distance: {dist}")

    def test_geocoding_coordinates_and_cache(self):
        lat, lon, name = geocode_location("32.7767, -96.7970")
        self.assertAlmostEqual(lat, 32.7767, places=4)
        self.assertAlmostEqual(lon, -96.7970, places=4)

        ny_lat, ny_lon, ny_name = geocode_location("New York, NY")
        self.assertAlmostEqual(ny_lat, 40.7127, places=2)
        self.assertAlmostEqual(ny_lon, -74.0060, places=2)

    def test_cumulative_distances(self):
        coords = [
            [-74.0060, 40.7128],
            [-74.0060, 41.7128],
            [-74.0060, 42.7128],
        ]
        cum_dist = compute_cumulative_distances(coords)
        self.assertEqual(len(cum_dist), 3)
        self.assertEqual(cum_dist[0], 0.0)
        self.assertTrue(65 < cum_dist[1] < 75)
        self.assertTrue(130 < cum_dist[2] < 145)

    def test_short_route_no_stops_needed(self):
        mock_coords = [[-96.8, 32.8], [-95.3, 29.8]]
        total_dist = 240.0
        opt = optimize_fuel_stops(
            coordinates=mock_coords,
            total_dist_miles=total_dist,
            stations=FuelOptimizerConfig.stations,
            station_tree=FuelOptimizerConfig.station_tree,
            max_range_miles=500.0,
            mpg=10.0
        )
        self.assertEqual(opt["fuel_stops_count"], 0)
        self.assertEqual(len(opt["fuel_stops"]), 0)
        self.assertAlmostEqual(opt["total_gallons_consumed"], opt["total_distance_miles"] / 10.0, places=1)
        self.assertGreater(opt["total_money_spent"], 0)

    def test_long_route_refueling_constraints(self):
        lons = np.linspace(-90.0, -80.0, 100)
        lats = np.linspace(30.0, 45.0, 100)
        mock_route_coords = [[lon, lat] for lon, lat in zip(lons, lats)]
        cum_dist = compute_cumulative_distances(mock_route_coords)
        total_dist = float(cum_dist[-1])
        self.assertGreater(total_dist, 1000.0)

        synthetic_stations = []
        for i, idx in enumerate(range(10, 95, 10)):
            synthetic_stations.append({
                "id": 1000 + i,
                "name": f"Test Station #{i+1}",
                "address": f"{i*100} Interstate Hwy",
                "city": f"TestCity{i}",
                "state": "US",
                "rack_id": 100,
                "price": 3.00 + (0.1 * (i % 3)),
                "lat": float(lats[idx]),
                "lon": float(lons[idx]),
            })

        station_coords = np.array([[s["lat"], s["lon"]] for s in synthetic_stations])
        station_tree = cKDTree(station_coords)

        opt = optimize_fuel_stops(
            coordinates=mock_route_coords,
            total_dist_miles=total_dist,
            stations=synthetic_stations,
            station_tree=station_tree,
            max_range_miles=500.0,
            mpg=10.0
        )

        self.assertGreater(opt["fuel_stops_count"], 0)
        stops = opt["fuel_stops"]

        prev_mile = 0.0
        for stop in stops:
            leg_dist = stop["mile_marker"] - prev_mile
            self.assertLessEqual(leg_dist, 500.0, f"Leg distance {leg_dist} exceeded 500 miles!")
            prev_mile = stop["mile_marker"]

        final_leg = total_dist - prev_mile
        self.assertLessEqual(final_leg, 500.0, f"Final leg {final_leg} exceeded 500 miles!")

        expected_gallons = round(total_dist / 10.0, 2)
        self.assertAlmostEqual(opt["total_gallons_consumed"], expected_gallons, delta=0.5)

    def test_build_route_geojson(self):
        route_geom = {
            "type": "LineString",
            "coordinates": [[-74.0, 40.7], [-118.2, 34.0]]
        }
        start = {"lat": 40.7, "lon": -74.0, "display_name": "New York"}
        finish = {"lat": 34.0, "lon": -118.2, "display_name": "Los Angeles"}
        stops = [
            {
                "stop_number": 1,
                "name": "Stop 1",
                "address": "Address 1",
                "city": "City",
                "state": "ST",
                "price_per_gallon": 3.19,
                "location": {"latitude": 39.0, "longitude": -84.0},
                "mile_marker": 400.0,
                "gallons_refueled": 40.0,
                "cost_at_stop": 127.60,
            }
        ]
        geojson = build_route_geojson(route_geom, start, finish, stops)
        self.assertEqual(geojson["type"], "FeatureCollection")
        self.assertEqual(len(geojson["features"]), 4)


class FuelOptimizerAPITests(SimpleTestCase):
    def setUp(self):
        self.client = Client()

    def test_dashboard_view_status(self):
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "OptiFuel USA")

    def test_api_missing_parameters(self):
        resp = self.client.get(reverse('api-route'))
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["success"])
        self.assertIn("Both 'start' and 'finish'", data["error"])

    def test_api_route_get_endpoint(self):
        resp = self.client.get(reverse('api-route'), {
            "start": "Chicago, IL",
            "finish": "Miami, FL",
            "max_range": "500",
            "mpg": "10"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("route", data)
        self.assertIn("fuel_summary", data)
        self.assertIn("fuel_stops", data)
        self.assertIn("map_url", data)
        self.assertIn("geojson", data)

        summary = data["fuel_summary"]
        self.assertGreater(summary["total_distance_miles"], 1000)
        self.assertGreater(summary["total_money_spent"], 0)
        self.assertGreater(summary["fuel_stops_count"], 0)

    def test_api_route_post_endpoint(self):
        payload = {
            "start": "Dallas, TX",
            "finish": "Houston, TX",
            "max_range": 500,
            "mpg": 10
        }
        resp = self.client.post(reverse('api-route'), data=payload, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertLess(data["route"]["distance_miles"], 300)
        self.assertEqual(data["fuel_summary"]["fuel_stops_count"], 0)

    def test_standalone_map_view(self):
        resp = self.client.get(reverse('api-route-map'), {
            "start": "Chicago, IL",
            "finish": "Miami, FL"
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "OptiFuel Route Map")
        self.assertContains(resp, "leaflet.js")
