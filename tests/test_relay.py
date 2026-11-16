import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import app


class RawStream(httpx.AsyncByteStream):
    def __init__(self, content=b'file-content'):
        self.content = content

    async def __aiter__(self):
        yield self.content


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, RELAY_API_KEY='x' * 40)
        self.env.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.real_upstream = app.state.client
        self.seen = []

        async def handler(request):
            self.seen.append((request, await request.aread()))
            if request.url.path.endswith('/timeout'):
                raise httpx.ReadTimeout('simulated', request=request)
            if request.url.path.endswith('/offline'):
                raise httpx.ConnectError('simulated', request=request)
            if '/file/' in request.url.path:
                return httpx.Response(200, stream=RawStream(), headers={'content-type': 'application/octet-stream'})
            return httpx.Response(429, stream=RawStream(b'{"ok":false,"error_code":429}'),
                                  headers={'retry-after': '5', 'content-type': 'application/json'})

        app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.headers = {'X-API-Key': 'x' * 40}

    def tearDown(self):
        self.client.portal.call(app.state.client.aclose)
        app.state.client = self.real_upstream
        self.client.__exit__(None, None, None)
        self.env.stop()

    def test_auth_before_forwarding(self):
        self.assertEqual(self.client.get('/bot123:abc/getMe').status_code, 401)
        self.assertEqual(self.seen, [])
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok'})

    def test_json_query_and_upstream_error(self):
        response = self.client.post('/bot123:abc/sendMessage?x=a%2Bb', headers=self.headers, json={'text': 'hello'})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {'ok': False, 'error_code': 429})
        self.assertEqual(response.headers['retry-after'], '5')
        request, body = self.seen[0]
        self.assertEqual(str(request.url), 'https://api.telegram.org/bot123:abc/sendMessage?x=a%2Bb')
        self.assertEqual(body, b'{"text":"hello"}')
        self.assertNotIn('x-api-key', request.headers)

    def test_multipart(self):
        self.client.post('/bot123:abc/sendDocument', headers=self.headers,
                         data={'chat_id': '42'}, files={'document': ('a.txt', b'hello')})
        request, body = self.seen[0]
        self.assertIn('multipart/form-data; boundary=', request.headers['content-type'])
        self.assertIn(b'hello', body)
        self.assertIn(b'name="chat_id"', body)

    def test_download(self):
        response = self.client.get('/file/bot123:abc/documents/a.txt', headers=self.headers)
        self.assertEqual(response.content, b'file-content')
        self.assertEqual(self.seen[0][0].url.host, 'api.telegram.org')

    def test_failures(self):
        self.assertEqual(self.client.get('/bot123:abc/timeout', headers=self.headers).status_code, 504)
        self.assertEqual(self.client.get('/bot123:abc/offline', headers=self.headers).status_code, 502)

    def test_invalid_paths(self):
        for path in ('/botbad/getMe', '/file/bot123:abc/a/%2e%2e/b', '/file/bot123:abc/a%3Fb'):
            self.assertEqual(self.client.get(path, headers=self.headers).status_code, 400)
        self.assertEqual(self.seen, [])


if __name__ == '__main__':
    unittest.main()
