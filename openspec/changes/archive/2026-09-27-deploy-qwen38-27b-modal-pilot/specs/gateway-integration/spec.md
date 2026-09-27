# Spec Delta

## Purpose

Mediates all team access to the self-hosted model through the company's existing LLM gateway, so that users authenticate with familiar per-user keys while the gateway holds the backend credentials and enforces the settings that keep a scale-to-zero backend both usable and affordable.

## ADDED Requirements

### Requirement: Users authenticate with gateway-issued keys

Users SHALL reach the model using standard bearer-token API keys issued by the gateway. Backend endpoint credentials MUST NOT be distributed to users.

#### Scenario: User calls the model through the gateway

- **WHEN** a user sends a request with a valid gateway-issued key, naming the served model
- **THEN** the gateway forwards the request to the backend and returns the model's response

#### Scenario: User presents an invalid or revoked key

- **WHEN** a user sends a request with an invalid or revoked gateway key
- **THEN** the gateway rejects the request and does not forward it to the backend

#### Scenario: Access is withdrawn from one user

- **WHEN** an individual user's key is revoked at the gateway
- **THEN** that user loses access while all other users are unaffected, with no change to the backend deployment

### Requirement: Gateway injects backend credentials

The gateway SHALL attach the backend's required authentication headers to every upstream request. Those credentials MUST be sourced from secure configuration rather than written into version-controlled files.

#### Scenario: Gateway forwards an authorized request

- **WHEN** the gateway forwards a user request to the backend endpoint
- **THEN** the upstream request carries the backend's required authentication headers and is accepted

#### Scenario: Backend credentials are missing or wrong

- **WHEN** the gateway is configured without valid backend credentials
- **THEN** upstream requests are rejected by the backend, and the resulting error is surfaced clearly enough to distinguish it from a model failure

### Requirement: No automated polling of the model endpoint

The gateway MUST NOT send periodic, unattended requests to this model's endpoint. Background health checking, availability probing, and any other scheduled traffic against this backend SHALL be disabled.

#### Scenario: Gateway runs unattended overnight

- **WHEN** the gateway is left running with no human user activity for twelve hours
- **THEN** the backend receives zero requests and accrues zero GPU cost

#### Scenario: On-demand health endpoint is queried

- **WHEN** an operator queries the gateway's health endpoint
- **THEN** this model is excluded from the probe and no GPU container is started on its behalf

#### Scenario: Polling suppression is verified against billing

- **WHEN** polling suppression has been configured
- **THEN** it is confirmed by observing zero backend cost across an idle period, not by configuration inspection alone

### Requirement: Timeouts tolerate cold starts

The gateway's request timeout SHALL exceed the backend's worst observed cold start duration, so that a user request arriving at a scaled-to-zero backend succeeds rather than failing while the backend is starting normally.

#### Scenario: Request arrives at a scaled-to-zero backend

- **WHEN** a user request arrives while the backend has no container running
- **THEN** the gateway waits for the backend to start and returns the model's response rather than timing out

#### Scenario: Backend is genuinely unresponsive

- **WHEN** the backend fails to respond within the configured timeout
- **THEN** the gateway returns a timeout error identifying the backend as the source

### Requirement: Retries are bounded

Automatic retries against this backend SHALL be limited, so that a slow cold start cannot multiply into several concurrently starting containers.

#### Scenario: A request times out during a cold start

- **WHEN** a request to a starting backend exceeds the timeout
- **THEN** the gateway does not issue enough retries to cause additional containers to start

#### Scenario: Concurrent users during a cold start

- **WHEN** several users send requests while the backend is starting
- **THEN** their requests are served by the starting container rather than triggering one container per user

### Requirement: Per-key usage limits

The gateway SHALL enforce per-key rate limits, so that a single misconfigured client or runaway script cannot consume the pilot budget.

#### Scenario: A client exceeds its rate limit

- **WHEN** a single key issues requests beyond its configured rate limit
- **THEN** the gateway rejects the excess requests and other users remain unaffected

#### Scenario: Normal team usage

- **WHEN** pilot users make requests at ordinary interactive rates
- **THEN** no user encounters a rate limit during normal work

### Requirement: Streaming passes through the gateway

The gateway SHALL forward incremental token streams from the backend to the user without buffering the full response.

#### Scenario: User requests a streamed completion through the gateway

- **WHEN** a user requests a streamed chat completion via the gateway
- **THEN** tokens arrive incrementally at the user's client as the backend produces them
