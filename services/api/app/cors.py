"""Keep no-Origin image previews separate from CORS fetches in browser caches."""
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware


class CacheAwareCORSMiddleware(CORSMiddleware):
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await super().__call__(scope, receive, send)

        async def send_response(message):
            if message['type'] == 'http.response.start':
                headers = MutableHeaders(scope=message)
                vary = {part.strip().lower() for part in headers.get('vary', '').split(',')}
                # CORSMiddleware normally adds Vary only for allowed Origins.
                # <img> has no Origin; caching that response without Vary makes
                # a later fetch reuse it and fail the browser's CORS check.
                if 'origin' not in vary and '*' not in vary:
                    headers.add_vary_header('Origin')
            await send(message)

        await super().__call__(scope, receive, send_response)
