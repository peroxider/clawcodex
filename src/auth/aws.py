"""Facade — auth/aws.py has been moved to clawcodex_ext/auth/aws.

The F-88 AWS Bedrock authentication (``AwsCredentials``, ``AwsAuth``)
now lives in :mod:`clawcodex_ext.auth.aws`. This module re-exports the
public surface so existing ``from src.auth.aws import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module has no ``__all__``.
"""

import clawcodex_ext.auth.aws as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
