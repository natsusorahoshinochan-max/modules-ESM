"""Throwaway static server for Results Workbench prototype 7."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from os import chdir
from pathlib import Path


PROTOTYPE_DIR = Path(__file__).resolve().parent


if __name__ == "__main__":
    chdir(PROTOTYPE_DIR)
    server = ThreadingHTTPServer(("127.0.0.1", 4185), SimpleHTTPRequestHandler)
    print("Results Workbench prototype: http://127.0.0.1:4185/?variant=B")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
