"""Pure route/checkpoint engine for the persistent Santiago journey."""

from __future__ import annotations

import bisect
import json
import math
from pathlib import Path


JOURNEY_ID = "krakow-santiago"
ROUTE_ID = "krakow-santiago-bicycle-v1"
DISPLAY_NAME = "Kraków → Santiago"
CHECKPOINT_COUNT = 365


class SantiagoJourney:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        checkpoint_document = self._read("checkpoints.json")
        route_document = self._read("route.geojson")
        route_meta = self._read("route-meta.json")
        self.checkpoints = checkpoint_document.get("checkpoints") or []
        self.route = (route_document.get("geometry") or {}).get("coordinates") or []
        self.cumulative_km = route_meta.get("cumulativeKm") or []
        self.total_distance_km = float(route_meta.get("totalDistanceKm") or 0)
        self._validate()
        self.checkpoint_distances = [float(item["routeDistanceKm"]) for item in self.checkpoints]
        self.main_checkpoints = [item for item in self.checkpoints if not item.get("variantCheckpoint")]
        self.main_checkpoint_distances = [float(item["routeDistanceKm"]) for item in self.main_checkpoints]

    def _read(self, name):
        return json.loads((self.data_dir / name).read_text(encoding="utf-8"))

    def _validate(self):
        if len(self.checkpoints) != CHECKPOINT_COUNT:
            raise ValueError(f"Santiago journey requires {CHECKPOINT_COUNT} checkpoints")
        if [item.get("index") for item in self.checkpoints] != list(range(1, CHECKPOINT_COUNT + 1)):
            raise ValueError("Santiago checkpoint indexes must be 1..365")
        if len(self.route) < 2 or len(self.route) != len(self.cumulative_km):
            raise ValueError("Santiago route geometry and cumulative metadata do not match")
        if self.total_distance_km <= 0:
            raise ValueError("Santiago route total must be positive")
        if len({item.get("id") for item in self.checkpoints}) != CHECKPOINT_COUNT:
            raise ValueError("Santiago checkpoint IDs must be unique")
        if {item.get("originalIndex") for item in self.checkpoints} != set(range(1, CHECKPOINT_COUNT + 1)):
            raise ValueError("Santiago originalIndex identities must be 1..365")
        distances = [float(item.get("routeDistanceKm", -1)) for item in self.checkpoints]
        main_distances = [
            float(item.get("routeDistanceKm", -1))
            for item in self.checkpoints
            if not item.get("variantCheckpoint")
        ]
        if any(right < left for left, right in zip(distances, distances[1:])):
            raise ValueError("Santiago journey checkpoint distances must not decrease")
        if any(right <= left for left, right in zip(main_distances, main_distances[1:])):
            raise ValueError("Santiago main-route checkpoint distances must be strictly increasing")
        if abs(distances[-1] - self.total_distance_km) > 1:
            raise ValueError("Santiago endpoint does not match route total")

    def position_at(self, distance_km):
        distance = max(0.0, min(self.total_distance_km, float(distance_km or 0)))
        upper = bisect.bisect_right(self.cumulative_km, distance)
        if upper <= 0:
            lower = upper = 0
        elif upper >= len(self.cumulative_km):
            lower = upper = len(self.cumulative_km) - 1
        else:
            lower = upper - 1
        start_distance = float(self.cumulative_km[lower])
        end_distance = float(self.cumulative_km[upper])
        span = end_distance - start_distance
        ratio = 0.0 if span <= 0 else (distance - start_distance) / span
        start, end = self.route[lower], self.route[upper]
        longitude = float(start[0]) + (float(end[0]) - float(start[0])) * ratio
        latitude = float(start[1]) + (float(end[1]) - float(start[1])) * ratio
        return {
            "distanceKm": round(distance, 6),
            "latitude": round(latitude, 7),
            "longitude": round(longitude, 7),
        }

    def previous_checkpoint(self, distance_km):
        index = bisect.bisect_right(self.main_checkpoint_distances, float(distance_km or 0)) - 1
        return self._public_checkpoint(self.main_checkpoints[max(0, index)])

    def next_checkpoint(self, distance_km):
        distance = float(distance_km or 0)
        index = bisect.bisect_right(self.main_checkpoint_distances, distance)
        if index >= len(self.main_checkpoints):
            return None
        checkpoint = self._public_checkpoint(self.main_checkpoints[index])
        checkpoint["distanceAwayKm"] = round(max(0, checkpoint["routeDistanceKm"] - distance), 6)
        return checkpoint

    def crossed_checkpoints(self, previous_distance_km, new_distance_km):
        previous = max(0.0, float(previous_distance_km or 0))
        current = max(0.0, float(new_distance_km or 0))
        if current <= previous:
            return []
        start = bisect.bisect_right(self.checkpoint_distances, previous)
        end = bisect.bisect_right(self.checkpoint_distances, current)
        return [self._public_checkpoint(self.checkpoints[index]) for index in range(start, end)]

    def _public_checkpoint(self, item):
        return {
            key: item.get(key)
            for key in (
                "id", "index", "journeyIndex", "originalIndex", "name", "country", "section", "type",
                "lat", "lon", "routeDistanceKm", "imageUrl", "variantCheckpoint", "associatedCheckpointId",
            )
            if item.get(key) is not None
        }

    def snapshot(self, committed_distance_km=0, live_session_distance_km=0, include_checkpoints=False):
        committed = max(0.0, float(committed_distance_km or 0))
        live_session = max(0.0, float(live_session_distance_km or 0))
        live_distance = min(self.total_distance_km, committed + live_session)
        position = self.position_at(live_distance)
        payload = {
            "journeyId": JOURNEY_ID,
            "routeId": ROUTE_ID,
            "displayName": DISPLAY_NAME,
            "checkpointCount": len(self.checkpoints),
            "committedDistanceKm": round(committed, 6),
            "liveSessionDistanceKm": round(live_session, 6),
            "liveDistanceKm": round(live_distance, 6),
            "totalDistanceKm": round(self.total_distance_km, 6),
            "remainingDistanceKm": round(max(0, self.total_distance_km - live_distance), 6),
            "progress": min(1.0, live_distance / self.total_distance_km),
            "complete": live_distance >= self.total_distance_km,
            "position": {"lat": position["latitude"], "lon": position["longitude"]},
            "previousCheckpoint": self.previous_checkpoint(live_distance),
            "nextCheckpoint": self.next_checkpoint(live_distance),
        }
        if include_checkpoints:
            payload["checkpoints"] = [self._public_checkpoint(item) for item in self.checkpoints]
        return payload
