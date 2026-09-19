import json
from urllib.parse import quote_plus
from django.shortcuts import render
from django.views import View
from django.views.generic import TemplateView
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .apps import FuelOptimizerConfig
from .services.routing import geocode_location, get_osrm_route
from .services.optimizer import (
    optimize_fuel_stops,
    build_route_geojson,
)

class RouteOptimizerAPIView(APIView):
    def get(self, request):
        return self._process_request(request.query_params)

    def post(self, request):
        return self._process_request(request.data)

    def _process_request(self, params):
        start_query = params.get("start", "").strip()
        finish_query = params.get("finish", "").strip()
        
        if not start_query or not finish_query:
            return Response(
                {
                    "success": False,
                    "error": "Both 'start' and 'finish' parameters are required.",
                    "example": "/api/route/?start=New+York,+NY&finish=Los+Angeles,+CA"
                },
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            max_range = float(params.get("max_range", 500.0))
            if max_range <= 0:
                raise ValueError("max_range must be positive.")
        except (ValueError, TypeError):
            return Response(
                {"success": False, "error": "Invalid 'max_range' value. Must be a positive number."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            mpg = float(params.get("mpg", 10.0))
            if mpg <= 0:
                raise ValueError("mpg must be positive.")
        except (ValueError, TypeError):
            return Response(
                {"success": False, "error": "Invalid 'mpg' value. Must be a positive number."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            start_lat, start_lon, start_name = geocode_location(start_query)
        except Exception as e:
            return Response(
                {"success": False, "error": f"Failed to geocode start location '{start_query}': {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            finish_lat, finish_lon, finish_name = geocode_location(finish_query)
        except Exception as e:
            return Response(
                {"success": False, "error": f"Failed to geocode finish location '{finish_query}': {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            route_data = get_osrm_route(start_lat, start_lon, finish_lat, finish_lon)
        except Exception as e:
            return Response(
                {"success": False, "error": f"Routing failed: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY
            )

        stations = FuelOptimizerConfig.stations
        station_tree = FuelOptimizerConfig.station_tree
        
        if not stations or station_tree is None:
            from .prepare_data import build_fuel_stations_dataset
            stations = build_fuel_stations_dataset()
            import numpy as np
            from scipy.spatial import cKDTree
            coords = np.array([[s["lat"], s["lon"]] for s in stations])
            station_tree = cKDTree(coords)
            FuelOptimizerConfig.stations = stations
            FuelOptimizerConfig.station_tree = station_tree

        optimization_result = optimize_fuel_stops(
            coordinates=route_data["coordinates"],
            total_dist_miles=route_data["distance_miles"],
            stations=stations,
            station_tree=station_tree,
            max_range_miles=max_range,
            mpg=mpg
        )

        start_info = {
            "query": start_query,
            "display_name": start_name,
            "lat": start_lat,
            "lon": start_lon
        }
        finish_info = {
            "query": finish_query,
            "display_name": finish_name,
            "lat": finish_lat,
            "lon": finish_lon
        }

        geojson_data = build_route_geojson(
            route_geometry=route_data["geometry"],
            start_info=start_info,
            finish_info=finish_info,
            fuel_stops=optimization_result["fuel_stops"]
        )

        map_url = f"/api/route/map/?start={quote_plus(start_query)}&finish={quote_plus(finish_query)}&max_range={max_range}&mpg={mpg}"

        response_data = {
            "success": True,
            "route": {
                "start": start_info,
                "finish": finish_info,
                "distance_miles": optimization_result["total_distance_miles"],
                "duration_hours": route_data["duration_hours"],
                "vehicle_parameters": {
                    "max_range_miles": max_range,
                    "fuel_efficiency_mpg": mpg
                }
            },
            "fuel_summary": {
                "total_distance_miles": optimization_result["total_distance_miles"],
                "total_gallons_consumed": optimization_result["total_gallons_consumed"],
                "total_money_spent": optimization_result["total_money_spent"],
                "average_price_per_gallon": optimization_result["average_price_per_gallon"],
                "fuel_stops_count": optimization_result["fuel_stops_count"],
            },
            "fuel_stops": optimization_result["fuel_stops"],
            "map_url": map_url,
            "geojson": geojson_data
        }

        return Response(response_data, status=status.HTTP_200_OK)


class RouteMapView(View):
    def get(self, request):
        start_query = request.GET.get("start", "New York, NY")
        finish_query = request.GET.get("finish", "Los Angeles, CA")
        max_range = float(request.GET.get("max_range", 500.0))
        mpg = float(request.GET.get("mpg", 10.0))
        
        try:
            start_lat, start_lon, start_name = geocode_location(start_query)
            finish_lat, finish_lon, finish_name = geocode_location(finish_query)
            route_data = get_osrm_route(start_lat, start_lon, finish_lat, finish_lon)
            
            stations = FuelOptimizerConfig.stations
            station_tree = FuelOptimizerConfig.station_tree
            
            opt = optimize_fuel_stops(
                coordinates=route_data["coordinates"],
                total_dist_miles=route_data["distance_miles"],
                stations=stations,
                station_tree=station_tree,
                max_range_miles=max_range,
                mpg=mpg
            )
            
            geojson = build_route_geojson(
                route_geometry=route_data["geometry"],
                start_info={"lat": start_lat, "lon": start_lon, "display_name": start_name},
                finish_info={"lat": finish_lat, "lon": finish_lon, "display_name": finish_name},
                fuel_stops=opt["fuel_stops"]
            )
            
            context = {
                "start_name": start_name,
                "finish_name": finish_name,
                "distance_miles": opt["total_distance_miles"],
                "duration_hours": route_data["duration_hours"],
                "total_money_spent": opt["total_money_spent"],
                "total_gallons": opt["total_gallons_consumed"],
                "fuel_stops_count": opt["fuel_stops_count"],
                "avg_price": opt["average_price_per_gallon"],
                "fuel_stops": opt["fuel_stops"],
                "geojson_str": json.dumps(geojson),
            }
            return render(request, "fuel_optimizer/map.html", context)
        except Exception as e:
            return render(request, "fuel_optimizer/error.html", {"error": str(e)})


class DashboardView(TemplateView):
    template_name = "fuel_optimizer/dashboard.html"
