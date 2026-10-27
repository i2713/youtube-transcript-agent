"""Personal GPT Action service. Run a single worker behind HTTPS."""
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from transcript import video_id

API_KEY = os.environ.get('API_KEY', '')
BASE_URL = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
if len(API_KEY) < 32:
    raise RuntimeError('Set API_KEY to a random secret of at least 32 characters')
parsed = urlparse(BASE_URL)
if parsed.scheme != 'https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
    raise RuntimeError('Set PUBLIC_BASE_URL to your HTTPS origin, without a path')

app = FastAPI(title='YouTube Transcript to Markdown', version='1.0.0', servers=[{'url': BASE_URL}])
auth_scheme = HTTPBearer(auto_error=False)
slots = threading.BoundedSemaphore(2)
lock = threading.Lock()
files = {}
TTL = 600
MAX_BYTES = 9_000_000
MAX_FILES = 20


def authenticate(credentials: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    if credentials is None or not secrets.compare_digest(credentials.credentials, API_KEY):
        raise HTTPException(401, 'Неверный ключ доступа')


class TranscriptRequest(BaseModel):
    url: str = Field(min_length=12, max_length=2048, description='YouTube video URL')
    language: str | None = Field(default=None, pattern=r'^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$', max_length=35)


class TranscriptResponse(BaseModel):
    filename: str
    openaiFileResponse: list[str]


@app.get('/health', include_in_schema=False)
def health():
    return {'status': 'ok'}


@app.post('/transcript', operation_id='getYoutubeTranscript', response_model=TranscriptResponse,
          dependencies=[Depends(authenticate)],
          summary='Get available YouTube captions as a downloadable Markdown file',
          openapi_extra={'x-openai-isConsequential': False})
def transcript(request: TranscriptRequest):
    try:
        vid = video_id(request.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not slots.acquire(blocking=False):
        raise HTTPException(429, 'Сервис занят. Повторите позже.')
    try:
        with tempfile.TemporaryDirectory() as folder:
            command = [sys.executable, str(Path(__file__).with_name('transcript.py')),
                       request.url, '--output-dir', folder]
            if request.language:
                command += ['--language', request.language]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=35)
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(504, 'YouTube не ответил вовремя. Повторите позже.') from exc
            if result.returncode:
                reason = result.stderr
                if 'RequestBlocked' in reason or 'IpBlocked' in reason:
                    raise HTTPException(502, 'YouTube блокирует адрес сервера. Нужен другой адрес или настроенный прокси.')
                if any(error in reason for error in ['TranscriptsDisabled', 'NoTranscriptFound', 'VideoUnavailable', 'ValueError']):
                    raise HTTPException(422, 'Видео или субтитры на выбранном языке недоступны.')
                raise HTTPException(502, 'Не удалось получить субтитры YouTube. Повторите позже.')
            path = Path(folder) / f'{vid}.md'
            if path.stat().st_size > MAX_BYTES:
                raise HTTPException(413, 'Транскрипт превышает допустимый размер файла.')
            content = path.read_bytes()
        token = secrets.token_urlsafe(32)
        with lock:
            now = time.monotonic()
            for old in list(files):
                if files[old][0] <= now:
                    del files[old]
            if len(files) >= MAX_FILES:
                raise HTTPException(429, 'Хранилище временных файлов заполнено. Повторите через 10 минут.')
            files[token] = (now + TTL, f'{vid}.md', content)
        return {'filename': f'{vid}.md', 'openaiFileResponse': [f'{BASE_URL}/files/{token}']}
    finally:
        slots.release()


@app.get('/files/{token}', include_in_schema=False)
def download(token: str):
    with lock:
        item = files.get(token)
        if item is None:
            raise HTTPException(404, 'Файл не найден')
        if item[0] <= time.monotonic():
            del files[token]
            raise HTTPException(404, 'Ссылка истекла. Запросите транскрипт повторно.')
        _, filename, content = item
    return Response(content, media_type='text/markdown; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
