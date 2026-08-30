"""Throwaway static server for import, merge, and residue-alignment prototype 4."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from os import chdir
from pathlib import Path


PROTOTYPE_DIR = Path(__file__).resolve().parent


if __name__ == "__main__":
    chdir(PROTOTYPE_DIR)
    server = ThreadingHTTPServer(("127.0.0.1", 4182), SimpleHTTPRequestHandler)
    print("Import and alignment prototype: http://127.0.0.1:4182/?variant=B")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
