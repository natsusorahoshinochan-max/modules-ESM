"""Throwaway static server for ProteinPrompt residue-operation prototype 3."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from os import chdir
from pathlib import Path


PROTOTYPE_DIR = Path(__file__).resolve().parent


if __name__ == "__main__":
    chdir(PROTOTYPE_DIR)
    server = ThreadingHTTPServer(("127.0.0.1", 4181), SimpleHTTPRequestHandler)
    print("Residue operations prototype: http://127.0.0.1:4181/?variant=A")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
