#!/usr/bin/env python3
"""MCP tool server for OMP Local STT (Speech-to-Text) and TTS (Text-to-Speech)."""

import json
import os
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("local-speech")

STT_URL = os.getenv("STT_BASE_URL", "http://localhost:50090/v1")
TTS_URL = os.getenv("TTS_BASE_URL", "http://localhost:50095/v1")


@mcp.tool()
def transcribe_audio(file_path: str, language: str = "auto") -> dict[str, Any]:
    """Transcribe an audio file using local Whisper STT service (port 50090)."""
    if not os.path.exists(file_path):
        return {"error": f"File '{file_path}' does not exist."}

    url = f"{STT_URL}/audio/transcriptions"
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"

    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        body = []
        body.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n'.encode()
        )
        if language != "auto":
            body.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\n{language}\r\n'.encode()
            )

        filename = os.path.basename(file_path)
        body.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
        )
        body.append(file_bytes)
        body.append(f"\r\n--{boundary}--\r\n".encode())

        req_data = b"".join(body)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=30) as resp:
            res_body = resp.read().decode("utf-8")
            return json.loads(res_body)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def synthesize_speech(
    text: str, voice: str = "serena", output_file: str = ""
) -> dict[str, Any]:
    """Synthesize text to speech using local TTS service (port 50095)."""
    url = f"{TTS_URL}/audio/speech"
    payload = {
        "model": "qwen3-tts",
        "input": text,
        "voice": voice,
        "response_format": "wav",
    }

    req_data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")

    try:
        out_path = output_file or os.path.expanduser("~/.omp/scratch/speech_output.wav")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        with urllib.request.urlopen(req, timeout=30) as resp:
            audio_data = resp.read()
            with open(out_path, "wb") as out_f:
                out_f.write(audio_data)
        return {"status": "success", "file_path": out_path, "bytes": len(audio_data)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
