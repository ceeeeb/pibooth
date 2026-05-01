pibooth-ceeeeb
==============

Custom fork of `pibooth <https://github.com/pibooth/pibooth>`_ — a photo
booth application in pure Python for the Raspberry Pi — maintained by
ceeeeb for personal events.

This fork tracks upstream pibooth at the time of forking and adds local
modifications. It is published under a different distribution name on
PyPI (``pibooth-ceeeeb``) to avoid colliding with the upstream
``pibooth`` package; the importable Python module is still named
``pibooth``.

Differences vs upstream
-----------------------

- Settings menu sized to 85% of the screen (was hard-capped at 600x400).
- 4-finger gesture inside the open settings menu pops a save / discard
  / cancel confirmation dialog (in addition to the existing 4-finger
  open).
- Bundled with companion plugins maintained in their own repos:
  ``pibooth-pcloud``, ``pibooth-nextcloud`` (forked), ``pibooth-gallery-qr``,
  ``pibooth-forget-button``, ``pibooth-background-changer``.

Install
-------

This package conflicts with upstream ``pibooth``. Install in a fresh
virtualenv::

    python3 -m venv pibooth-env
    source pibooth-env/bin/activate
    pip install pibooth-ceeeeb

Or directly from git::

    pip install git+https://github.com/ceeeeb/pibooth.git@v2.0.8.2

Plugins that depend on ``pibooth>=2.0.0`` (e.g. ``pibooth-pcloud``,
``pibooth-nextcloud``) will not see ``pibooth-ceeeeb`` as satisfying the
requirement, so install plugins with ``--no-deps`` if you want to avoid
pulling upstream pibooth alongside this fork::

    pip install --no-deps pibooth-pcloud

License
-------

MIT — see the ``LICENSE`` file. Upstream credits preserved.

Upstream
--------

For the unmodified, supported version of pibooth, see
https://github.com/pibooth/pibooth.
