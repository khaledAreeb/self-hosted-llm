# Spec Delta

## Purpose

Establishes what the deployed model is actually good and bad at across the company's real work, measured at full context and recorded reproducibly, so that funding decisions and future configuration changes rest on evidence rather than on smoke tests.

## ADDED Requirements

### Requirement: The deployment serves its full native context

The endpoint SHALL accept requests up to 250,000 tokens, within the model's 262,144 native limit so that no rope scaling is required.

#### Scenario: A long document is submitted

- **WHEN** a request approaching 250,000 tokens is sent
- **THEN** it is accepted and answered rather than rejected for length

#### Scenario: A request exceeds the configured limit

- **WHEN** a request exceeds 250,000 tokens
- **THEN** a clear context-length error is returned rather than an out-of-memory failure

#### Scenario: Memory is verified before evaluation begins

- **WHEN** the deployment starts at the full configured context
- **THEN** the KV cache allocates successfully and the server reaches a serving state, confirmed before any evaluation work depends on it

### Requirement: KV cache precision is chosen for fidelity, and the choice is recorded

The KV cache SHALL use BF16 for this evaluation, and the reason MUST be recorded so the trade-off is visible to whoever later optimises for throughput.

#### Scenario: Long-context work is evaluated

- **WHEN** the model is assessed on long-document tasks
- **THEN** it runs with the higher-fidelity KV cache, so that any weakness observed is attributable to the model rather than to a throughput setting

#### Scenario: The concurrency cost is stated

- **WHEN** the configuration is recorded
- **THEN** the resulting reduction in concurrent full-length sequences is stated explicitly alongside the fidelity reason

### Requirement: An evaluation set covers the company's real use cases

A fixed evaluation set SHALL exist covering coding, report writing, long-document reasoning, and vision. Each entry MUST be a concrete task rather than a generic prompt, and the set MUST be re-runnable.

#### Scenario: The set is assembled

- **WHEN** the evaluation set is written
- **THEN** it contains tasks drawn from work the company actually does, and each states what a good answer would look like

#### Scenario: Vision is covered

- **WHEN** the set is assembled
- **THEN** it includes at least one image task, because this is the only model in the fleet that accepts images and that capability is otherwise untested

#### Scenario: Long context is genuinely exercised

- **WHEN** the set is assembled
- **THEN** at least one task supplies a document long enough to exercise context beyond what a short prompt would, since long-context behaviour is the main reason for this configuration

### Requirement: Results are recorded well enough to be compared later

Every evaluation run SHALL retain its outputs and the exact configuration that produced them, so a later run can be compared against it.

#### Scenario: A run completes

- **WHEN** the evaluation set is run
- **THEN** the outputs are retained together with the serving flags, model identifier and date

#### Scenario: A future configuration is assessed

- **WHEN** a later change alters the model or its configuration
- **THEN** the same set can be re-run and compared against the retained outputs

#### Scenario: Findings are stated plainly

- **WHEN** results are summarised
- **THEN** both strengths and weaknesses are recorded, including any use case the model handles poorly

### Requirement: Speculative decoding is verified, not assumed

Multi-token-prediction speculative decoding SHALL be enabled and its effect observed. It MUST be removed if it does not help, since low acceptance makes it slower rather than faster.

#### Scenario: Speculative decoding is active

- **WHEN** the server runs with the MTP head enabled
- **THEN** its acceptance rate is observed and recorded rather than taken from published figures

#### Scenario: It does not improve throughput

- **WHEN** measured throughput is no better than without it
- **THEN** it is disabled and the negative result recorded

### Requirement: Spending is bounded and checked

Evaluation SHALL operate within a stated budget ceiling, with the remaining balance checked before each phase of work.

#### Scenario: A run is about to start

- **WHEN** a group of evaluation work begins
- **THEN** the remaining balance is read from the platform's cost reporting and recorded

#### Scenario: The ceiling is reached

- **WHEN** spending reaches the stated ceiling
- **THEN** work stops and findings are written from what has been gathered, rather than continuing

#### Scenario: Cold starts are amortised

- **WHEN** multiple evaluation tasks are run
- **THEN** they are batched into as few warm windows as possible, since a cold start at this context length costs several minutes of GPU time
