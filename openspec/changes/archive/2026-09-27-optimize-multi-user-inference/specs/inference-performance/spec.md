# Spec Delta

## Purpose

Makes the deployment's throughput and latency under concurrent load measurable and attributable, so that serving configuration is chosen from evidence rather than from defaults or intuition, and so a configuration that makes things worse is detected rather than shipped.

## ADDED Requirements

### Requirement: A repeatable load test exists

The deployment SHALL have a load test that drives a configurable number of concurrent requests and reports throughput and latency. It MUST be re-runnable so that two configurations can be compared on equal terms.

#### Scenario: Load test is run at a given concurrency

- **WHEN** the load test is run with a specified number of concurrent requests
- **THEN** it reports aggregate output tokens per second, per-request tokens per second, and time to first token

#### Scenario: The same test is run twice on one configuration

- **WHEN** the load test is run twice without changing configuration
- **THEN** the results are close enough that a real improvement can be distinguished from run-to-run variance

#### Scenario: Prompts resemble real traffic

- **WHEN** the load test generates prompts
- **THEN** they include both short chat-style requests and long conversation-style requests with a shared prefix, because those two exercise decode and prefill very differently

### Requirement: A baseline is recorded before any tuning

A baseline SHALL be measured and recorded on the current configuration before any optimization flag is changed. Later results MUST be compared against it.

#### Scenario: Baseline is captured

- **WHEN** the baseline run completes
- **THEN** throughput and latency at each tested concurrency level are recorded, together with the exact serving flags in force

#### Scenario: An optimization is evaluated

- **WHEN** a configuration change is assessed
- **THEN** it is compared against the recorded baseline at the same concurrency levels, not against an impression or an earlier ad-hoc measurement

### Requirement: Already-active optimizations are identified before being enabled

The active serving configuration SHALL be determined from the running server before flags are added. Enabling something already on MUST NOT be reported as an improvement.

#### Scenario: Checking whether prefix caching is active

- **WHEN** the current configuration is inspected
- **THEN** whether prefix caching is already enabled is established from the server's own startup output or configuration, not assumed from documentation

#### Scenario: A flag turns out to be a default

- **WHEN** an intended optimization is found to be enabled by default
- **THEN** that is recorded, and the flag is not claimed as a change that produced a gain

### Requirement: Speculative decoding is evaluated against acceptance rate

Multi-token-prediction speculative decoding SHALL be evaluated using the model's `mtp` head. Its acceptance rate MUST be observed, because low acceptance makes speculative decoding slower rather than faster.

#### Scenario: Speculative decoding is enabled

- **WHEN** the server runs with MTP speculative decoding
- **THEN** the observed acceptance rate is recorded alongside the throughput result

#### Scenario: Acceptance rate is too low to help

- **WHEN** measured throughput with speculative decoding is no better than the baseline
- **THEN** the feature is disabled and the outcome recorded, rather than retained on the strength of its published acceptance figure

### Requirement: Prefix caching is evaluated on repeated-prefix traffic

Prefix caching SHALL be evaluated with traffic that repeats a long prefix, since that is the pattern agent and chat clients actually produce and the only pattern where caching can help.

#### Scenario: Repeated-prefix requests are issued

- **WHEN** several requests share a long common prefix
- **THEN** the effect on prompt throughput and time to first token is measured against the baseline

#### Scenario: Caching competes with concurrency

- **WHEN** prefix caching is active
- **THEN** its effect on the number of concurrent requests the GPU can serve is checked, because cached prefixes occupy KV cache that would otherwise hold other users' conversations

### Requirement: Every change is kept only if measurement supports it

A configuration change SHALL be retained only when measurement shows it helps, and reverted otherwise. The final configuration MUST consist only of changes with recorded supporting evidence.

#### Scenario: A change does not improve results

- **WHEN** a configuration change measures no better than the baseline
- **THEN** it is reverted, and the negative result is recorded so it is not retried without new evidence

#### Scenario: A change helps one workload and harms another

- **WHEN** a change improves one traffic pattern but degrades another
- **THEN** the trade-off is recorded explicitly and the decision states which workload was prioritised and why

### Requirement: Spending is bounded by an explicit stop rule

Measurement SHALL operate within a stated budget ceiling, and the remaining balance MUST be checked before each run.

#### Scenario: Budget is checked before a run

- **WHEN** a measurement run is about to start
- **THEN** the remaining balance is read from the platform's cost reporting and recorded

#### Scenario: The ceiling is reached

- **WHEN** spending on this change reaches its stated ceiling
- **THEN** measurement stops and the best configuration found so far is adopted, rather than continuing to tune

#### Scenario: Measurements are batched into warm windows

- **WHEN** several configurations are compared
- **THEN** runs are grouped to reuse a warm container where possible, because a cold start costs roughly five minutes of GPU time
