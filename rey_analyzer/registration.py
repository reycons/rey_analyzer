"""What this application tells bootstrap about itself.

Discovery identity, and deliberately nothing else. Installing the distribution
is what makes the application visible; this says which application was found.

**Not capability.** Commands and workflow operations are published in a later
increment. Duplicating the CLI catalog here would migrate capability into the
increment that exists to defer it, and the registry would briefly be the source
of truth twice.

**Not configuration.** Where the application is checked out, whether this
installation enables it, and where it logs are the installation's answers, held
in ``install/apps/<app>.yaml``. A registration that carried them would let a
package decide something about an installation it has never seen.
"""

from __future__ import annotations

from typing import Any

__all__ = ["APPLICATION_NAME", "get_registration"]

#: The registered identity. One value, matched against the installation's own
#: declaration; a disagreement is refused rather than reconciled.
APPLICATION_NAME = "rey_analyzer"


def get_registration() -> dict[str, Any]:
    """Return this application's registration.

    Returns:
        The discovery identity bootstrap needs.
    """
    return {"name": APPLICATION_NAME}
