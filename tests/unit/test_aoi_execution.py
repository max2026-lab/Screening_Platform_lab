import pytest
import json
from pathlib import Path
from lawful_anomaly_screening.aoi.validation import validate_aoi_file, extract_bbox_from_geojson
from lawful_anomaly_screening.sources.manifest_builder import build_manifest, create_source_scene_manifest_hash

def test_validate_aoi_file(tmp_path):
    aoi_path = tmp_path / "test.geojson"
    aoi_data = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
    }
    aoi_path.write_text(json.dumps(aoi_data))
    
    metadata = validate_aoi_file(aoi_path)
    assert metadata["aoi_geometry_type"] == "Polygon"
    assert metadata["aoi_bbox"] == [0.0, 0.0, 1.0, 1.0]
    assert metadata["aoi_geometry"] == aoi_data
    assert "aoi_hash" in metadata

def test_validate_aoi_invalid_type(tmp_path):
    aoi_path = tmp_path / "test.geojson"
    aoi_data = {
        "type": "Point",
        "coordinates": [0, 0]
    }
    aoi_path.write_text(json.dumps(aoi_data))
    
    with pytest.raises(ValueError, match="AOI geometry must be Polygon or MultiPolygon"):
        validate_aoi_file(aoi_path)

def test_validate_aoi_feature_collection_multiple(tmp_path):
    aoi_path = tmp_path / "test.geojson"
    aoi_data = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}}
        ]
    }
    aoi_path.write_text(json.dumps(aoi_data))
    
    with pytest.raises(ValueError, match="FeatureCollection must contain exactly one feature"):
        validate_aoi_file(aoi_path)

def test_validate_aoi_empty_geometry(tmp_path):
    aoi_path = tmp_path / "test.geojson"
    aoi_data = {
        "type": "Polygon",
        "coordinates": []
    }
    aoi_path.write_text(json.dumps(aoi_data))
    
    with pytest.raises(ValueError, match="AOI geometry is empty"):
        validate_aoi_file(aoi_path)

def test_manifest_hash_depends_on_aoi_and_dates():
    manifest1 = build_manifest(aoi_hash="hash1", start_date="2024-01-01", end_date="2024-03-31")
    manifest2 = build_manifest(aoi_hash="hash2", start_date="2024-01-01", end_date="2024-03-31")
    manifest3 = build_manifest(aoi_hash="hash1", start_date="2024-01-02", end_date="2024-03-31")
    
    hash1 = create_source_scene_manifest_hash(manifest1)
    hash2 = create_source_scene_manifest_hash(manifest2)
    hash3 = create_source_scene_manifest_hash(manifest3)
    
    assert hash1 != hash2
    assert hash1 != hash3


def test_bbox_extraction_from_polygon_geojson():
    aoi_data = {
        "type": "Polygon",
        "coordinates": [[[10.0, 20.0], [30.0, 20.0], [30.0, 40.0], [10.0, 40.0], [10.0, 20.0]]]
    }
    bbox = extract_bbox_from_geojson(aoi_data)
    assert bbox == [10.0, 20.0, 30.0, 40.0]


def test_bbox_extraction_from_feature_collection_geojson():
    aoi_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[5.0, 15.0], [25.0, 15.0], [25.0, 35.0], [5.0, 35.0], [5.0, 15.0]]]
                }
            }
        ]
    }
    bbox = extract_bbox_from_geojson(aoi_data)
    assert bbox == [5.0, 15.0, 25.0, 35.0]


def test_malformed_aoi_no_coordinates_fails_clearly():
    aoi_data = {"type": "Polygon", "coordinates": []}
    with pytest.raises(ValueError, match="AOI geometry is empty"):
        extract_bbox_from_geojson(aoi_data)
