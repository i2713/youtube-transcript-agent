"""Download available YouTube captions as UTF-8 Markdown."""
import argparse
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def video_id(value):
    parsed = urlparse(value.strip())
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
        raise ValueError('Нужна ссылка на видео YouTube с https://')
    host = (parsed.hostname or '').lower()
    parts = parsed.path.strip('/').split('/')
    if host == 'youtu.be' and len(parts) == 1:
        candidate = parts[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        if parsed.path == '/watch':
            candidate = parse_qs(parsed.query).get('v', [''])[0]
        elif len(parts) == 2 and parts[0] in ('shorts', 'live', 'embed'):
            candidate = parts[1]
        else:
            candidate = ''
    else:
        candidate = ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate):
        raise ValueError('Не удалось найти ID видео в ссылке YouTube.')
    return candidate


def escape(text):
    text = ' '.join(text.split())
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_{}\[\]()#+.!|~-])', r'\\\1', text)


def markdown(captions):
    vid = captions.video_id
    lines = [f'# Транскрипт YouTube: {vid}', '',
             f'Источник: https://www.youtube.com/watch?v={vid}', '',
             f'Язык: {escape(captions.language)} ({escape(captions.language_code)})', '',
             'Тип субтитров: ' + ('автоматические' if captions.is_generated else 'авторские'), '',
             'Текст из субтитров YouTube, без пересказа и перевода.', '', '## Текст', '']
    for snippet in captions:
        seconds = max(0, int(snippet.start))
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        stamp = f'{hours:02}:{minutes:02}:{secs:02}'
        lines.extend([f'[{stamp}](https://www.youtube.com/watch?v={vid}&t={seconds}s) {escape(snippet.text)}', ''])
    return '\n'.join(lines)


def fetch(url, languages=None):
    from youtube_transcript_api import YouTubeTranscriptApi
    from requests import Session

    class TimedSession(Session):
        def request(self, *args, **kwargs):
            kwargs.setdefault('timeout', 30)
            return super().request(*args, **kwargs)

    vid = video_id(url)
    with TimedSession() as session:
        tracks = list(YouTubeTranscriptApi(http_client=session).list(vid))
        if languages:
            selected = next((t for lang in languages for t in sorted(tracks, key=lambda x: x.is_generated)
                             if t.language_code == lang), None)
            if selected is None:
                raise ValueError('Нет субтитров на запрошенном языке. Доступны: ' +
                                 ', '.join(t.language_code for t in tracks))
        else:
            # Automatic captions identify the spoken language when present.
            generated = next((t for t in tracks if t.is_generated), None)
            selected = next((t for t in tracks if not t.is_generated and generated
                             and t.language_code == generated.language_code), generated)
            selected = selected or next(iter(tracks), None)
        if selected is None:
            raise ValueError('У видео нет доступных субтитров.')
        return selected.fetch()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--language', action='append', help='Код языка; можно повторять в порядке предпочтения')
    parser.add_argument('--output-dir', default='outputs')
    args = parser.parse_args()
    try:
        vid = video_id(args.url)
        content = markdown(fetch(args.url, args.language))
        destination = Path(args.output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / f'{vid}.md'
        path.write_text(content, encoding='utf-8')
        print(path.resolve())
        return 0
    except Exception as exc:
        print(f'Не удалось получить транскрипт ({type(exc).__name__}): {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
