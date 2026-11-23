"""`rqh` subcommands, one module each, found by `rqharness.cli.discover_commands`.

A command module defines ``register(subparsers)``: it adds its parser and sets
``handler`` with ``set_defaults(handler=fn)``, where ``fn(args)`` returns a
``rqharness.cli.Outcome``. Adding a module here is the whole registration; no
shared file is edited (spec D23).
"""
