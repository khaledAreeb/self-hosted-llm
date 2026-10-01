# Spec Delta

## Purpose

Lets the operator run the model on a rented Shadeform GPU VM whenever the team needs it and close it afterwards, with the same serving behaviour measured on Modal, protected access, and a guarantee that a forgotten VM does not keep billing.

## ADDED Requirements

### Requirement: Only GPUs that can run the model are offered

The tool SHALL list only single-GPU offers that are available now, have enough GPU memory for the model at its configured context, and run an operating system whose CUDA driver supports the pinned vLLM container. Offers MUST be ordered by hourly price, cheapest first.

#### Scenario: Listing offers

- **WHEN** the operator asks for offers
- **THEN** each offer shows provider, region, GPU, hourly price and operating system, and no unavailable or unsuitable offer is shown

#### Scenario: Restricting where the VM runs

- **WHEN** the operator limits offers to certain regions or providers
- **THEN** only offers in those regions or from those providers are listed and used

#### Scenario: Nothing suitable is available

- **WHEN** no offer meets the requirements
- **THEN** the tool says so and creates nothing

### Requirement: The tool is standalone and starts from the measured settings

The tool SHALL be fully standalone: it MUST NOT import, read or require the Modal deployment's files or libraries. It SHALL define its own serving settings, which at delivery MUST equal the settings measured on Modal (model, context length, KV cache precision, GPU memory share, speculative decoding, reasoning parser and default effort, tool calling).

#### Scenario: Running on a machine with nothing else

- **WHEN** the tool runs on a machine that has only Python 3 and the tool file
- **THEN** every command works, without the Modal deployment's file or the Modal library present

#### Scenario: Starting point

- **WHEN** the tool is first delivered
- **THEN** its vLLM settings equal the measured Modal configuration flag for flag, and that check is recorded

#### Scenario: Tuning one side

- **WHEN** a serving setting is changed in the tool, or in the Modal deployment
- **THEN** the other is unaffected, because neither depends on the other

### Requirement: The Modal deployment is left untouched

Adding the Shadeform deployment SHALL NOT change the Modal deployment's configuration file, so that the Modal endpoint stays exactly as measured and ready to use as a fallback.

#### Scenario: After the Shadeform tool is added

- **WHEN** the Shadeform tool and its tests are complete
- **THEN** the Modal deployment's configuration file is byte-for-byte what it was before this change

### Requirement: "Up" means the model answers, not that the VM exists

Bringing a VM up SHALL finish only when the model returns a real answer through the protected endpoint. A VM that exists but never serves MUST NOT be left running.

#### Scenario: Normal start

- **WHEN** the operator brings a VM up
- **THEN** the tool reports progress through provisioning, container start and model load, and finishes by printing the endpoint address after a real completion succeeds

#### Scenario: The chosen offer has no capacity

- **WHEN** the provider rejects the request for lack of capacity
- **THEN** the tool tries the next suitable offer, without the operator re-running it

#### Scenario: The model never becomes ready

- **WHEN** the model has not answered within the startup time limit, or the VM reports an error
- **THEN** the tool deletes the VM, confirms it is deleted, and reports why, so no billing continues for a VM that never served

### Requirement: Access requires a secret key

Every request to the served model SHALL require the operator's secret key; requests without it MUST be refused. The key MUST NOT be printed in full or written anywhere except the operator's git-ignored environment file.

#### Scenario: A request without the key

- **WHEN** a request reaches the VM without the key, or with a wrong one
- **THEN** it is refused and no answer is generated

#### Scenario: Connecting the gateway

- **WHEN** a VM is up
- **THEN** the tool prints the API base address and the model name to enter in the gateway, and names the environment variable that holds the key, without printing the key itself

### Requirement: Company data only travels encrypted

The tool SHALL offer an encrypted (HTTPS) mode in which the VM serves only over TLS and accepts connections only on SSH and the API port. The plain-HTTP mode MUST be clearly labelled as unencrypted each time it is used.

#### Scenario: Plain mode

- **WHEN** a VM is brought up in plain mode
- **THEN** the tool warns that traffic, including the key and every prompt, is unencrypted and suitable only for non-sensitive tests

#### Scenario: Encrypted mode

- **WHEN** a VM is brought up in encrypted mode
- **THEN** the endpoint answers only over HTTPS, a plain-HTTP request to it fails, and ports other than SSH and the API port are closed

### Requirement: Every VM has a deadline, and billing stops when it passes

Bringing a VM up SHALL require a maximum lifetime. The deadline MUST be recoverable from Shadeform alone, with no local state, and a clean-up command MUST delete every VM created by the tool whose deadline has passed.

#### Scenario: No lifetime given

- **WHEN** the operator tries to bring a VM up without a maximum lifetime
- **THEN** the tool refuses and creates nothing

#### Scenario: The deadline passes

- **WHEN** the clean-up command runs after a VM's deadline
- **THEN** that VM is deleted, and the deletion is confirmed

#### Scenario: Other instances on the account

- **WHEN** the account also has instances the tool did not create
- **THEN** the clean-up command leaves them untouched

### Requirement: Closing stops the billing

Closing a VM SHALL delete it and confirm from Shadeform that it is deleted, and the operator MUST be able to see every running VM created by the tool with its cost so far.

#### Scenario: Closing

- **WHEN** the operator closes a VM
- **THEN** the tool reports it deleted only after Shadeform confirms the deletion

#### Scenario: Checking what is running

- **WHEN** the operator asks for status
- **THEN** every running VM created by the tool is listed with its address, hourly price, cost so far, and time left before its deadline
