# Provider execution contract

Status: current operational specification.

This document defines the common execution contract for Adapter-backed
Execution Bindings. Method-specific scientific contracts remain authoritative
for scientific inputs, outputs, units, shapes, residue mappings, masking,
randomness, lineage, provenance, and Provider translation.

This contract refines the shared operational consequences of
[ADR-0029](./adr/0029-readiness-follows-cache-miss-before-provider-entry.md),
[ADR-0030](./adr/0030-execution-evidence-separates-attempts-and-invocations.md),
[ADR-0041](./adr/0041-one-deep-module-owns-node-execution-attempt-lifecycle.md),
[ADR-0042](./adr/0042-run-evidence-ledger-owns-its-fact-grammar.md), and
[ADR-0045](./adr/0045-one-simplefold-module-owns-provider-asset-closure.md).
It does not introduce another scientific identity, public protocol, Provider
base class, or evidence grammar.

## Governing principles

1. Scientific correctness and interpretability come first.
2. Environment Configuration, Provider assets, pinned upstreams, and internal
   values are trusted after their contract-owning boundary admits them.
3. Readiness checks only the declared operational prerequisites needed to enter
   the selected Provider route. It does not authenticate or fingerprint them.
4. An Adapter follows the authoritative Provider or pinned-upstream contract
   exactly. It does not guess, repair, retry, or select a fallback.
5. Core runtime owns blocking-resource lifetime and causal evidence. Adapters
   own Provider translation and Provider-specific outcome classification.
6. The implementation uses the smallest direct mechanism that satisfies these
   contracts. It does not add machinery for hypothetical routes or failures.

This is a trusted, single-user, loopback-only project. This specification adds
no authentication, authorization, sandbox, attacker handling, malformed-
Provider recovery, repeated validation, or defensive installation proof.

## Execution order

An Adapter-backed Cache miss or bypass follows this order:

```text
admitted Environment Configuration + admitted scientific inputs
    -> Readiness Attestation
    -> trusted route-specific asset paths
    -> Provider activation
    -> Engine Invocation {
           Provider call
           documented Provider outcome classification
       }
    -> canonical result admission
    -> deterministic resource cleanup
    -> Operation terminal publication
```

Operation terminal publication occurs only after result admission and cleanup
reach their conclusions. The terminal fact is durable and is never rewritten.
A cleanup-only failure therefore publishes a failed Operation terminal instead
of publishing success before cleanup.

In this document, **Provider activation** is only a descriptive phase for
Provider import, client construction, and resident-model loading. It is not a
new domain object, Ledger fact, or public event.

Provider activation occurs inside the Operation Attempt and before the
corresponding Engine Invocation that performs scientific work. Activation
failure produces a failed Operation Attempt without inventing an Invocation for
the scientific engine that was never entered. When the declared Method composes
several scientific engine calls, any completed preceding Invocations remain
evidence; only the not-yet-entered engine has no Invocation.

An Engine Invocation is one actual entry into one declared scientific engine
seam. It contains exactly one physical Adapter- or SDK-owned Provider attempt.
One Operation Attempt may still contain several Engine Invocations when its
declared Method actually composes several scientific engine calls, such as an
encode call followed by a logits call. Retries and compatibility fallbacks are
not additional stages of the same Invocation.

## Provider assets and Readiness

### Complete route closure

Each Adapter-backed Execution Binding declares the union of all fixed Provider
assets that any legal input accepted by that route may require. The closure is
not the intersection of assets shared by every input and is not a
Prompt-dependent dependency graph.

Readiness checks that closure once at the Run-scoped boundary defined by
ADR-0029. A successful Readiness conclusion means that later legal inputs for
the same Binding do not discover a missing fixed weight, CCD object, tokenizer
table, annotation table, executable, package, or source location inside the
Provider seam.

The closure remains operational rather than scientific identity. Readiness does
not hash Provider files, inspect Git state, prove installation origin, build a
manifest, compare contents, or retain a reusable proof outside its defined Run
lifetime.

### Direct binding

After Readiness succeeds, the Adapter uses the exact admitted configured paths.
It does not:

- copy Provider source, checkpoints, weights, CCD data, tokenizer data, or
  reference databases into a runtime or per-invocation asset root;
- search an environment variable, current directory, downloader cache, sibling
  checkout, or alternate workspace for another object;
- download a missing object;
- rename an admitted Provider asset to satisfy an alternate layout; or
- select another model, checkpoint, source root, or Provider route.

A private invocation directory contains only scientific-input materializations,
Provider-required working files, logs, intermediate results, and outputs. It is
not another Provider Asset Closure.

