"""Shared test fixtures: put ~/workspace on sys.path so `LIB` and the
package import exactly as they do in production.
"""

import os
import sys

sys.path.insert(0, os.path.expanduser("~/workspace"))
