"""Throwaway static server for project/versioning prototype 8."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from os import chdir
from pathlib import Path


PROTOTYPE_DIR = Path(__file__).resolve().parent


if __name__ == "__main__":
    chdir(PROTOTYPE_DIR)
    server = ThreadingHTTPServer(("127.0.0.1", 4186), SimpleHTTPRequestHandler)
    print("Project/versioning prototype: http://127.0.0.1:4186/?variant=A")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
