# PRD: GEE Paid Archive Triage Integration v6

## 1. Product summary

Add a lawful Google Earth Engine (GEE) remote-sensing triage workflow to the Screening Platform project.

The workflow produces a desk-based shortlist of candidate areas where paid high-resolution archive imagery may be worth requesting. It does not claim to find treasure, prove archaeological value, authorize entry, authorize metal detecting, authorize excavation, or replace landowner/heritage/environmental permits.

The current validated notebook version is `lawful_gee_candidate_scout_FINAL_v6_1_fixed_request_zones_quality.ipynb`.

## 2. Problem

The project currently has strong workflow governance: legal gates, SQLite persistence, review states, export restrictions, paid archive quote/order lifecycle, and release verification. However, the repository does not yet contain the live GEE public-data triage logic used in the Colab notebook.

The notebook currently performs real public-data screening, but it is outside the repository workflow. This creates a gap:

- GEE candidate outputs are not persisted in the project database.
- Legal/review/export controls are not automatically applied to notebook outputs.
- Request zones and imagery quote comparisons are not managed by the existing platform lifecycle.
- Operators must manually move CSV/GeoJSON outputs from Colab into downstream review.

## 3. Goals

### 3.1 Functional goals

1. Support importing GEE notebook outputs into the platform.
2. Preserve the notebook's real-data candidate scoring outputs.
3. Create request zones from stable/high-priority candidates.
4. Add stronger road/building false-positive filters and warnings.
5. Add a paid-imagery quote comparison workflow.
6. Keep all outputs governed by the platform legal gate, review state, export precision, and paid archive flow.

### 3.2 Quality goals

1. Reduce false positives before paid imagery spend.
2. Separate raw candidate score from review priority.
3. Preserve explainability for every score and warning.
4. Make outputs reproducible and auditable.
5. Keep exact coordinates restricted to reviewer/internal use only.

### 3.3 Safety/legal goals

1. Enforce legal attestation and geofence clearance before import/escalation.
2. Keep public/shared exports coordinate-restricted or redacted.
3. Make the final rule visible in all operator outputs:

> This workflow produces a desk-based paid imagery shortlist. It does not prove treasure, authorize entry, authorize metal detecting, authorize excavation, or replace permits.

## 4. Non-goals

The v6 integration must not include:

- Field action planning.
- Digging, excavation, collection, or metal-detecting instructions.
- Claims that candidates indicate treasure.
- Automated purchase of imagery without explicit human action.
- Production cloud deployment.
- Multi-user auth/roles.
- Background workers or queue architecture.
- Machine learning training or automated recalibration.
- Any bypass of landowner, heritage, environmental, or protected-area requirements.

## 5. Users

### 5.1 Operator

Runs the GEE notebook, imports outputs, reviews candidates, creates request zones, compares paid imagery quotes, and prepares evidence for lawful review.

### 5.2 Reviewer

Approves or rejects candidates/request zones for paid archive quote based on evidence, false-positive warnings, and legal status.

### 5.3 Auditor / project owner

Checks that legal gates, export policies, quote/order state transitions, and evidence artifacts are complete.

## 6. Current v6 notebook outputs

The v6 notebook creates:

- `lawful_gee_candidate_scout_top_25_<timestamp>.csv`
- `lawful_gee_candidate_scout_top_25_<timestamp>.geojson`
- `top25_enhanced_v6.csv`
- `top25_enhanced_v6.geojson`
- `quality_diagnostics_all_cells_v6.csv`
- `stable_candidate_priority_list_v6.csv`
- `request_zones_v6.csv`
- `request_zones_v6.geojson`
- `paid_imagery_quote_template_v6.csv`
- `paid_imagery_quote_comparison_v6.csv`
- `paid_archive_request_summary.txt`
- `visual_inspection_map.html`
- `paid_archive_request_candidate_package_FINAL_v6_ZONES_QUOTES.zip`

## 7. Key concepts

### 7.1 Candidate cell

A grid cell scored from public GEE data. It includes visibility, contrast, terrain, seasonal stability, sensitivity stability, false-positive warnings, and review priority.

### 7.2 Request zone

A grouped/buffered area derived from one or more high-priority candidate cells. It is the practical geometry used when requesting paid high-resolution archive imagery.

### 7.3 False-positive warning

A warning that a candidate may be explained by modern or low-value features, such as roads, buildings, cropland, water edges, linear artifacts, quarry/construction patterns, or settlement proximity.

### 7.4 Paid imagery quote

