"""Model evaluation engine: pure metric computation, dataset loading, and
the orchestrator that runs real components against labeled test cases and
persists results.

Every module under ``classification_metrics``/``confusion_matrix``/
``retrieval_metrics``/``rag_metrics``/``performance_metrics`` is pure
(no I/O, no database, no network) and takes plain Python data in and
returns plain dataclasses/dicts out -- this is what keeps the unit test
suite fast and offline. Only ``evaluation_service`` touches a database
session or calls a real model.
"""
