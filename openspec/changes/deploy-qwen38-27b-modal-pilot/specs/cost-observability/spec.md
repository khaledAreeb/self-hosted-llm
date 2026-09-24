# Spec Delta

## Purpose

Makes the deployment's own operating cost measurable, so that the pilot ends with a defensible forecast of what a production deployment would cost per month and per user, rather than an impression that the model worked well.

## ADDED Requirements

### Requirement: Duty cycle is measurable

The pilot SHALL produce a measurement of how many GPU-hours are actually consumed per working day under real team usage. This measurement is the primary input to the production cost forecast and MUST come from observed billing, not estimation.

#### Scenario: A pilot working day completes

- **WHEN** a day of team usage finishes
- **THEN** the GPU-hours billed for that day can be read from the platform's own cost reporting and attributed to that day

#### Scenario: Duty cycle is extrapolated to production

- **WHEN** the production forecast is prepared
- **THEN** it is derived from the measured ratio of billed GPU-hours to elapsed working hours, and states that ratio explicitly

#### Scenario: Idle cost is separated from serving cost

- **WHEN** duty cycle is reported
- **THEN** GPU time spent idle inside the scaledown window is distinguishable from GPU time spent actively generating

### Requirement: Per-user request and token attribution

The pilot SHALL record, for each request, the requesting user, a timestamp, and input and output token counts.

#### Scenario: A user sends requests over a pilot day

- **WHEN** a pilot user makes requests during the day
- **THEN** each request is recorded with that user's identity, its timestamp, and its token counts

#### Scenario: Per-user cost is derived

- **WHEN** the pilot reports cost per user
- **THEN** it is computed from recorded per-user usage combined with measured GPU-hours, not assumed to be an equal split

#### Scenario: Request arrival pattern is recoverable

- **WHEN** the gaps between consecutive requests are analysed
- **THEN** the recorded timestamps are sufficient to determine whether a shorter or longer idle window would reduce cost

### Requirement: Effective cost per token accounts for utilization

Reported cost per token SHALL be computed from GPU-hours divided by tokens actually produced, not from a nominal token price. The report MUST state the utilization level the figure assumes.

#### Scenario: Cost per token is reported

- **WHEN** an effective cost per million output tokens is quoted
- **THEN** it is accompanied by the utilization level it was measured at, because the figure varies by orders of magnitude between low and saturated utilization

#### Scenario: Comparison against hosted alternatives

- **WHEN** the pilot compares self-hosting against a hosted API
- **THEN** the comparison uses the measured effective cost per token and states data residency as the reason self-hosting may still be chosen at a higher price

### Requirement: Latency is measured

The pilot SHALL measure time to first token and sustained output tokens per second, separately for warm requests and for requests that trigger a cold start.

#### Scenario: A warm request is served

- **WHEN** a request is served by an already-running container
- **THEN** time to first token and output tokens per second are recorded

#### Scenario: A cold request is served

- **WHEN** a request triggers a container start
- **THEN** total cold start duration is recorded separately from the warm serving latency

#### Scenario: Latency informs the GPU decision

- **WHEN** the production recommendation names a GPU
- **THEN** it cites measured tokens per second rather than theoretical bandwidth figures

### Requirement: Budget consumption is visible before exhaustion

Remaining pilot budget SHALL be checkable at any time, and MUST be checked before each phase of the pilot so that the budget is not exhausted mid-trial.

#### Scenario: Operator checks remaining budget

- **WHEN** the operator wants to know how much budget remains
- **THEN** spend to date and remaining balance can be read from the platform's cost reporting

#### Scenario: A phase would exceed the remaining budget

- **WHEN** a planned pilot phase would cost more than the remaining balance
- **THEN** the phase is rescoped or deferred rather than started

#### Scenario: Unexpected spend appears

- **WHEN** cost accrues during a period with no expected user activity
- **THEN** it is detected by a budget check and investigated before more budget is lost

### Requirement: Quality is assessed against real company tasks

The pilot SHALL evaluate the model on a fixed set of representative tasks drawn from the company's actual work, recorded so the same set can be re-run against future configurations.

#### Scenario: The evaluation set is assembled

- **WHEN** the quality assessment is prepared
- **THEN** it consists of a written, fixed set of representative company tasks rather than ad hoc improvised prompts

#### Scenario: Results are recorded

- **WHEN** the model is run against the evaluation set
- **THEN** the outputs are retained so they can serve as the baseline for any later configuration change

#### Scenario: A future configuration is considered

- **WHEN** a cheaper or faster configuration is evaluated later
- **THEN** the same evaluation set is re-run and compared against the retained baseline
