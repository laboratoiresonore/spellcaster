"""Endpoint handlers for the Spellcaster antenna.

Each module exposes one or more handler callables with the signature:

    def handler(request_ctx: dict) -> tuple[int, dict]:
        ...
        return (status_code, response_body)

The request_ctx dict has: method, path, raw_path, headers, body, client_ip, config.
Handlers must return JSON-serialisable dicts. Exceptions propagate to agent.py
which logs + returns a generic 500 (never leaks internal errors to clients).
"""