### Root lifetime

Configured Provider roots are fixed for the lifetime of the application
process. Changing a root requires a new process. The runtime does not support
same-path hot replacement, root rebinding, content generations, asset
fingerprints, or cache invalidation machinery.

A process-global upstream cache may therefore reuse state only for the one
configured root. Environment variables or earlier imports must not cause the
Provider to read a different root from the one admitted by Readiness.

## Adapter call and evidence

The Adapter constructs the Provider client, loads a resident model, and creates
the fixed Provider request before starting the corresponding Engine Invocation.
It starts the Invocation immediately before the actual scientific or remote
Provider call.

The Provider call and classification of its documented operational outcome
both occur inside the Invocation boundary. A documented Provider error value or
exception terminates that Invocation as failed. Client construction,
configuration construction, or local preparation failure before the call
produces no Invocation.

Provider-independent result decoding, normalization, and output admission occur
after a successful Provider outcome. Failure in those later phases leaves the
completed Engine Invocation succeeded and fails the surrounding Operation
Attempt at the actual causal depth.

Every actual scientific engine entry has one Engine Invocation and one terminal
fact. One Invocation must not contain:

- an SDK retry;
- an Adapter retry;
- a second command selected after the first command fails;
- a fallback endpoint, model, device, executable syntax, or Provider; or
- a speculative malformed-response recovery path.

Provider-specific randomness, residue projection, source/model label, and other
Method-required provenance remain attached to the exact Invocation that used
them. The common execution contract does not add generic provenance fields.

## Remote Provider calls

Environment Configuration owns the admitted credential handle. The selected
Method owns the model and algorithm identity, and the selected Execution Binding
fixes that Method, Provider model label, endpoint route, and SDK. The Adapter
implements the fixed translation and invocation without owning model identity.
Every current Biohub Adapter owns the same fixed 150-second request timeout as an
operational performance-policy fact. The timeout is not an Environment
Configuration field, composition-root policy, Execution Profile override,
Workflow parameter, or scientific identity. An Acceptance Campaign Execution
Profile may still own its outer service and tier transport limits; those limits
do not replace or alter the Adapter-owned SDK request timeout.

Each remote Engine Invocation makes one SDK-owned network attempt. The effective
SDK attempt count is one, including when the SDK has a larger default retry
policy. The effective request timeout is finite, including when the SDK default
is indefinite, and is exactly 150 seconds for every current Biohub route.

A synchronous remote request need not claim immediate cancellation if its
official client cannot provide it. It must still terminate within its admitted
finite timeout so that the Operation, Run, and application shutdown can reach a
terminal state.

The Adapter deterministically closes every remote client it creates on success,
Provider failure, translation failure, and cancellation. Normal lifecycle does
not rely on garbage collection to release the client's connection pool.

## Local Provider processes

Core execution owns one managed local-process entry point. A Module Package does
not directly own raw `subprocess.run` or `subprocess.Popen` lifecycle. Each local
Adapter owns one fixed positive finite process timeout as part of its route
performance policy and passes that value to the core owner. The timeout is not
chosen ad hoc by the caller and does not round-trip through Environment
Configuration or Workflow parameters. Core execution owns the bounded
termination and kill grace periods. This shared contract does not assign one
common timeout to mkdssp, SoluProt, and Protein-Sol; each Adapter declares its
own exact constant.

For each local Provider process, the core owner:

1. starts an isolated process group;
2. registers that group with Run cancellation before waiting;
3. applies the Adapter-owned timeout for that Provider call;
4. sends cancellation and timeout signals to the process group rather than only
   its leader;
5. escalates from termination to kill within bounded grace periods;
6. waits for the process group to disappear; and
7. unregisters the group only after it is no longer active.

Leader exit alone does not close process-group ownership. A Run cancellation or
local timeout must not leave a descendant performing Provider work after the Run
reports cleanup completion.

Every local Provider route, including an executable-only CPU route, enters the
existing `OperationResources.local_provider` lifecycle. Switching Provider IDs
releases the prior resident Provider state before the next local Provider
executes.

This process owner does not interpret Provider output, infer scientific success,
or add command compatibility behavior. The Adapter retains command construction,
documented exit interpretation, and scientific translation.

## Process-global state

A normal namespaced Provider import and its ordinary Python module cache may
remain in `sys.modules`. The contract does not require unloading imported
packages, recreating the interpreter module graph, or restoring immutable
module-owned singleton objects.

An Adapter does not leave a temporary current directory, added `sys.path` entry,
environment override, injected bare-module alias, or mutable registry change
that it introduced and that can alter a later Provider call. When a pinned
upstream requires such a temporary mutation, the Adapter restores only the
entries and values that it changed before returning or raising. Serial Run
execution prevents overlap but does not make these active mutations permanent
process state.