A human-reviewed provider offer with metadata such as provider, acquisition date, resolution, cloud cover, off-nadir angle, price, license, and coverage of priority request zones.

## 8. Candidate scoring requirements

### 8.1 Required imported candidate fields

The platform must support at least these fields from `top25_enhanced_v6.csv` and `stable_candidate_priority_list_v6.csv`:

- `cell_id`
- `center_lon`
- `center_lat`
- `candidate_score`
- `quality_adjusted_score`
- `review_priority_score`
- `confidence_score_all`
- `stability_score`
- `top10_count`
- `top25_count`
- `avg_rank`
- `season_top10_count`
- `season_top25_count`
- `season_avg_rank`
- `season_score_mean`
- `season_score_std`
- `score_gap_from_median`
- `score_gap_to_next_rank`
- `balanced_rank`
- `visibility_heavy_rank`
- `contrast_heavy_rank`
- `terrain_heavy_rank`
- `visibility_score`
- `remote_sensing_contrast`
- `terrain_score`
- `s2_count`
- `builtup_frac`
- `builtup_near_frac`
- `cropland_frac`
- `water_edge_frac`
- `builtup_warning`
- `cropland_heavy_warning`
- `water_edge_warning`
- `modern_linear_edge_warning`
- `false_positive_warning_count`
- `worldcover_mode`

### 8.2 Ranking behavior

The platform must not rank only by raw `candidate_score`.

Primary review ordering must use:

1. `review_priority_score`
2. `false_positive_warning_count` ascending
3. `confidence_score_all`
4. `stability_score`
5. `candidate_score`

### 8.3 Candidate interpretation rule

A high-scoring candidate means:

> Worth review with paid imagery.

It must never be presented as:

> Treasure found.

## 9. Request zone requirements

### 9.1 Zone creation

The system must support importing `request_zones_v6.geojson` and `request_zones_v6.csv`.

Each request zone should include:

- `zone_id`
- geometry
- centroid
- area estimate
- candidate cell IDs included
- candidate count
- max candidate score
- mean review priority score
- max confidence score
- min false-positive warning count
- reason summary
- recommended imagery specs

### 9.2 Zone ranking

Request zones should be ranked by:

1. clean candidate presence
2. highest review priority score
3. confidence score
4. stability score
5. low false-positive warning count
6. practical coverage efficiency

### 9.3 Zone export

Reviewer/internal exports may include exact request-zone geometry.

Public/report exports must apply existing export precision policy and must not expose exact sensitive coordinates.

## 10. Stronger road/building filter requirements

The v6 workflow must flag likely modern false positives using public data where available.

Required warning fields:

- `builtup_warning`
- `cropland_heavy_warning`
- `water_edge_warning`
- `modern_linear_edge_warning`
- `false_positive_warning_count`

Desired future warning fields:

- `road_proximity_warning`
- `settlement_proximity_warning`
- `quarry_or_construction_warning`
- `building_density_warning`
- `field_boundary_pattern_warning`

Warning behavior:

- Warnings must not automatically delete candidates.
- Warnings must lower review priority or require manual review.
- Clean candidates with high confidence should be elevated above high raw-score candidates with obvious false-positive warnings.

## 11. Paid imagery quote comparison requirements

### 11.1 Quote template

The workflow must produce `paid_imagery_quote_template_v6.csv` with columns for operators/providers to fill:

- `quote_id`
- `provider`
- `zone_id`
- `candidate_ids_covered`
- `acquisition_date`
- `sensor`
- `resolution_m`
- `cloud_cover_pct`
- `off_nadir_deg`
- `sun_elevation_deg`
- `processing_level`
- `license_terms`
- `price`
- `currency`
- `delivery_time_days`
- `coverage_score`
- `metadata_complete`
- `notes`

### 11.2 Quote scoring

The comparison file must support ranking offers using:

- resolution quality
- cloud cover
- off-nadir angle
- coverage of priority zones
- metadata completeness
- license acceptability
- price
- delivery time

### 11.3 Human action requirement

No paid quote or order may be created automatically.

Quote and order escalation must require:

- legal gate passed
- reviewer approval
- export audit manifest exists
- explicit human trigger

## 12. Import workflow requirements

Add an import command or module that accepts a v6 package directory or zip.

Proposed CLI:

```powershell
lawful-anomaly gee-import-v6 `
  --run-id <run_id> `
  --package-path <paid_archive_request_candidate_package_FINAL_v6_ZONES_QUOTES.zip> `
  --attestation present `
  --geofence clear
```

The importer must:

