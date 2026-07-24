# SimpleFold: separate fold and evaluate modules

SimpleFold is exposed as two modules: simplefold.fold (sequence to structures,
100M model, num_steps capped at 50, outputs pLDDT from the same forward pass)
and simplefold.evaluate (structures to scores, larger model running only the
pLDDT head on existing structures without re-folding).

This split lets users fold many candidates cheaply with the 100M model and
selectively re-score top candidates with a more accurate pLDDT estimator,
without paying the cost of full folding on the larger model. During testing,
the evaluate module uses the 360M model; production configuration supports
any model size.
