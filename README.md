# LDA

LDA is an E2B-only Campaign Controller for optimizing Ubuntu 26.04 packages. Each selected
package is one Mission and one isolated E2B Sandbox. Inside it, pinned Humanize2 runs a
resumable Builder/Reviewer Flow: the Builder keeps `agent.new()` across rounds, every Reviewer
turn is fresh and Pydantic-structured, programmatic Hard Fences run before and after review,
and only the combined evidence can accept a candidate.

## Start a real Campaign

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
export E2B_API_URL=https://e2b.fact-lab.work
export E2B_SANDBOX_URL="$E2B_API_URL"
export E2B_API_KEY='provided-out-of-band'
export E2B_ACCESS_TOKEN=dummy
export ANTHROPIC_API_KEY='provided-out-of-band'
lda-flow campaign campaigns/ubuntu2604-core-libs.yaml --output artifacts/core-libs
```

Run an individual E2B Mission action when debugging a package configuration:

```bash
lda-flow mission prepare mission.json
lda-flow mission build mission.json
lda-flow mission verify mission.json
```

Build and verify the pinned base template from a credentialed environment:

```bash
python templates/lda-base/build.py
python templates/lda-base/verify.py
```

Inspect selection without creating a Sandbox:

```bash
lda-flow campaign campaigns/ubuntu2604-core-libs.yaml --dry-run
```

The two packages in the checked-in Campaign are `libpng1.6` and `libaio`. Their package
metadata, ABI, header, FFI, upstream self-test, dependency consumer, protected paths, source
allowlist, CPU policy, trace, micro benchmark, and package E2E commands are explicit YAML
data. Hard Fences cannot be disabled through configuration.

The controller requires E2B and a forwarded model credential for a real run. It does not
fall back to Docker or the host. Each accepted Mission produces a local report, downloaded
candidate packages, a trace audit input, and an E2B snapshot ID; the Campaign then uses clean
official and candidate peer Sandboxes for portfolio benchmarks.
