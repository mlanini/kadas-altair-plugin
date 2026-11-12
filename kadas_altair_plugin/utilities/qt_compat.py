"""Qt compatibility helpers shared across the plugin.

The helpers keep runtime behavior stable across Qt5/PyQt5 and Qt6/PyQt6.
"""


def qt_exec(qt_object):
    """Execute a Qt modal/event loop using exec() or exec_()."""
    if qt_object is None:
        raise ValueError('qt_object cannot be None')

    exec_fn = getattr(qt_object, 'exec', None)
    if callable(exec_fn):
        return exec_fn()

    legacy_exec_fn = getattr(qt_object, 'exec_', None)
    if callable(legacy_exec_fn):
        return legacy_exec_fn()

    raise AttributeError(f'{type(qt_object).__name__} has no exec/exec_ method')
