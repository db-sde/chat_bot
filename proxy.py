import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI(title="CORS Proxy for Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def proxy(path: str, request: Request):
    method = request.method
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    body = await request.body()
    
    async def stream_response():
        async with httpx.AsyncClient() as client:
            url = f"http://127.0.0.1:8000/{path}"
            try:
                async with client.stream(
                    method,
                    url,
                    headers=headers,
                    params=dict(request.query_params),
                    content=body,
                    timeout=60.0
                ) as response:
                    async for chunk in response.aiter_bytes():
                         yield chunk
            except Exception as e:
                yield f"event: error\ndata: {str(e)}\n\n".encode()

    return StreamingResponse(stream_response())

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
