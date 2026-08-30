"""Throwaway static server for Workflow canvas prototype 1."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from os import chdir


PROTOTYPE_DIR = Path(__file__).resolve().parent


if __name__ == "__main__":
    chdir(PROTOTYPE_DIR)
    server = ThreadingHTTPServer(("127.0.0.1", 4179), SimpleHTTPRequestHandler)
    print("Workflow canvas prototype: http://127.0.0.1:4179/?variant=A")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

