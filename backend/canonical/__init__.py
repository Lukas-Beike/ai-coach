"""Provider-neutral canonical vocabulary and record types.

This leaf package is standard-library only. It performs no I/O and imports no
other backend package, so every layer may depend on it without creating cycles.
Provider adapters map their own payload spellings onto these members at the
boundary.
"""
