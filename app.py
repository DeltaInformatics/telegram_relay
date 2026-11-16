import hmac
import os
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask


@asynccontextmanager
async def lifespan(app: FastAPI):
    key = os.environ.get('RELAY_API_KEY', '')
    if len(key) < 32 or key == 'replace-with-a-random-key-at-least-32-characters':
        raise RuntimeError('Set RELAY_API_KEY to a random secret of at least 32 characters')
    app.state.api_key = key
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(120, connect=10), follow_redirects=False,
        trust_env=False,
    ) as client:
        app.state.client = client
        yield


app = FastAPI(title='Telegram relay', lifespan=lifespan, docs_url=None, redoc_url=None)


async def authorize(request: Request):
    supplied = request.headers.get('x-api-key', '')
    if not hmac.compare_digest(supplied.encode(), request.app.state.api_key.encode()):
        raise HTTPException(401, 'Invalid relay API key')


@app.get('/health')
async def health():
    return {'status': 'ok'}


async def forward(request: Request, path: str):
    # Construct the origin ourselves: callers cannot choose another host.
    url = httpx.URL('https://api.telegram.org/' + path).copy_with(
        query=request.scope['query_string']
    )
    headers = {}
    for name in ('content-type', 'content-length', 'range'):
        if name in request.headers:
            headers[name] = request.headers[name]
    upstream_request = request.app.state.client.build_request(
        request.method, url, headers=headers, content=request.stream(),
    )
    try:
        response = await request.app.state.client.send(upstream_request, stream=True)
    except httpx.TimeoutException:
        raise HTTPException(504, 'Telegram request timed out') from None
    except httpx.RequestError:
        raise HTTPException(502, 'Cannot reach Telegram') from None
    response_headers = {
        name: value for name, value in response.headers.items()
        if name in {'content-type', 'content-length', 'content-encoding',
                    'content-range', 'accept-ranges', 'retry-after',
                    'content-disposition'}
    }

    async def body():
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()

    return StreamingResponse(
        body(), status_code=response.status_code, headers=response_headers,
        background=BackgroundTask(response.aclose),
    )


TOKEN = r'[0-9]+:[A-Za-z0-9_-]+'


@app.api_route('/bot{token}/{method}', methods=['GET', 'POST'], dependencies=[Depends(authorize)])
async def bot_method(token: str, method: str, request: Request):
    if not re.fullmatch(TOKEN, token) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', method):
        raise HTTPException(400, 'Invalid bot token or method')
    return await forward(request, f'bot{token}/{method}')


@app.get('/file/bot{token}/{file_path:path}', dependencies=[Depends(authorize)])
async def download(token: str, file_path: str, request: Request):
    if (not re.fullmatch(TOKEN, token)
            or not re.fullmatch(r'[A-Za-z0-9_./-]+', file_path)
            or any(part in ('', '.', '..') for part in file_path.split('/'))):
        raise HTTPException(400, 'Invalid bot token or file path')
    return await forward(request, f'file/bot{token}/{file_path}')
