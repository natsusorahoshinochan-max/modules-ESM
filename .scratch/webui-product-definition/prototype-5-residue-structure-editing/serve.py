"""Throwaway static server for residue-level structure-editing prototype 5."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from os import chdir
from pathlib import Path


PROTOTYPE_DIR = Path(__file__).resolve().parent


if __name__ == "__main__":
    chdir(PROTOTYPE_DIR)
    server = ThreadingHTTPServer(("127.0.0.1", 4183), SimpleHTTPRequestHandler)
    print("Residue structure-editing prototype: http://127.0.0.1:4183/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
