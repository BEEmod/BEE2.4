"""Run flake8-async, with options."""
import sys

import flake8_async


def join(flag: str, *opts: str) -> str:
    """Build --flag=opt1,opt2"""
    return f'--{flag}={','.join(opts)}'


sys.argv += [
    join(
        'startable-in-context-manager',
        '_load_fsys_task',
        'create',
        'display',
        'display_errors',
        'dropdown',
        'generic_func',
        'init',
        'init_option',
        'init_picker',
        'init_toplevel',
        'init_widgets',
        'init_windows',
        'make_color_swatch',
        'make_map_widgets',
        'make_pane',
        'make_stylevar_pane',
        'make_widgets',
        'route_callback_exceptions',
        'startup',
        'widget_checkmark',
        'widget_checkmark_multi',
        'widget_color_multi',
        'widget_color_single',
        'widget_item_variant',
        'widget_minute_seconds',
        'widget_minute_seconds_multi',
        'widget_slider',
        'widget_string',
    ),
    join(
        'async200-blocking-calls',
        'pickle.dumps->run_sync()',
    ),
    join(
        'enable',
        'ASYNC1',  # Regular
        'ASYNC2',  # Blocking calls

        # Optional rules
        'ASYNC910',
        'ASYNC911',
        'ASYNC912',
        'ASYNC913',
    ),
    join(
        'disable',
        'ASYNC910',
    ),
]

sys.exit(flake8_async.main())
