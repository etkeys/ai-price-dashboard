# GitHub Actions Build & Publish Specification — ai-price-dashboard

Task: t_9bdfd1e2 (research). Downstream implementer: t_d398c4b1 (dale). Reviewer: t_37152b3a (kova).
Root task: t_cb278371.
Reference workflow: https://raw.githubusercontent.com/etkeys/videodl/refs/heads/main/.github/workflows/build-on-release.yml
Target file: `.github/workflows/build-and-publish.yml`

This document specifies the triggers, tag logic, Tailscale setup, and certificate
trust steps. It is a build guide, not finished code — Dale writes the YAML.

---

## 1. What the reference workflow actually does

Read verbatim from the videodl repo on 2026-07-27. Facts, not assumptions:

- Trigger: `on: release: types: [released]` only. No PR trigger exists there.
- `permissions: contents: write` (needed because it uploads release assets).
- Single job `build-and-upload` on `ubuntu-latest`.
- Step order (this ordering matters, see §5.3):
  1. `tailscale/github-action@v4` with `oauth-client-id` / `oauth-secret` secrets and `tags: tag:ci`
  2. Write `secrets.REGISTRY_CERT` to `/usr/local/share/ca-certificates/cr.etkeys.xyz.crt`,
     run `update-ca-certificates`, then `systemctl restart docker`
  3. `actions/checkout@v3`
  4. Version-stamping via `sed` into source files
  5. `docker/setup-buildx-action@v2`
  6. `docker build -t cr.etkeys.xyz:31500/videodl-web -f web.dockerfile .`
  7. `docker save | gzip` into a tarball
  8. `softprops/action-gh-release@v2` uploads the tarballs as release assets
  9. `docker login -u ... -p ... cr.etkeys.xyz:31500`
  10. `docker push cr.etkeys.xyz:31500/videodl-web:latest`

Known weaknesses in the reference that we should NOT copy verbatim:

- It builds `-t <image>` with no tag (implicitly `:latest`) and pushes only `:latest`.
  Releases become unaddressable by version. Our task explicitly requires a versioned tag.
- `docker login -p "<secret>"` puts the password on the command line. Use
  `--password-stdin` instead.
- Pinned to older action majors (`checkout@v3`, `setup-buildx-action@v2`).
  Use `checkout@v4` and `setup-buildx-action@v3`.
- No test step at all. Our root task says "test and build", so we add pytest.

## 2. Triggers

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened]
  release:
    types: [published]
```

Rationale:

- `pull_request` default types are exactly `opened, synchronize, reopened`. Listing
  them explicitly is self-documenting and prevents surprise if defaults change.
  Do NOT add `closed` (nothing to build) or `edited` (title/body edits, not code).
- Root task says "when a release is released". Two candidate event types:
  - `released` — fires for a non-prerelease publish, and also when a prerelease is
    later promoted to a full release. Does NOT fire for prereleases.
  - `published` — fires for any publish, prerelease included.
  The decomposed implementation task (t_d398c4b1) explicitly says
  "on release published", so use `published`. This is a deliberate divergence from
  the reference workflow, and it means prereleases (e.g. `v1.2.0-rc1`) also produce
  a pushed image — which is desirable, since the tag string carries the prerelease
  marker and won't collide with the final release tag.

`permissions`: the reference needs `contents: write` to upload release assets.
We are not uploading assets (see §6), so the job needs only `contents: read`.
Declare it explicitly at workflow level:

```yaml
permissions:
  contents: read
