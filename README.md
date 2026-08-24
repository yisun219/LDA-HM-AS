# Humanize Flow

Independent, backend-neutral Humanize scaffold. It owns orchestration state and
artifacts; it does not invoke an LLM or mutate a target project.

Stages: `Setup -> Gen-Idea -> Gen-Plan -> Implementation -> Regular Review ->
Full Alignment -> Code Review -> Finalize -> Methodology Analysis -> Complete`.
Stalled or regressed rounds enter `Drift Recovery`; three consecutive stalls trip
the circuit breaker.

```sh
./humanize init . --goal 'the work'
./humanize idea . --primary 'direction' --alternative 'other'
./humanize plan . --file plan.json --approve
./humanize round . --lane mainline --objective 'bounded step'
./humanize builder-stop . --summary 'artifact and tests are ready'
./humanize review . --verdict ADVANCED --summary 'independent review'
./humanize status .
```

State is atomically checkpointed in `.humanize/state.json`; immutable-ish artifacts
and an append-only event log live below `.humanize/`. A persistent Builder session
id and a fresh Reviewer session id are recorded per round.

