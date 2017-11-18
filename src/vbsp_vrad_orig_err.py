"""Our compiler replacements might be saved under the _original name.

Detect that and crash.
"""
import sys
print('BEE2: Fatal error - saved as _original file.', file=sys.stderr)
sys.exit(1)
