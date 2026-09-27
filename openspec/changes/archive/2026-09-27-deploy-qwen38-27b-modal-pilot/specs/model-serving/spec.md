# Spec Delta

## Purpose

Provides an on-demand, authenticated inference endpoint for a self-hosted large language model, so that company teams can use it without prompts leaving infrastructure the company controls. The endpoint costs nothing while nobody is using it.

## ADDED Requirements

### Requirement: OpenAI-compatible inference API

The endpoint SHALL expose an OpenAI-compatible chat completions API so that any standard OpenAI client can call it without custom integration code.

#### Scenario: Standard client sends a chat completion request

- **WHEN** an authorized client POSTs a well-formed chat completion request naming the served model
- **THEN** the endpoint returns a response in the OpenAI chat completion schema, containing generated text and token usage counts

#### Scenario: Client requests the model list

- **WHEN** an authorized client requests the models listing
- **THEN** the endpoint returns the served model identifier in OpenAI list schema

#### Scenario: Client requests an unknown model

- **WHEN** an authorized client requests a model name the endpoint does not serve
- **THEN** the endpoint returns an error identifying the requested model as unavailable, and does not silently substitute the served model

### Requirement: Served model identity and precision

The endpoint SHALL serve the publisher's official FP8 checkpoint of Qwen3.8-27B. The deployment MUST NOT perform its own quantization of the model weights.

#### Scenario: Deployed model matches the specified checkpoint

- **WHEN** the deployment is started
- **THEN** the loaded weights are the publisher's official FP8 checkpoint, and the model identifier reported by the API corresponds to that checkpoint

#### Scenario: Quality baseline is the unquantized reference

- **WHEN** output quality is assessed during the pilot
- **THEN** it is assessed against the official FP8 checkpoint as the baseline, with no locally quantized variant introduced as a confounding variable

### Requirement: Unauthenticated requests are rejected before compute starts

The endpoint SHALL reject requests that do not carry valid credentials, and that rejection MUST occur before any GPU container is started. An unauthenticated request MUST NOT cause billable compute.

#### Scenario: Request arrives with no credentials

- **WHEN** an HTTP request reaches the endpoint URL without valid credentials
- **THEN** the request is rejected with an authentication error, and no GPU container is started

#### Scenario: Request arrives with invalid credentials

- **WHEN** an HTTP request reaches the endpoint URL with malformed or revoked credentials
- **THEN** the request is rejected with an authentication error, and no GPU container is started

#### Scenario: Endpoint URL is discovered by an unauthorized party

- **WHEN** an unauthorized party obtains the endpoint URL and sends traffic to it
- **THEN** no GPU time is consumed and no charge is incurred, regardless of request volume

### Requirement: Scale to zero when idle

The service SHALL release its GPU after a bounded idle period and SHALL start automatically on the next authorized request. It MUST NOT hold a GPU on a fixed schedule.

#### Scenario: Idle period elapses with no requests

- **WHEN** no authorized request is received for longer than the configured idle window
- **THEN** the GPU container shuts down and GPU billing for that container stops

#### Scenario: Request arrives while scaled to zero

- **WHEN** an authorized request arrives with no container running
- **THEN** a container starts, loads the model, serves the request, and returns a valid response

#### Scenario: Overnight and weekend idleness

- **WHEN** a full night or weekend passes with no authorized user request
- **THEN** the accrued GPU cost for that period is zero

### Requirement: Model weights are cached across container starts

Model weights SHALL be downloaded once and reused by subsequent container starts. A cold start MUST NOT re-download the weights.

#### Scenario: First-time setup

- **WHEN** the model is fetched for the first time
- **THEN** the weights are written to persistent storage that survives container shutdown

#### Scenario: Cold start after weights are cached

- **WHEN** a container starts and cached weights are present
- **THEN** the container loads weights from the cache without network download of the model

#### Scenario: Compilation artifacts are reused

- **WHEN** a container starts after a previous container has already compiled the model for this GPU
- **THEN** cached compilation artifacts are reused rather than regenerated

### Requirement: Bounded context length

The endpoint SHALL serve a context length bounded well below the model's native maximum, so that key-value cache reservation leaves room for concurrent requests on a single GPU.

#### Scenario: Context bound is configured

- **WHEN** the server starts
- **THEN** the maximum context length is set to an explicit bounded value rather than the model's native maximum

#### Scenario: Request exceeds the configured bound

- **WHEN** a request's combined prompt and requested output exceed the configured context bound
- **THEN** the endpoint returns a clear context-length error rather than failing with an out-of-memory condition

### Requirement: Streaming responses

The endpoint SHALL support incremental token streaming, so that users see output as it is produced rather than waiting for the complete response.

#### Scenario: Client requests a streamed completion

- **WHEN** an authorized client requests a chat completion with streaming enabled
- **THEN** tokens are delivered incrementally as they are generated

#### Scenario: Client requests a non-streamed completion

- **WHEN** an authorized client requests a chat completion without streaming
- **THEN** the complete response is returned in a single message

### Requirement: Cold start is allowed to complete

The service SHALL permit model loading to finish before declaring a start failure. The startup allowance MUST exceed the observed cold start duration for this model.

#### Scenario: Container start takes several minutes

- **WHEN** a container is loading a multi-gigabyte model and has not yet become ready
- **THEN** the platform continues waiting until the configured startup allowance elapses, rather than killing and retrying the container

#### Scenario: Container genuinely fails to start

- **WHEN** a container fails to become ready within the startup allowance
- **THEN** the failure is surfaced with diagnostic output identifying the cause
