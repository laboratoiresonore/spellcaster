"""Allow running as: python -m spellcaster_core [command] [args]"""
from .cli import main
import sys
sys.exit(main() or 0)
