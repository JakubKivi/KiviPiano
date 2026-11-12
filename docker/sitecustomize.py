"""Startup compatibility shims for legacy dependencies (e.g. madmom).

``madmom`` 0.16.1 predates Python 3.10 (which removed the ``collections``
ABC aliases such as ``MutableSequence``) and numpy 1.24 (which removed the
``np.float``/``np.int``/``np.bool`` aliases). These shims restore those names
so old packages keep importing on the Python 3.10 / numpy 1.x runtime.
"""

import builtins
import collections
import collections.abc

for _name in dir(collections.abc):
    if not _name.startswith("_") and not hasattr(collections, _name):
        setattr(collections, _name, getattr(collections.abc, _name))

try:
    import numpy as _np
except ImportError:
    _np = None

if _np is not None:
    for _name in ("float", "int", "bool", "object", "str", "complex"):
        if not hasattr(_np, _name) and hasattr(builtins, _name):
            setattr(_np, _name, getattr(builtins, _name))
