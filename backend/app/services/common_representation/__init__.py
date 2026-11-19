"""Common structured representation for the approved global PDF pipeline.

Stage 1 only: this package defines the representation types
(:mod:`.types`) and conversion adapters from each existing producer's
current output (:mod:`.adapters`). It implements neither the global
chunking engine nor the shared validation gate.

As of Stage 4A Task 4, :mod:`.adapters` and :mod:`.chunker` are imported
and called from the live ingestion path in
``app.services.admin.knowledge_base_pipeline``.
"""
