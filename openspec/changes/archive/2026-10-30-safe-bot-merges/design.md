# Design

## Context

The release app is integration 4772643. It is exempt from both the isolated Gitar ruleset and the Default ruleset; the latter includes required checks and review-thread resolution. The existing release workflow starts or finds a test before enabling auto-merge. Direct use of the app before correcting the broad exemption can bypass those protections.

## Goals / Non-Goals

**Goals:** Preserve GitHub's enforcement of non-Gitar protections and release sequencing while enabling narrowly identified bot merges.

**Non-Goals:** Change human review requirements, bypass failing checks, publish a release, or execute pull request code with privileged credentials.

## Decisions

- Identify PRs by GitHub-controlled author, same-repository head, and target branch; require expected release branch names only as an additional restriction.
- Attempt a direct squash merge with the evaluated head SHA. GitHub's protected-branch enforcement remains the final authority. An explicit repository variable keeps the workflow disabled until an administrator has removed and verified any non-Gitar bypass.
- Run trusted automation on relevant PR, check, and review-thread state changes, with scheduled recovery. Serialize merge attempts and re-read current PR state before each attempt.
- Preserve the release workflow's explicit test dispatch and require a successful GitHub Actions test on the current head or GitHub's current test-merge commit before a release merge attempt. GitHub enforces the applicable current required checks at merge time.

## Risks / Trade-offs

- GitHub returns `bypass_actors` only to a caller with write access to the ruleset. Do not grant the merge identity ruleset administration. The administrator must verify the deployment gate and repeat that check after ruleset changes.
- The observed GitHub auto-merge bypass behavior does not establish direct-merge behavior. Verify positive and negative cases in the repository before claiming delivery.
- Removing the broad Default exemption can affect existing automation. Audit its operations and sequence the configuration change with the workflow rollout.
