# V1.20 Reviewer Readiness Closeout Summary

## Current locked baseline

- HEAD `e89ce65deb2ddda409afbdd98b21d918f5d1e5c6`
- evidence tag `baseline-v1.20-closeout-decision-path-cli-evidence-2026-05-13`

## What this closeout adds beyond the prior field-trial summary

- landscape-scale closeout decision-path metadata
- aggregate closeout summary fields
- real CLI evidence for unresolved, approved, and watch paths

## Evidence values from CLI closeout run

- before decisions:
  - status `warn`
  - landscape_scale_candidate_count `2`
  - landscape_scale_unresolved_count `2`
  - landscape_scale_closeout_ready `false`
  - unresolved path `landscape_scale_unresolved`
- after decisions:
  - status `warn`
  - landscape_scale_candidate_count `2`
  - landscape_scale_approved_for_archive_quote_count `1`
  - landscape_scale_watch_count `1`
  - landscape_scale_closeout_requires_context_review_count `1`
  - landscape_scale_closeout_ready `true`
  - approved path `landscape_scale_paid_escalation_requires_context_review`
  - watch path `landscape_scale_watch`

## Current product truth

- closeout now distinguishes ordinary unresolved review from landscape-scale decision-path readiness
- approved landscape-scale candidates explicitly require separate landscape/context review before paid imagery escalation
- watch landscape-scale candidates are treated as deferred context follow-up
- no scoring, filtering, threshold, polygonization, tile-scaling, export precision, or DB schema changes were made

## Known limitations

- landscape-scale review is still guidance/metadata, not a hard enforcement gate
- watch remains an unresolved review state, so closeout can remain `warn` even when landscape-scale `closeout_ready` is `true`
- no real-world object-scale nonzero candidate has been captured yet

## Next product decision

- decide whether landscape-scale context review should remain guidance only or become an enforced gate before paid imagery escalation
- do not change scoring or suppression until that decision is made
