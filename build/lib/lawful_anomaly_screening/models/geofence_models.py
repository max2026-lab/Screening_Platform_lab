from dataclasses import dataclass


@dataclass(frozen=True)
class GeofenceRecord:
    geofence_id: str
    name: str
