"""Throwaway static server for Prompt Studio prototype 2."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from os import chdir
from pathlib import Path


PROTOTYPE_DIR = Path(__file__).resolve().parent


if __name__ == "__main__":
    chdir(PROTOTYPE_DIR)
    server = ThreadingHTTPServer(("127.0.0.1", 4180), SimpleHTTPRequestHandler)
    print("Prompt Studio prototype: http://127.0.0.1:4180/?variant=A")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
