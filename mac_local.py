"""Run a temporary HTTPS tunnel and the personal GPT service on macOS."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cloudflared', required=True)
    parser.add_argument('--state-dir', required=True)
    args = parser.parse_args()
    state = Path(args.state_dir).resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    keyfile = state / 'api-key'
    if not keyfile.exists():
        fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_urlsafe(32))
    processes = []
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        # Port is fixed so an existing instance is detected before starting a tunnel.
        import socket
        with socket.socket() as check:
            check.bind(('127.0.0.1', 8765))
        with (state / 'tunnel.log').open('w') as log:
            tunnel = subprocess.Popen([args.cloudflared, 'tunnel', '--no-autoupdate', '--protocol', 'http2', '--url', 'http://127.0.0.1:8765'], stdout=log, stderr=log)
            processes.append(tunnel)
            deadline = time.monotonic() + 60
            base = None
            while time.monotonic() < deadline and tunnel.poll() is None:
                match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', (state / 'tunnel.log').read_text())
                if match:
                    base = match.group()
                    break
                time.sleep(0.5)
            if not base:
                raise RuntimeError('Не удалось создать туннель. Смотрите tunnel.log.')
            env = dict(os.environ, API_KEY=keyfile.read_text().strip(), PUBLIC_BASE_URL=base)
            with (state / 'server.log').open('w') as serverlog:
                server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', '8765', '--workers', '1', '--no-access-log'], cwd=Path(__file__).parent, env=env, stdout=serverlog, stderr=serverlog)
                processes.append(server)
                processes.append(subprocess.Popen(['/usr/bin/caffeinate', '-i', '-w', str(server.pid)]))
                for _ in range(40):
                    if server.poll() is not None:
                        raise RuntimeError('Сервер не запустился. Смотрите server.log.')
                    try:
                        with urlopen('http://127.0.0.1:8765/health', timeout=1):
                            break
                    except OSError:
                        time.sleep(0.25)
                else:
                    raise RuntimeError('Сервер не ответил.')
                (state / 'connection.json').write_text(json.dumps({'url': base, 'schema': base + '/openapi.json'}, indent=2))
                print('Сервис запущен. Не закрывайте это окно и крышку Mac.', flush=True)
                print('Схема для GPT: ' + base + '/openapi.json', flush=True)
                print('После перезапуска обновите адрес схемы в GPT. Остановка: Ctrl+C.', flush=True)
                while server.poll() is None and tunnel.poll() is None:
                    time.sleep(1)
                raise RuntimeError('Сервер или туннель остановился. Запустите заново.')
    except KeyboardInterrupt:
        print('Остановлено.')
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        (state / 'connection.json').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
