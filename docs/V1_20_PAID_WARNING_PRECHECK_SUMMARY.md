# V1.20 Paid Warning Precheck Summary

## Current locked baseline

- HEAD `58f860e9578e6e5ad510dfaf5a5dfa43fd1e5140`
- evidence tag `baseline-v1.20-paid-warning-precheck-cli-evidence-2026-05-14`

## What was added

- warning-only paid quote/order precheck metadata for landscape-scale candidates
- no hard enforcement gate
- no scoring, suppression, threshold, polygonization, tile-scaling, export precision, or DB schema changes

## CLI evidence summary

- `paid-quote-create` succeeded
- `paid-quote-show` succeeded
- `paid-order-create` succeeded
- `paid-order-show` succeeded
- quote/order were not blocked by landscape-scale status

## Warning fields proven in CLI outputs

- `paid_landscape_scale_warning = true`
- `paid_landscape_scale_warning_code = landscape_scale_context_review_recommended`
- `paid_landscape_scale_context_review_recommended = true`
- `paid_landscape_scale_warning_message` includes:
  - `25 ha`
  - `paid imagery`
  - `warning-only`
  - `does not block quote/order`

## Current policy

- landscape-scale paid escalation remains allowed
- context review is recommended before paid imagery escalation
- warning is visible/auditable but not blocking

## Known limitations

- still no enforced context-review gate
- warning depends on operator/reviewer judgment
- no real-world object-scale nonzero candidate has been captured yet

## Next product decision

- keep warning-only as current default
- consider enforcement only after more real examples or paid-spend risk justifies it
- do not change scoring or suppression as part of paid warning work
