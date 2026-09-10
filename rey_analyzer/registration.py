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
                             {   'name': 'pipeline-name',
                                 'required': False,
                                 'value_type': 'string',
                                 'description': 'Pipeline name supplied by '
                                                'pipeline_coordinator.'},
                             {   'name': 'pipeline-run-id',
                                 'required': False,
                                 'value_type': 'string',
                                 'description': 'Unique pipeline run '
                                                'identifier supplied by '
                                                'pipeline_coordinator.'},
                             {   'name': 'pipeline-step-name',
                                 'required': False,
                                 'value_type': 'string',
                                 'description': 'Pipeline step name '
                                                'supplied by '
                                                'pipeline_coordinator.'},
                             {   'name': 'pipeline-step-id',
                                 'required': False,
                                 'value_type': 'string',
                                 'description': 'Optional unique pipeline '
                                                'step identifier.'},
                             {   'name': 'log-file',
                                 'required': False,
                                 'value_type': 'path',
                                 'description': 'Shared pipeline JSONL log '
                                                'path.'},
                             {   'name': 'ctx-file',
                                 'required': False,
                                 'value_type': 'path',
                                 'description': 'Pipeline step ctx '
                                                'snapshot (JSON); mutually '
                                                'exclusive with '
                                                'config-path.'}],
    'commands': [   {   'name': 'run',
                        'description': 'Process all enabled data sources.',
                        'parameters': []},
                    {   'name': 'run-source',
                        'description': 'Process one named data source.',
                        'parameters': [   {   'name': 'source',
                                              'required': True,
                                              'value_type': 'choice',
                                              'possible_values': [   'file_profile_to_loader_config',
                                                                     'fo_final_ddl',
                                                                     'fo_profile_to_loader',
                                                                     'fo_staging_ddl',
                                                                     'fo_staging_view',
                                                                     'loader_config_to_final_ddl',
                                                                     'loader_config_to_staging_ddl',
                                                                     'loader_config_to_staging_view',
                                                                     'rey_loader_logs']}]},
                    {   'name': 'run-workflow',
                        'description': 'Run a configured analyzer '
                                       'workflow.',
                        'parameters': [   {   'name': 'workflow',
                                              'required': True,
                                              'value_type': 'string',
                                              'description': 'Workflow '
                                                             'name under '
                                                             "'workflows' "
                                                             'in '
                                                             'rey_analyzer '
                                                             'config.'},
                                          {   'name': 'step',
                                              'required': False,
                                              'value_type': 'string',
                                              'description': 'Run only the '
                                                             'one matching '
                                                             'step.'},
                                          {   'name': 'from-step',
                                              'required': False,
                                              'value_type': 'string',
                                              'description': 'Run from the '
                                                             'matching '
                                                             'step through '
                                                             'the end of '
                                                             'the '
                                                             'workflow.'},
                                          {   'name': 'to-step',
                                              'required': False,
                                              'value_type': 'string',
                                              'description': 'Run from the '
                                                             'start of the '
                                                             'workflow '
                                                             'through the '
                                                             'matching '
                                                             'step.'}]},
                    {   'name': 'submit-file',
                        'description': 'Submit one file for analysis.',
                        'parameters': [   {   'name': 'source',
                                              'required': True,
                                              'value_type': 'choice',
                                              'possible_values': [   'file_profile_to_loader_config',
                                                                     'fo_final_ddl',
                                                                     'fo_profile_to_loader',
                                                                     'fo_staging_ddl',
                                                                     'fo_staging_view',
                                                                     'loader_config_to_final_ddl',
                                                                     'loader_config_to_staging_ddl',
                                                                     'loader_config_to_staging_view',
                                                                     'rey_loader_logs']},
                                          {   'name': 'file',
                                              'required': True,
                                              'value_type': 'path'}]},
                    {   'name': 'analyze-file',
                        'description': 'Analyze one file without moving '
                                       'it.',
                        'parameters': [   {   'name': 'source',
                                              'required': True,
                                              'value_type': 'choice',
                                              'possible_values': [   'file_profile_to_loader_config',
                                                                     'fo_final_ddl',
                                                                     'fo_profile_to_loader',
                                                                     'fo_staging_ddl',
                                                                     'fo_staging_view',
                                                                     'loader_config_to_final_ddl',
                                                                     'loader_config_to_staging_ddl',
                                                                     'loader_config_to_staging_view',
                                                                     'rey_loader_logs']},
                                          {   'name': 'file',
                                              'required': True,
                                              'value_type': 'path'}]},
                    {   'name': 'build-payload',
                        'description': 'Build and print the LLM payload '
                                       'without calling the API.',
                        'parameters': [   {   'name': 'source',
                                              'required': False,
                                              'value_type': 'choice',
                                              'possible_values': [   'file_profile_to_loader_config',
                                                                     'fo_final_ddl',
                                                                     'fo_profile_to_loader',
                                                                     'fo_staging_ddl',
                                                                     'fo_staging_view',
                                                                     'loader_config_to_final_ddl',
                                                                     'loader_config_to_staging_ddl',
                                                                     'loader_config_to_staging_view',
                                                                     'rey_loader_logs'],
                                              'description': 'Data source '
                                                             'name; uses '
                                                             'the first '
                                                             'inbox file '
                                                             'when '
                                                             'supplied.'},
                                          {   'name': 'analysis',
                                              'required': False,
                                              'value_type': 'string',
                                              'description': 'Analysis '
                                                             'config name; '
                                                             'use with '
                                                             'file when '
                                                             'source is '
                                                             'omitted.'},
                                          {   'name': 'file',
                                              'required': False,
                                              'value_type': 'path',
                                              'description': 'File to '
                                                             'build a '
                                                             'payload for '
                                                             'when '
                                                             'analysis is '
                                                             'supplied.'}]},
                    {   'name': 'status',
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


#: The operations a workflow may name, and what each is configured with.
#:
#: ``source`` is a data-source name. Publication says the setting exists and is
#: required; which data source that name identifies, and which analysis config
#: that source in turn names, stay the implementation's answers.
WORKFLOW_OPERATIONS: list[dict[str, Any]] = [
    {
        "name": "analysis",
        "description": "Run one named analyzer data source through its analysis config.",
        "parameters": [
            {
                "name": "source",
                "required": True,
                "value_type": "string",
                "description": "Data-source name declared under data_sources.",
            },
        ],
    },
]


def get_registration() -> dict[str, Any]:
    """Return this application's registration.

    Returns:
        Identity, entry point and published capability.
    """
    return {
        "name": APPLICATION_NAME,
        "entry_point": "main.py",
        "cli": CLI,
        "workflow_operations": WORKFLOW_OPERATIONS,
    }
