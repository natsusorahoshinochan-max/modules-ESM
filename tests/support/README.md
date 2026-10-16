# Shared test operations

Support owns application/catalog composition, public requests, synchronization,
exact output decoding, CTK execution and resource handling. It does not choose a
scientific scenario or assert that any terminal Run is successful. Tests own the
expected outcome and relationships; `tests/scenarios` owns shared scenario facts.

`public_runs` works with public transport. `inprocess_runs` waits on a TestClient
application's durable terminal state. `public_journeys` combines explicit commit,
run and event retrieval for in-process journeys and returns the observed terminal
unchanged. None of these operations silently saves a Draft, retries a failed Run,
or substitutes a Provider.

Application, client and storage ownership remains with the caller. Use the
client/runtime's existing context or shutdown boundary. Data-root isolation does
not select Provider configuration: real gates supply the private execution
profile, and controlled tests explicitly replace the intended tool seam.

The existing CTK retains its successful-case contract and closes owned runtime
and temporary resources after collecting outputs. Failure and cancellation
expectations belong to their owner tests. Installation and retained-output
helpers keep temporary execution resources separate from retained observations.
