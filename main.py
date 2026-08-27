"""Entry point:  py -3 main.py [file.ly]"""
import sys

from lilyrender.ui import run

if __name__ == "__main__":
    sys.exit(run(sys.argv))
