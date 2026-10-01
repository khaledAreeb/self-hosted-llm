# Spec Delta

## Purpose

Establishes how many people the deployment can serve at once for general-purpose work, measured on the configuration those people will actually use, so rollout and funding decisions rest on a measured capacity rather than on single-request speed.

## ADDED Requirements

### Requirement: Capacity is measured on the multi-user configuration

Capacity SHALL be measured on the serving configuration intended for multi-user use, not on the single-person evaluation configuration, and that configuration MUST bound GPU spend to one container.

#### Scenario: The configuration under test is the one users get

- **WHEN** a load test runs
- **THEN** the endpoint serves with the configuration that users will receive after the change, and the results record that configuration alongside them

#### Scenario: Load beyond capacity queues instead of adding a GPU

- **WHEN** more requests arrive than one container accepts at once
- **THEN** the excess waits for that container, and no second GPU container is started

### Requirement: Long-document accuracy is re-checked on the multi-user configuration

Moving the KV cache from BF16 to FP8 SHALL be kept only after long-document accuracy is re-checked against the retained BF16 results, and any loss MUST be recorded with the decision it led to.

#### Scenario: Accuracy holds

- **WHEN** the six phase-2 long-document tasks are re-run on FP8 and every answer meets its recorded criteria as well as it did on BF16
- **THEN** FP8 is kept and the comparison is recorded

#### Scenario: Accuracy drops

- **WHEN** any long-document answer on FP8 falls below its BF16 result
- **THEN** the loss is recorded task by task, and the configuration decision states explicitly which of accuracy and concurrency it favours and why

### Requirement: Workloads reflect general-purpose use

The load test SHALL exercise the kinds of traffic general-purpose use produces: interactive requests of mixed kinds, coding-agent traffic, and a long document arriving among interactive users.

#### Scenario: Interactive traffic is mixed

- **WHEN** the interactive workload runs
- **THEN** it draws from realistic chat, coding and report prompts rather than a single repeated prompt, so thinking length and answer length vary as they do in real use

#### Scenario: Coding-agent traffic is represented

- **WHEN** the agent-style workload runs
- **THEN** each request carries a large context that repeats across requests and asks for a short reply, as coding agents do

#### Scenario: A long document lands among interactive users

- **WHEN** one request of roughly 137,000 tokens arrives while interactive requests are in flight
- **THEN** the effect on the interactive requests' latency is measured and reported

### Requirement: Latency is reported as users experience it

Every load level SHALL report, at the median and 95th percentile: time to first token; time to first visible (non-thinking) token; per-request generation speed; and total request time. It SHALL also report aggregate throughput and the count of failed requests.

#### Scenario: Thinking is separated from the visible answer

- **WHEN** requests are served with reasoning on
- **THEN** time to first visible token is reported separately from time to first token, because a user sees nothing until thinking ends

#### Scenario: Failures are counted, not dropped

- **WHEN** any request errors, times out or returns an empty answer
- **THEN** it is counted in that load level's results and not excluded from the percentiles

### Requirement: The measurement method is validated before it is trusted

Load-test measurements SHALL agree with the existing single-request benchmark before any load result is relied on.

#### Scenario: Single-request agreement

- **WHEN** the load-test method measures one request at a time on a warm endpoint
- **THEN** its time to first token and generation speed are within 10% of the existing benchmark's figures on the same endpoint

#### Scenario: Disagreement

- **WHEN** the figures differ by more than 10%
- **THEN** the cause is found and fixed, or the method is replaced, before load results are recorded

### Requirement: "Usable" is defined before the results are seen

A latency target defining acceptable service SHALL be stated before the load test runs. Capacity MUST be reported as the highest tested concurrency that meets it, and the full measurements MUST be retained so a different target can be applied later.

#### Scenario: Capacity against the stated target

- **WHEN** results are summarised
- **THEN** capacity is given as the highest concurrency meeting the pre-stated target, with the target quoted next to it

#### Scenario: A different target is wanted later

- **WHEN** someone applies a stricter or looser target afterwards
- **THEN** the retained per-level measurements are enough to read off the new capacity without re-running the test

### Requirement: Concurrent requests are translated into users with stated assumptions

Capacity SHALL be translated from concurrent requests into numbers of people using explicit, recorded assumptions about how much of the time each kind of user is sending, and MUST NOT be presented as a single unconditional user count.

#### Scenario: Different kinds of user

- **WHEN** the user estimate is given
- **THEN** it is stated separately for interactive users and coding-agent users, each with the busy-fraction assumption it depends on

### Requirement: Slowdowns are explained from the server's side

The server's own counters (requests running, requests waiting, KV cache use and preemptions) SHALL be recorded throughout each load run, so that where latency degrades, the cause is identified.

#### Scenario: Latency degrades at a load level

- **WHEN** latency at one level is materially worse than at the level below
- **THEN** the report states whether requests were waiting, the KV cache was full, requests were preempted, or the GPU was compute-bound, citing the recorded counters

### Requirement: Speculative decoding is verified under load

Multi-token-prediction speculative decoding SHALL be compared on against off at high concurrency, and MUST be kept only if it helps at the concurrency real use produces.

#### Scenario: It stops helping under load

- **WHEN** MTP's throughput or latency advantage disappears or reverses at high concurrency
- **THEN** the result is recorded, and the setting chosen matches the concurrency expected in real use, with the reason stated

### Requirement: The load test is re-runnable

The workloads, commands and retained results SHALL allow the same load test to be repeated after any configuration or model change, and the results compared directly.

#### Scenario: A configuration changes later

- **WHEN** a later change alters the serving configuration or the model
- **THEN** the same load test runs from the documented commands and produces results in the same form as the retained ones

### Requirement: Spending is bounded and checked

Load testing SHALL stay within a $4 ceiling, with the balance read from the platform before each group of paid work.

#### Scenario: The ceiling would be exceeded

- **WHEN** the next group of work would take spend past the ceiling
- **THEN** that group is skipped and findings are written from what has been measured