```

## 3. Image tagging

Registry / repository: `cr.etkeys.xyz:31500/ai-price-dashboard`

| Event | Tag | Example |
|---|---|---|
| `release: published` | `<version>` from the git tag | `cr.etkeys.xyz:31500/ai-price-dashboard:v0.1.0` |
| `release: published` | also `latest` | `cr.etkeys.xyz:31500/ai-price-dashboard:latest` |
| `pull_request` | `pr-<number>` | `cr.etkeys.xyz:31500/ai-price-dashboard:pr-42` |

Notes:

- `<version>` is the release tag name verbatim: `github.event.release.tag_name`.
  Do not strip a leading `v` — keeping it verbatim makes the image tag match the
  git tag exactly, which is what an operator will look for. (The reference derives
  the tag by `cut`-ing `github.ref`; `github.event.release.tag_name` is the direct,
  correct field for a release event and needs no parsing.)
- `latest` should move only on releases, never on PR builds.
- `pr-<number>` uses `github.event.pull_request.number` (also available as
  `github.event.number` for PR events; prefer the explicit path).
- The `pr-` prefix is the "test build" signifier required by the root task. It is
  unambiguous, sorts away from semver tags, and is trivially cleanable by a registry
  GC policy matching `^pr-\d+$`.
- The `pr-<n>` tag is intentionally mutable: each push to the PR overwrites it, so
  the tag always reflects the PR head. If immutability per-commit is later wanted,
  add a second tag `pr-<n>-<short-sha>`; out of scope for this task.

### 3.1 Tag computation

Compute both the tag list and a "should we push" flag in one step, writing to
`$GITHUB_OUTPUT` (never `set-output`, which is deprecated and disabled):

```yaml
- name: Compute image tags
  id: meta
  run: |
    IMAGE=cr.etkeys.xyz:31500/ai-price-dashboard
    if [ "${{ github.event_name }}" = "release" ]; then
      VERSION="${{ github.event.release.tag_name }}"
      echo "tags=${IMAGE}:${VERSION},${IMAGE}:latest" >> "$GITHUB_OUTPUT"
    else
      echo "tags=${IMAGE}:pr-${{ github.event.pull_request.number }}" >> "$GITHUB_OUTPUT"
    fi
```

If Dale uses `docker/build-push-action`, the `tags:` input accepts that
comma-separated list directly. If Dale uses raw `docker build`, expand it into
repeated `-t` flags instead. Either is acceptable; `docker/build-push-action@v6`
is preferred because it handles multi-tag build + push in one step and supports
GitHub Actions layer caching (`cache-from: type=gha`, `cache-to: type=gha,mode=max`).

## 4. Tailscale in the runner

Use the official action. Current release as of 2026-07-27 is `v4.1.3`; the floating
major tag `v4` exists and is what the reference uses.

```yaml
- name: Connect to Tailscale
  uses: tailscale/github-action@v4
  with:
    oauth-client-id: ${{ secrets.TAILSCALE_OAUTH_CLIENT_ID }}
    oauth-secret: ${{ secrets.TAILSCALE_OAUTH_SECRET }}
    tags: tag:ci
```

Verified facts about `tailscale/github-action@v4` (read from its `action.yml`):

- Runs on `node24`, has a `post` step that logs out automatically at job end.
  No manual `tailscale logout` cleanup step is needed.
- Inputs available: `authkey` (deprecated), `oauth-client-id`, `oauth-secret`,
  `audience`, `tags`, `version` (default `1.94.2`, accepts `latest`/`unstable`),
  `args`, `tailscaled-args`, `hostname`, `timeout` (default `2m`), `retry`
  (default `5`), `use-cache` (default `true`), `statedir`, `sha256sum`, `ping`.
- `tags` is mandatory in practice when using an OAuth client: the OAuth client must
  hold the `auth_keys` scope and every tag listed here must be owned by that client.
- The action installs and starts `tailscaled` itself; do not hand-roll an
  `apt-get install tailscale` sequence.

Optional hardening Dale may add, cheap and worth it:

- `ping: cr.etkeys.xyz` — the action will `tailscale ping` the host after `up`
  completes, so a tailnet/ACL problem fails fast with a clear message instead of
  surfacing later as an opaque `docker push` timeout.
- Pin to `tailscale/github-action@v4.1.3` instead of `@v4` if the team prefers exact
  action pinning. Reference repo uses the floating major; either is defensible.
  Recommendation: use `@v4` for parity with the existing repo convention.

Secret names: `TAILSCALE_OAUTH_CLIENT_ID` and `TAILSCALE_OAUTH_SECRET`, matching the
reference workflow. The root task states repository secrets are already defined;
**Dale must not rename them.** If a secret turns out to be missing, that is a blocker
for the operator, not something to work around.

## 5. Trusting the private registry certificate

`cr.etkeys.xyz:31500` presents a certificate the runner does not trust by default.
Two distinct trust stores are involved and both matter.

### 5.1 System CA store

```yaml
- name: Trust private registry certificate
  run: |
    printf '%s\n' "${{ secrets.REGISTRY_CERT }}" \
      | sudo tee /usr/local/share/ca-certificates/cr.etkeys.xyz.crt > /dev/null
    sudo update-ca-certificates
