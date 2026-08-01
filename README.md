# Safe Agent Tool Retries With Idempotency

A standard-library lab demonstrating the semantic contract required when an agent retries a mutating tool after an ambiguous outcome.

The central invariant is stronger than “ignore duplicates”: one tenant, tool, and idempotency key is permanently bound to one canonical intent and one durable result. An equivalent retry returns that result. Reusing the key for changed intent fails.

## Requirements

- CPython 3.11 or newer.
- SQLite bundled with Python.
- No package installation, network service, API key, or paid infrastructure.

## Run

```bash
python3 -m unittest -v test_lab.py
python3 tool_lab.py
```

Expected test result: one passing integration test. The demo prints two operations and two tickets. The first request is created; its equivalent retry is replayed. A second request synthetically loses the response after commit, then recovers the already committed result on retry.

## Mental model

The failure window is:

```text
validate intent -> begin transaction -> write side effect -> store result -> commit
                                                                  |
                                                     response can be lost here
```

The ticket and replayable result commit in the same SQLite transaction. A retry can therefore distinguish an unknown client outcome from an unknown database outcome.

`request_hash` excludes the idempotency key and hashes the normalized semantic fields. This makes the durable key-to-intent binding explicit. The primary key scopes deduplication by tenant and tool instead of globally.

## Failure and recovery exercise

`create_ticket(..., lose_result=True)` commits the ticket and operation result, then raises `LostAfterCommit` before the caller receives it. Calling `create_ticket` again with the same payload must return `disposition: replayed` and the original `ticket_id`.

Change the title while reusing the original key. The call must raise `IntentConflict`; silently replaying the old result would conceal changed intent, while executing again would create an unintended side effect.

Verify durable state directly:

```sql
SELECT count(*) FROM operations;
SELECT count(*) FROM tickets;
```

Both counts remain `2` after the complete demo.

## Concurrency and production gap

`BEGIN IMMEDIATE` serializes competing SQLite writers, so concurrent retries observe the committed operation rather than creating another ticket. This is intentionally a single-process teaching artifact. A production tool boundary still needs request authentication, authorization, bounded key retention, schema evolution, database timeouts, retry/backoff policy, metrics for created/replayed/conflicting calls, trace correlation, and a documented response for in-progress operations.

For a shared database, preserve the same invariants with a unique constraint and one transaction; do not replace them with a process-local cache or a check-then-write sequence.

## Security notes

- Treat tenant identity as authenticated context in production, not a caller-controlled string.
- Hashing canonical intent detects conflicts; it does not encrypt sensitive fields.
- Do not log complete tool arguments or results without a data-retention policy.

## Cleanup

The demo and test use temporary databases and remove them automatically. If adapting the script to a persistent path, stop writers before deleting the database and its `-wal` and `-shm` files.

## Related article

This repository is the repeatable evidence artifact for “Make Agent Tool Retries Safe With Typed Contracts and Idempotency.”

