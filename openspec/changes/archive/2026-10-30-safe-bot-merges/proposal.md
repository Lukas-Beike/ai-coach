# Proposal

## Why

Dependabot and release pull requests can wait indefinitely for a Gitar check that is not produced for them. The release app currently bypasses the entire Default ruleset, so using it for direct merges without first restricting that exemption would bypass required protections.

## What Changes

- Permit narrowly identified bot pull requests to request a direct squash merge as the release app, bound to the evaluated head.
- Preserve required checks, review-thread resolution, release test sequencing, and human Gitar review.
- Retry when relevant state changes and provide bounded recovery for missed events.
- Document and verify the actual ruleset configuration and hosted merge behavior.

## Capabilities

### Modified Capabilities

- `build-release-and-deployment`: Safe bot merges and their protected-branch gates.

## Impact

GitHub Actions workflows, the release app's ruleset exemptions, workflow regression tests, and repository guidance. No application data or provider synchronization is affected.