```

Points of care:

- The file **must** end in `.crt` and live under `/usr/local/share/ca-certificates/`
  — `update-ca-certificates` ignores any other extension. The reference gets this right.
- Add `> /dev/null` after `tee`. The reference omits it, which echoes the certificate
  into the build log. A public cert is not a secret, but if `REGISTRY_CERT` is stored
  as a repository secret GitHub will mask it anyway; suppressing output avoids a log
  full of `***` noise and removes any doubt.
- Use `printf '%s\n'` rather than `echo` so a cert whose content begins with `-` or
  contains backslashes is not mangled by `echo` builtin quirks.
- The step is idempotent: rewriting the same path and re-running
  `update-ca-certificates` is safe on repeat runs.

### 5.2 Docker daemon trust

The Docker daemon does **not** read the system CA store at request time for registry
TLS on an already-running daemon; it must be restarted to pick up the refreshed bundle:

```yaml
    sudo systemctl restart docker
```

This is what the reference does and it works on `ubuntu-latest`, where Docker runs as
a systemd service. Keep it.

An alternative that avoids the restart is the per-registry cert directory:

```
/etc/docker/certs.d/cr.etkeys.xyz:31500/ca.crt
```

Docker reads that path per-pull/push with no daemon restart. It is arguably cleaner,
but the directory name contains a colon and the daemon-restart form is already proven
in the reference. **Recommendation: keep `systemctl restart docker`** for parity, and
note the `certs.d` alternative here in case the restart ever becomes a problem.

### 5.3 Step ordering — important

The certificate step must run **before** any `docker login`, `docker push`, or
buildx builder creation that talks to the registry. It should also run before or
alongside the Tailscale step — the reference does Tailscale first, then cert trust,
then everything else. Preserve that order.

Also note: `systemctl restart docker` destroys any buildx builder created before it.
So the order must be: Tailscale → cert trust + docker restart → `setup-buildx-action`
→ build. The reference happens to satisfy this. Dale must not reorder them.

## 6. Registry login and push

```yaml
- name: Log in to private registry
  run: |
    printf '%s' "${{ secrets.REGISTRY_PASSWORD }}" \
      | docker login cr.etkeys.xyz:31500 \
          -u "${{ secrets.REGISTRY_USER }}" --password-stdin
```

- Use `--password-stdin`, not `-p "<secret>"`. The reference uses `-p`, which places
  the password in the process argument list where any process on the runner can read
  it via `/proc`. This is a deliberate improvement over the reference.
- Secret names `REGISTRY_USER` / `REGISTRY_PASSWORD` / `REGISTRY_CERT` match the
  reference. Do not rename.
- Push both computed tags for a release; push the single `pr-<n>` tag for a PR.
- Optional but tidy: a final `docker logout cr.etkeys.xyz:31500` step with
  `if: always()`.

**No release-asset upload.** The reference does `docker save | gzip` and attaches
tarballs with `softprops/action-gh-release@v2`. Neither the root task (t_cb278371) nor
the implementation task (t_d398c4b1) asks for this, and it is the only reason the
reference needs `contents: write`. Omit it and keep `permissions: contents: read`.
If Erik later wants the tarball, it is an additive change.

## 7. Test step

The root task title is "test and build". The repo has a real pytest suite
(`tests/` with `test_cli.py`, `test_config.py`, `test_main.py`,
`test_models_listing.py`, `test_run.py`) and `pyproject.toml` declares a
`dev` extra of `pytest>=8.0.0`, `pytest-cov>=5.0.0` with
`[tool.pytest.ini_options] testpaths = ["tests"]`.

Recommended shape — a separate `test` job that the `build` job depends on:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip
      - run: pip install -e ".[dev]"
      - run: pytest

  build-and-publish:
    needs: test
    runs-on: ubuntu-latest
    ...
```

