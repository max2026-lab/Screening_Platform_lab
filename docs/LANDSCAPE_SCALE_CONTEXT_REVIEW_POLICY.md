# Landscape-Scale Context Review Policy

## Current decision

- landscape-scale context review remains guidance-only for now
- no enforcement gate is implemented in this step
- no scoring, suppression, or threshold changes are made

## Why guidance-only for now

- avoids blocking legitimate urgent cases
- keeps reviewer judgment central
- allows collection of real examples
- avoids premature policy logic before enough evidence exists

## Trigger

- applies when `is_landscape_scale = true`
- current threshold is `250000.0 m2 / 25 ha`
- candidate uses `reviewer_review_track = landscape_scale_separate_review`

## Definition of context review complete

- reviewer explicitly assesses surrounding landscape/context
- reviewer records whether candidate is object-scale actionable, landscape-scale only, duplicate/context artifact, or needs monitoring
- reviewer records rationale before paid imagery escalation
- automated score alone is not sufficient

## Required evidence to record

- `reviewer_id`
- `candidate_id`
- `run_id`
- context review decision
- short rationale/note
- whether paid imagery escalation is allowed
- timestamp if supported by the existing review action flow

## Candidate decision options to evaluate later

- keep existing decisions only: `reject` / `watch` / `approve_for_archive_quote`
- add metadata-only context-review fields
- add a new explicit context-review-complete gate
- add a new state only if unavoidable

## Future enforcement options

- guidance-only, current behavior
- warning-only before paid quote
- hard block before paid quote/order unless context review complete
- hard block only for paid order, not quote

## Recommended future default

- start with warning-only or metadata-only enforcement before hard blocking
- do not change scoring or suppression until more real examples exist

## Non-goals

- no detector-quality claim
- no scoring formula change
- no threshold change
- no candidate suppression
- no paid-flow enforcement in this doc branch
- no DB migration

## Acceptance criteria for future implementation

- existing zero-candidate flow unaffected
- existing non-landscape candidates unaffected
- landscape-scale candidates remain visible
- paid escalation policy is auditable
- reviewer closeout remains understandable
