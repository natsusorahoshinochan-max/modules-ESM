# Two-layer type system: string IDs for ports, Python classes for data

Port compatibility is checked against string type IDs (e.g., protein.sequence,
protein.structure). The engine never inspects the internal structure of data
passing through ports. This keeps the core agnostic to the shape of future types.

Runtime data is carried by concrete Python classes (dataclasses) in the types/
package. Each class corresponds to one type ID. Modules read and write these objects
through the port contract defined in their ModuleDefinition.

New modules can register new type IDs without modifying the core, as long as the
consumer modules declare matching input ports or the user inserts a conversion node.
