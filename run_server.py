"""Run a Windows-compatible production WSGI server, bound locally by default."""
import os
from waitress import serve
from app import create_app
if __name__ == '__main__':
    serve(create_app(), host=os.environ.get('TECHMORAL_HOST', '127.0.0.1'),
          port=int(os.environ.get('TECHMORAL_PORT', '8080')), threads=4)