Rationale for splitting:

- The test job needs no Tailscale, no cert, no registry credentials. Keeping it
  separate means a plain unit-test failure never touches the tailnet or secrets.
- `needs: test` gates publication on a green suite for both PRs and releases.
- Python 3.11 matches `requires-python = ">=3.11"` and the Dockerfile's
  `python:3.11-slim` base.

## 8. Recommended final job structure

```
job: test
  1. actions/checkout@v4
  2. actions/setup-python@v5   (3.11, pip cache)
  3. pip install -e ".[dev]"
  4. pytest

job: build-and-publish   (needs: test)
  1. tailscale/github-action@v4        (oauth id/secret, tags: tag:ci)
  2. Trust registry cert + update-ca-certificates + systemctl restart docker
  3. actions/checkout@v4
  4. Compute image tags -> $GITHUB_OUTPUT  (§3.1)
  5. docker/setup-buildx-action@v3
  6. Log in to cr.etkeys.xyz:31500 via --password-stdin
  7. docker/build-push-action@v6  (context: ., push: true, tags: from step 4,
                                   cache-from/to: type=gha)
```

Step 3 (checkout) after steps 1–2 mirrors the reference; it is harmless because
nothing before it reads the repo.

## 9. Things Dale must NOT do

- Do not rename any secret. `TAILSCALE_OAUTH_CLIENT_ID`, `TAILSCALE_OAUTH_SECRET`,
  `REGISTRY_CERT`, `REGISTRY_USER`, `REGISTRY_PASSWORD` are already defined on the
  repository.
- Do not `echo` a secret to stdout in any step.
- Do not push `latest` from a pull request build.
- Do not create the buildx builder before the `systemctl restart docker`.
- Do not add `pull_request_target`. It runs with repo secrets in the context of the
  base branch and would hand write-capable registry credentials to any fork PR.
  `pull_request` is correct here.
- Do not use `set-output`; it is disabled. Use `$GITHUB_OUTPUT`.

### 9.1 Open risk for the operator, not for Dale

A `pull_request` build pushes an image using real registry credentials. On a
**public** repository, a PR from a fork does not receive secrets, so the Tailscale
and login steps will fail — the build job will simply go red on fork PRs. On a
**private** repository this is a non-issue. If `etkeys/ai-price-dashboard` is public
and fork PRs are expected, the build job should carry a guard such as:

```yaml
if: github.event_name == 'release' || github.event.pull_request.head.repo.full_name == github.repository
```

I could not verify the repository's visibility from this environment (`gh` is not
authenticated here). Flagging it rather than guessing. If in doubt, adding the guard
above is harmless on a private repo.

## 10. Acceptance criteria for review (t_37152b3a)

1. File exists at `.github/workflows/build-and-publish.yml` and is valid YAML.
2. `on:` contains `pull_request` (opened/synchronize/reopened) and
   `release: types: [published]`.
3. Workflow- or job-level `permissions` is `contents: read`.
4. A `test` job runs pytest on Python 3.11 and the build job declares `needs: test`.
5. Tailscale step uses `tailscale/github-action@v4` with the two OAuth secrets and
   `tags: tag:ci`.
6. Cert step writes to `/usr/local/share/ca-certificates/cr.etkeys.xyz.crt`, runs
   `update-ca-certificates`, restarts docker, and does not print the cert to the log.
7. Buildx setup occurs after the docker restart.
8. Release builds tag `cr.etkeys.xyz:31500/ai-price-dashboard:<release tag_name>`
   and `:latest`.
9. PR builds tag `cr.etkeys.xyz:31500/ai-price-dashboard:pr-<pr number>` and never
   `:latest`.
10. `docker login` uses `--password-stdin`; no secret appears in an argv position.
11. No secret is echoed to stdout anywhere in the workflow.
12. Existing secret names are used unchanged.

