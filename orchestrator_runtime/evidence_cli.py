"""Warning-free CLI entry point; the package eagerly exports evidence types."""
import sys
from .evidence import _main

if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
