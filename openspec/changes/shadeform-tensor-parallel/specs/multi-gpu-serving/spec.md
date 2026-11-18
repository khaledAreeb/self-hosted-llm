# Spec Delta

## Purpose

Lets the operator choose, for one run, to serve the model across several GPUs of a single Shadeform VM instead of one, while a run without that choice behaves exactly as it did before.

## ADDED Requirements

### Requirement: One GPU stays the default, unchanged

A run that does not ask for multiple GPUs SHALL behave exactly as before this capability existed: the same offers, the same VM, and the same vLLM settings as the measured single-GPU deployment.

#### Scenario: No option given

- **WHEN** the operator lists offers or brings a VM up without asking for multiple GPUs
- **THEN** only single-GPU offers are considered, and the vLLM settings are identical, argument for argument and in order, to those verified against the Modal deployment

#### Scenario: One GPU requested explicitly

- **WHEN** the operator asks for one GPU explicitly
- **THEN** the result is the same as giving no option

### Requirement: Multi-GPU is chosen per run

The operator SHALL be able to ask for the model to be split across a stated number of GPUs on one VM, separately for each run. The choice MUST work together with the existing choices of GPU type, provider, region and lifetime.

#### Scenario: Asking for two GPUs

- **WHEN** the operator lists offers and asks for two GPUs
- **THEN** only available offers with exactly two GPUs are shown, each with its price for the whole VM, ordered cheapest first

#### Scenario: Combining choices

- **WHEN** the operator asks for two GPUs of one type, in one region
- **THEN** only offers matching all of those choices are shown and used

#### Scenario: The next run is independent

- **WHEN** one run used several GPUs and the operator starts another run without asking for them
- **THEN** the second run uses one GPU, with nothing carried over

### Requirement: Only offers that can hold the split model are used

Offers for several GPUs SHALL be used only if each GPU has enough memory for its share of the model and the VM's driver supports the pinned vLLM container. The same rules as for one GPU apply to each GPU.

#### Scenario: Cards that are too small

- **WHEN** an offer has the requested number of GPUs but too little memory on each
- **THEN** it is not offered

#### Scenario: Old host driver

- **WHEN** an offer has the requested number of GPUs but a host driver too old for the container
- **THEN** it is listed as not usable, with the reason, and is never used

#### Scenario: No offer fits

- **WHEN** no available offer has the requested number of suitable GPUs
- **THEN** the tool says so and creates nothing

### Requirement: The model is served across all requested GPUs

When several GPUs are requested, the served model SHALL use all of them, and the VM SHALL NOT be reported ready unless it has the requested number of GPUs and the model answers through the protected endpoint.

#### Scenario: Normal start

- **WHEN** the operator brings up a VM for two GPUs
- **THEN** the tool reports ready only after the model answers a real question, and states that two GPUs are in use

#### Scenario: Fewer GPUs than requested

- **WHEN** the VM turns out to have fewer GPUs than requested
- **THEN** the start fails with a message saying so, and the VM is deleted with billing confirmed stopped

#### Scenario: The split model cannot start

- **WHEN** the model does not start across the GPUs, or does not answer within the startup time limit
- **THEN** the VM is deleted with billing confirmed stopped, and the tool says where to look for the cause

### Requirement: The GPU connection is reported

For a multi-GPU run, the tool SHALL make visible how the GPUs are connected, so that a measured speed can be read together with the kind of link that produced it.

#### Scenario: Reading the connection

- **WHEN** a multi-GPU VM is ready
- **THEN** the operator can see the number of GPUs and their connection type, both in the start log on the VM and in the information the tool shows

### Requirement: Safety guarantees are the same for every mode

Multi-GPU runs SHALL keep every guarantee of the single-GPU deployment: a required lifetime enforced by a deadline, a required secret key, encrypted mode with a firewall on request, deletion on every failure, and billing confirmed stopped when the VM is closed.

#### Scenario: Deadline

- **WHEN** a multi-GPU VM is brought up
- **THEN** it has a deadline and a cost cap, and the cap reflects the price of the whole multi-GPU VM

#### Scenario: Encrypted mode

- **WHEN** a multi-GPU VM is brought up in encrypted mode
- **THEN** it answers only over HTTPS, and ports other than SSH and the API port are closed

#### Scenario: Closing

- **WHEN** the operator closes a multi-GPU VM
- **THEN** it is deleted and billing is confirmed stopped, exactly as for one GPU

### Requirement: The benefit is measured before it is relied on

The documentation SHALL NOT claim that multiple GPUs make the model faster or serve more people until that has been measured on the real setup, and SHALL record the measured numbers beside the single-GPU numbers.

#### Scenario: After the paid measurement

- **WHEN** a multi-GPU run has been measured
- **THEN** the documentation gives its generation speed, cache capacity, start time and cost, next to the single-GPU figures from the same hardware type, and says whether it was worth the higher hourly price