This specification does not introduce a Provider worker system. A future route
that cannot satisfy scoped restoration requires a separate architecture
decision supported by an actual reachable Provider constraint.

## Cleanup and error ownership

Adapters and core resources close clients, resident models, local processes, and
temporary directories at their current owner seam.

The runtime completes cleanup before publishing the Operation terminal. When
scientific execution or Provider translation has already failed, a later cleanup
failure does not replace that primary error. Both remain attributable to their
actual causal depths through the existing Operation and cleanup reporting. When
cleanup is the only failure, the runtime publishes a failed Operation terminal;
no earlier success terminal exists to rewrite. No retry, silent suppression, or
new cleanup evidence grammar is introduced.

## Minimal implementation shape

The common production shape is deliberately small:

- each local Provider route retains one route-owned fixed asset list and one
  small immutable runtime record, when a record is useful;
- Adapters use the existing `OperationResources.engine_invocation` boundary;
- local executable routes use the one core managed-process entry point;
- existing context managers or `ExitStack` own client and model release; and
- existing Run and Node Attempt cleanup owns terminal publication.

This contract does not require or permit introducing the following merely to
implement the confirmed repairs:

- a Provider base class or generic Provider execution framework;
- a dynamic or Prompt-dependent asset dependency graph;
- asset hashes, fingerprints, generations, hot reload, or invalidation state;
- a retry, fallback, compatibility, or malformed-response framework;
- a Provider worker or sandbox system;
- an Activation Ledger fact or another evidence writer;
- a second resource manager; or
- legacy behavior, aliases, migration paths, or dual implementations.

## Verification contract

Verification is behavior-based and uses existing public, package, Adapter, and
resource seams. It does not assert private helper count, private call order,
function length, or a general AST shape.

Focused Provider execution cases use three test-only profiles:

| Profile | Required observations |
| --- | --- |
| Local assets | Removing each declared fixed asset fails Readiness; a successful call opens the admitted asset paths and creates no Provider-asset copy; ambient state cannot select another root. |
| Remote Provider | One Adapter call produces one physical SDK attempt per Engine Invocation; the timeout is exactly 150 seconds; an official operational error fails that Invocation; the client closes on every terminal path. |
| Local process | The command uses the exact constant declared by its Adapter; cancellation owns the complete process group; leader-first exit leaves no descendant; Provider switching releases earlier resident state. |

A narrow provider-execution coverage check compares Adapter-backed Execution
Bindings in the current Catalog with the Binding IDs represented by these
focused cases. It does not require exact-set inventories for every Node Type,
direct Binding, Port, or scientific contract and does not move fixtures into
production Module Package Registration.

One required source-boundary check enforces that production Module Packages do
not directly own `subprocess.run` or `subprocess.Popen`; the one core
managed-process owner is the only production exception. Global-state,
asset-path, attempt-count, timeout, error, and cleanup rules are verified by
observable behavior rather than source-shape inspection.

Controlled local fakes may prove attempt count, timeout propagation, client
closure, official error classification, cleanup causality, and process-group
termination. They do not replace required real-Provider acceptance of
scientific translation and outcomes. After focused and deterministic gates
pass, the canonical real-Provider Acceptance Campaign runs once in serial order
under its admitted Execution Profile.

## Implementation status

The current implementation addresses these previously confirmed gaps against
this contract:

- [#77 — admitted Provider assets are copied into runtime work directories, including Protein-Sol source](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/77)
- [#78 — Local ESMFold2 can read CCD data outside the admitted model root](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/78)
- [#79 — Local ESM-3 Readiness omits function-tokenization assets](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/79)
- [#83 — cancellation can unregister a process group while descendants remain alive](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/83)
- [#84 — Module Packages directly own mkdssp and SoluProt/Protein-Sol process lifecycle](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/84)
- [#86 — SoluProt uses failure-driven USEARCH command fallback](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/86)
- [#87 — temporary-directory cleanup can replace the primary Operation error](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/87)

The remaining confirmed gaps are:

- [#80 — Biohub SDK retries are collapsed into one Engine Invocation](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/80)
- [#81 — Biohub requests have no finite timeout and clients are not deterministically closed](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/81)
- [#82 — remote ESMFold2 records Provider errors outside the Invocation boundary](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/82)
- [#85 — SimpleFold leaves Provider import state in the host process](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/85)

The linked issues record implementation status. They do not define alternate
contracts or preserve superseded behavior as compatibility.
