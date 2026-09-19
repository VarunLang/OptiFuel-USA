import os
import json
import numpy as np
from scipy.spatial import cKDTree
from django.apps import AppConfig

class FuelOptimizerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'fuel_optimizer'
    
    stations = []
    station_tree = None

    def ready(self):
        data_path = os.path.join(os.path.dirname(__file__), "data", "fuel_stations.json")
        if os.path.exists(data_path):
            try:
                with open(data_path, "r", encoding="utf-8") as f:
                    FuelOptimizerConfig.stations = json.load(f)
                
                if FuelOptimizerConfig.stations:
                    coords = np.array([
                        [s["lat"], s["lon"]] for s in FuelOptimizerConfig.stations
                    ])
                    FuelOptimizerConfig.station_tree = cKDTree(coords)
                    print(f"FuelOptimizerConfig: Preloaded {len(FuelOptimizerConfig.stations)} fuel stations into cKDTree.")
            except Exception as e:
                print(f"Warning: Failed to preload fuel stations: {e}")
        else:
            print(f"Warning: Fuel stations data file not found at {data_path}. Run prepare_data.py to generate it.")
