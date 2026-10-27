import os
os.environ['API_KEY'] = 'test-key-' + 'x' * 40
os.environ['PUBLIC_BASE_URL'] = 'https://example.com'
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
import server

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        self.headers = {'Authorization': 'Bearer ' + os.environ['API_KEY']}
        server.files.clear()

    def test_auth_and_url_validation(self):
        self.assertEqual(self.client.post('/transcript', json={'url': 'https://youtu.be/abcdefghijk'}).status_code, 401)
        response = self.client.post('/transcript', headers=self.headers, json={'url': 'https://example.com/abcdefghijk'})
        self.assertEqual(response.status_code, 422)

    def test_file_roundtrip_and_expiry(self):
        def run(command, **kwargs):
            Path(command[4], 'abcdefghijk.md').write_text('# Привет\n', encoding='utf-8')
            return SimpleNamespace(returncode=0)
        with patch('server.subprocess.run', side_effect=run):
            response = self.client.post('/transcript', headers=self.headers, json={'url': 'https://youtu.be/abcdefghijk'})
        self.assertEqual(response.status_code, 200, response.text)
        url = response.json()['openaiFileResponse'][0]
        result = self.client.get(url)
        self.assertEqual(result.text, '# Привет\n')
        self.assertIn('abcdefghijk.md', result.headers['content-disposition'])
        with patch('server.time.monotonic', return_value=float('inf')):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_upstream_timeout(self):
        with patch('server.subprocess.run', side_effect=subprocess.TimeoutExpired('test', 35)):
            result = self.client.post('/transcript', headers=self.headers, json={'url': 'https://youtu.be/abcdefghijk'})
        self.assertEqual(result.status_code, 504)

    def test_youtube_block(self):
        with patch('server.subprocess.run', return_value=SimpleNamespace(returncode=1, stderr='IpBlocked')):
            result = self.client.post('/transcript', headers=self.headers, json={'url': 'https://youtu.be/abcdefghijk'})
        self.assertEqual(result.status_code, 502)

    def test_schema(self):
        schema = self.client.get('/openapi.json').json()
        self.assertEqual(schema['paths']['/transcript']['post']['operationId'], 'getYoutubeTranscript')
        self.assertTrue(schema['paths']['/transcript']['post']['security'])
        self.assertNotIn('/files/{token}', schema['paths'])
