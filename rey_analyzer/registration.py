"""What this application tells bootstrap about itself.

Identity and the surface this application allows to be invoked. Installing the
distribution is what makes it discoverable; this is what it publishes once it
is.

**One source.** An entry for this application left behind in an installation's
external registry is legacy data. It is not merged, is not a fallback and cannot
override what is here, so a command dropped from this file is gone rather than
preserved by a stale copy.

**Not configuration.** Where the application is checked out, whether an
installation enables it and where it logs are that installation's answers, held
in its ``apps:`` declaration. A registration carrying them would let a package
decide something about an installation it has never seen.

``workflow_operations`` is the approved surface a workflow may invoke, and the
contract an author writes a process against. A workflow may name exactly these,
and each declares the settings a step configures it with.
"""

from __future__ import annotations

from typing import Any

__all__ = ["APPLICATION_NAME", "get_registration"]

#: The registered identity. One value, matched against the installation's own
#: declaration; a disagreement is refused rather than reconciled.
APPLICATION_NAME = "rey_analyzer"

#: The command-line surface this application exposes, as an assembler of a
#: pipeline step reads it.
CLI: dict[str, Any] = {   'shared_parameters': [   {   'name': 'config-path',
                                 'required': False,
                                 'value_type': 'path',
                                 'description': 'Path to an app config '
                                                'file or installation '
                                                'config root.'},
                             {   'name': 'config-dir',
                                 'required': False,
                                 'value_type': 'path',
                                 'description': 'Directory containing '
                                                'config.<env>.yaml '
                                                '(overrides '
                                                'APP_CONFIG_DIR).'},
                             {   'name': 'set',
                                 'required': False,
                                 'repeatable': True,
                                 'value_type': 'KEY=VALUE',
                                 'description': 'Override an environment '
                                                'variable for this run.'},
                             ],
    'commands': [   {   'name': 'status',
                        'description': 'Print status of a past run.',
                        'parameters': [   {   'name': 'run-id',
                                              'required': True,
                                              'value_type': 'string'}]},
                    {   'name': 'approve',
                        'description': 'Approve a pending-approval run.',
                        'parameters': [   {   'name': 'run-id',
                                              'required': True,
                                              'value_type': 'string'},
                                          {   'name': 'reviewer',
                                              'required': False,
                                              'value_type': 'string'}]},
                    {   'name': 'reject',
                        'description': 'Reject a pending-approval run.',
                        'parameters': [   {   'name': 'run-id',
                                              'required': True,
                                              'value_type': 'string'},
                                          {   'name': 'reviewer',
                                              'required': False,
                                              'value_type': 'string'}]}]}


#: The operations a workflow may name, each with its settings contract (backlog
#: 939): a JSON Schema 2020-12 definition of the settings its reader takes, and
#: the starter settings a new instance copies.
#:
#: ``source`` is a reference: the name of a data source the step's own Workflow
#: declares (backlog 1032). Which data source that is, and which analysis config
#: it names in turn, stay the implementation's answers (rey_analyzer/workflow.py
#: _process_analysis -> Workflow.data_source -> _resolve_analysis).
WORKFLOW_OPERATIONS: list[dict[str, Any]] = [
    {
        "name": "analysis",
        "description": "Run one named analyzer data source through its analysis config.",
        "contract_definition": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "description": "Run one named analyzer data source through its analysis config.",
            "properties": {
                "source": {
                    "type": "string",
                    "description": (
                        "Data source to analyse, declared in this workflow's "
                        "data_sources. Its analysis_config names the analysis it runs."
                    ),
                },
            },
            "required": ["source"],
            "additionalProperties": False,
        },
        "contract_sample": {"source": ""},
    },
]


def get_registration() -> dict[str, Any]:
    """Return this application's registration.

    Returns:
        Identity, entry point and published capability.
    """
    # Deferred: rey_analyzer.workflow imports from this module.
    from rey_analyzer.workflow import build_process_registry  # noqa: PLC0415

    return {
        "name": APPLICATION_NAME,
        # The mark this application is known by, published the way its CLI and
        # its operations are: which icon is an application's own is a fact
        # about the application, not a choice an installation makes.
        #
        # A NAME, never markup. The surface that draws it holds the artwork and
        # accepts no SVG from an installed distribution.
        "icon": "app.rey_analyzer",
        "entry_point": "main.py",
        "cli": CLI,
        "workflow_operations": WORKFLOW_OPERATIONS,
        # The approved implementation for each published operation, as the
        # finished mapping (backlog 963): what a canonical workflow step binds to.
        "approved_implementations": build_process_registry(),
    }
