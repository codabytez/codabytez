#!/usr/bin/env python3
"""
Mints the Spotify refresh token the card needs, once.

    python scripts/spotify_auth.py

Reads SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET from .env, opens your
browser, catches the redirect on the loopback address, exchanges the code, and
writes SPOTIFY_REFRESH_TOKEN back into .env.

Credentials are read from the file rather than taken as arguments, and the
token is written rather than printed, so neither ends up in argv, shell
history or terminal scrollback. --client-id/--client-secret still work if you
would rather pass them explicitly.

Before running, create an app at https://developer.spotify.com/dashboard and
add this exact redirect URI to it:

    http://127.0.0.1:8888/callback

A new app starts in development mode, which is all this needs: it allows up to
25 listed users, and you are the only one. No quota extension request required.

The refresh token does not expire; it is only invalidated if you revoke the
app's access or change your password.
"""

import argparse
import base64
import http.server
import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import requests

REDIRECT_URI = 'http://127.0.0.1:8888/callback'
AUTH_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'
# user-top-read is all the card uses. Deliberately not requesting playback or
# playlist scopes it has no need for.
SCOPES = 'user-top-read'

_result = {}
_done = threading.Event()


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        # Browsers ask for /favicon.ico unprompted. Answering it as if it were
        # the callback would strand the flow waiting for a redirect already
        # spent, so anything that is not the callback path is turned away.
        if parsed.path != '/callback':
            self.send_response(404)
            self.end_headers()
            return
        _result.update({k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()})
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        ok = 'code' in _result
        self.wfile.write(
            b'<body style="font:16px system-ui;padding:3rem">'
            + (b'<h2>Authorised.</h2><p>Close this tab and return to the terminal.</p>'
               if ok else
               b'<h2>Authorisation failed.</h2><p>Check the terminal.</p>')
            + b'</body>')
        _done.set()

    def log_message(self, *args):
        pass  # keep the console clean


def read_env(path):
    """The dotenv pairs, or {} if the file is absent."""
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env(path, key, value):
    """
    Set one key in a dotenv file, in place, preserving comments and order.

    Writing the token here rather than printing it keeps it out of terminal
    scrollback and shell history.
    """
    lines = []
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            lines = f.readlines()
    for i, line in enumerate(lines):
        if line.split('=', 1)[0].strip() == key:
            lines[i] = '{}={}\n'.format(key, value)
            break
    else:
        if lines and not lines[-1].endswith('\n'):
            lines.append('\n')
        lines.append('{}={}\n'.format(key, value))
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--client-id', help='defaults to SPOTIFY_CLIENT_ID in .env')
    parser.add_argument('--client-secret', help='defaults to SPOTIFY_CLIENT_SECRET in .env')
    parser.add_argument('--env', default='.env',
                        help='dotenv file to read credentials from and write the '
                             'refresh token back to (default: .env)')
    args = parser.parse_args()

    # Prefer the dotenv file so credentials never appear in argv or shell history.
    env = read_env(args.env)
    args.client_id = args.client_id or env.get('SPOTIFY_CLIENT_ID') or os.environ.get('SPOTIFY_CLIENT_ID')
    args.client_secret = args.client_secret or env.get('SPOTIFY_CLIENT_SECRET') or os.environ.get('SPOTIFY_CLIENT_SECRET')
    if not args.client_id or not args.client_secret:
        sys.exit('Need a client id and secret. Put SPOTIFY_CLIENT_ID and '
                 'SPOTIFY_CLIENT_SECRET in {}, or pass --client-id/--client-secret.'
                 .format(args.env))

    state = secrets.token_urlsafe(16)
    params = urllib.parse.urlencode({
        'client_id': args.client_id,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPES,
        'state': state,
    })

    try:
        server = http.server.HTTPServer(('127.0.0.1', 8888), _Handler)
    except OSError as error:
        sys.exit('Cannot listen on 127.0.0.1:8888 ({}). Something else is using '
                 'that port - stop it and try again.'.format(error))

    # serve_forever rather than handle_request: the flow needs to survive any
    # number of stray requests and stop on the callback, not on the first hit.
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = '{}?{}'.format(AUTH_URL, params)
    print('Opening your browser to authorise...')
    print('If it does not open, visit:\n  {}\n'.format(url))
    webbrowser.open(url)

    got_it = _done.wait(timeout=180)
    server.shutdown()
    if not got_it:
        sys.exit('Timed out after 3 minutes waiting for the redirect. Is the '
                 'redirect URI in your Spotify app set to exactly {}?'.format(REDIRECT_URI))

    if 'error' in _result:
        sys.exit('Spotify returned an error: {}'.format(_result['error']))
    if 'code' not in _result:
        sys.exit('No authorisation code in the redirect: {}'.format(_result))
    if _result.get('state') != state:
        sys.exit('State mismatch - the response did not come from the request we made.')

    basic = base64.b64encode(
        '{}:{}'.format(args.client_id, args.client_secret).encode()).decode()
    response = requests.post(TOKEN_URL, timeout=30,
                             headers={'Authorization': 'Basic ' + basic},
                             data={'grant_type': 'authorization_code',
                                   'code': _result['code'],
                                   'redirect_uri': REDIRECT_URI})
    if response.status_code != 200:
        sys.exit('Token exchange failed ({}): {}'.format(response.status_code, response.text))

    refresh_token = response.json().get('refresh_token')
    if not refresh_token:
        sys.exit('No refresh_token in the response: {}'.format(response.json()))

    write_env(args.env, 'SPOTIFY_REFRESH_TOKEN', refresh_token)
    print('\nDone. SPOTIFY_REFRESH_TOKEN written to {} (not printed here, so it'
          '\nstays out of your scrollback and shell history).'.format(args.env))
    print('\nTo mirror it into CI, run these and paste each value when prompted:')
    print('  gh secret set SPOTIFY_CLIENT_ID')
    print('  gh secret set SPOTIFY_CLIENT_SECRET')
    print('  gh secret set SPOTIFY_REFRESH_TOKEN')


if __name__ == '__main__':
    main()