1. Validate the package exists.
2. Validate required files are present.
3. Validate CSV schemas.
4. Validate GeoJSON structure.
5. Create or link a run record.
6. Store candidate cells.
7. Store request zones.
8. Store quote template/comparison metadata.
9. Store provenance hashes for each imported file.
10. Block import/escalation if legal gate fails.

## 13. Data model additions

Minimum new logical entities:

### 13.1 `gee_import_artifacts`

Tracks imported package metadata and file hashes.

Fields:

- `artifact_id`
- `run_id`
- `package_name`
- `package_sha256`
- `imported_at`
- `notebook_version`
- `required_files_present`
- `schema_valid`
- `legal_gate_decision`

### 13.2 `request_zones`

Stores paid-imagery request zones.

Fields:

- `zone_id`
- `run_id`
- `geometry_json`
- `centroid`
- `area_m2`
- `candidate_ids`
- `zone_score`
- `false_positive_warning_count_min`
- `review_state`

### 13.3 `imagery_quote_comparisons`

Stores paid imagery quote comparison rows.

Fields:

- `quote_id`
- `run_id`
- `zone_id`
- `provider`
- `resolution_m`
- `cloud_cover_pct`
- `off_nadir_deg`
- `price`
- `currency`
- `license_terms`
- `comparison_score`
- `human_selected`

## 14. Review workflow requirements

The platform should support review states for both candidates and request zones.

Suggested states:

- `pending_review`
- `rejected_false_positive`
- `approved_for_request_zone`
- `approved_for_archive_quote`
- `quote_requested`
- `quote_received`
- `order_ready`
- `order_submitted`
- `imagery_delivered`
- `closed_no_action`

Manual notes must be preserved.

## 15. Acceptance criteria

### 15.1 Notebook/package acceptance

A v6 package is accepted only if:

- required files are present
- schemas validate
- `quality_diagnostics_all_cells_v6.csv` exists
- `stable_candidate_priority_list_v6.csv` exists
- `request_zones_v6.geojson` exists
- `paid_imagery_quote_template_v6.csv` exists
- `paid_imagery_quote_comparison_v6.csv` exists
- final rule text is present in summary

### 15.2 Import acceptance

An import is accepted only if:

- legal gate passes
- all file hashes are stored
- candidate count is greater than zero
- request zone count is greater than zero
- exact-coordinate exports remain restricted to internal/reviewer audience

### 15.3 Quote comparison acceptance

A quote comparison is accepted only if:

- every compared quote links to a request zone
- resolution, cloud cover, off-nadir, price, and license fields are present
- selected quote requires explicit human action
- no automatic order is submitted

## 16. Metrics

Track:

- number of candidate cells imported
- number of request zones created
- clean candidate percentage
- false-positive warning distribution
- quote count per request zone
- selected provider/quote
- paid escalation count
- rejected false-positive count
- top10/top25 stability metrics
- season stability metrics

## 17. Risks

| Risk | Mitigation |
| --- | --- |
| False positives from farms/roads/buildings | stronger warning flags and manual review |
| Overconfidence in scores | final rule, confidence separation, score-gap diagnostics |
| Unsafe coordinate exposure | export precision policy |
| Unlawful field action | legal gate and hard-stop language |
| Paid imagery waste | request zones and quote comparison |
| Notebook/repo drift | versioned import schema and artifact hashes |

## 18. Rollout plan

### Phase A: Documentation

- Add this PRD.
- Add operator notes for v6 package handling.

### Phase B: Import scaffold

- Add `gee-import-v6` CLI command.
- Validate package and schemas.
- Store provenance hashes.

### Phase C: Persistence

- Persist candidate cells, request zones, and quote comparison rows.

### Phase D: Review and export

- Add request-zone review queue.
- Apply export precision policy to candidate and request-zone outputs.

### Phase E: Paid archive workflow

- Link request zones to existing paid quote/order services.
- Require reviewer approval and explicit human action.

## 19. Open questions

1. Should exact GEE candidate outputs be stored in the same candidate tables or separate GEE-specific tables?
2. Should request zones be reviewer-created, notebook-created, or both?
3. Which road/building datasets are acceptable for production use in the target geographies?
4. Should the platform support multiple notebook versions with separate import schemas?
5. What is the minimum evidence bundle required before a paid quote request?

## 20. Final rule

This project supports lawful desk-based remote-sensing triage only.

It does not prove treasure, authorize entry, authorize metal detecting, authorize excavation, authorize collection, or replace landowner, heritage, environmental, or protected-area permits.
