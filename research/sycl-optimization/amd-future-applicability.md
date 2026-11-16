# AMD / future-hardware applicability

Findings tied to the Intel stack (IGC/NEO pair, XMX-ESIMD, oneDNN) do not transfer to AMD. Transferable: the method (hold build environment
fixed, bisect one input at a time, KL gate + task-level gate), and the lesson that bundled runtime packages can dominate source-level changes.
Not evaluated on any non-Intel GPU in this research; no AMD numbers exist.
