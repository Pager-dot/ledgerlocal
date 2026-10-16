"""LedgerLocal — local-first invoice & receipt sorting for freelancers.

Everything runs against an open-weight model on your own machine. There is no
cloud component, no API key, and (see :mod:`ledgerlocal.offline`) no code path
that is allowed to open a socket to anywhere but your local inference server.
"""

__version__ = "0.1.0"
