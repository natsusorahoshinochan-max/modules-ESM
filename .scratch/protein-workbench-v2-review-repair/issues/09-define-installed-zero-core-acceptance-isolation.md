# Define installed-artifact and zero-Core acceptance isolation

Type: grilling
Mode: HITL
Status: open
Blocked by: 02, 03, 06, 08

## Question

What process, dependency, import-origin, and transport isolation must an
installed-artifact gate prove for the Workbench and its locked provider
dependencies? Decide whether ambient `.pth` reuse is ever admissible, how a
zero-Core extension is introduced without packaging fixtures, and which
provider journeys must traverse the public REST and Run Event Stream rather
than internal service objects.
