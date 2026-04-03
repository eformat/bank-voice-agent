"""Domain-specific tools for voice agents.

This module provides specialized tools:
- convert_text_to_speech: For text to speech agent
- convert_speech_to_text: For speech to text agent
- listen_for_user_speech: Capture microphone audio and transcribe it
"""

import base64
import io
import os
import time
import wave
from pathlib import Path
from typing import Iterator

import requests
try:
    import simpleaudio as sa
except Exception:  # pragma: no cover - optional audio backend
    sa = None
from dotenv import load_dotenv
from langchain.tools import tool
from openai import OpenAI

load_dotenv()

TTS_URL = os.getenv("TTS_URL", "TTS_URL")
TTS_MODEL = os.getenv("TTS_MODEL", "TTS_MODEL")
TTS_VOICE = os.getenv("TTS_VOICE", "TTS_VOICE")
PLAY_AUDIO = os.getenv("PLAY_AUDIO", "0").lower() in ("1", "true", "yes", "y")
TTS_SAMPLE_RATE = int(os.getenv("TTS_SAMPLE_RATE", "24000"))
TTS_API_KEY = os.getenv("TTS_API_KEY", os.getenv("API_KEY", ""))
# Higgs streamed audio can arrive in fairly large bursts depending on `audio_chunk_size`.
# A smaller default yields smoother realtime playback in the browser.
TTS_AUDIO_CHUNK_SIZE = int(os.getenv("TTS_AUDIO_CHUNK_SIZE", "5"))
TTS_TIMEOUT_S = float(os.getenv("TTS_TIMEOUT_S", "30"))

STT_URL = os.getenv("STT_URL", "STT_URL")
STT_MODEL = os.getenv("STT_MODEL", "STT_MODEL")
STT_TOKEN = os.getenv("STT_TOKEN", "STT_TOKEN")

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes (int16)
_LISTENING_PAUSED = False


def pause_listening() -> None:
    """Signal to pause background listening callbacks."""
    global _LISTENING_PAUSED
    _LISTENING_PAUSED = True
    print("Listening paused")


def resume_listening() -> None:
    """Signal to resume background listening callbacks."""
    global _LISTENING_PAUSED
    _LISTENING_PAUSED = False
    print("Listening resumed")


def is_listening_paused() -> bool:
    """Return True if listening is currently paused."""
    return _LISTENING_PAUSED


@tool
def log_inquiry(inquiry: str) -> str:
    """Log a customer inquiry or request."""
    print("log_inquiry tool called with inquiry: ", inquiry)
    return f"Logged inquiry: {inquiry}"


@tool
def convert_text_to_speech(text: str = ""):
    """Convert text to speech and play the generated audio."""
    print("convert_text_to_speech tool called with text: ", text)

    if not text or not text.strip():
        # IMPORTANT: allow tool calls with missing args (LLM sometimes emits {}).
        # Returning a string avoids crashing the graph/tool pipeline.
        return "No text provided for speech synthesis (empty tool call)."

    if not PLAY_AUDIO:
        # In cloud/container environments, audio playback is not possible.
        # We keep the tool callable but do not attempt to play.
        return "Audio playback disabled (PLAY_AUDIO=0)."

    if sa is None:
        return "Audio playback is unavailable because simpleaudio is not installed."

    pause_listening()

    url = TTS_URL
    payload = {
        "model": TTS_MODEL,
        "voice": TTS_VOICE,
        "input": text,
        "response_format": "pcm",
    }

    try:
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
    except requests.RequestException as exc:
        return f"Failed to generate audio: {exc}"

    pcm_audio = response.content
    if not pcm_audio:
        return "No audio was returned from the service."

    # simpleaudio expects raw PCM; ensure we have complete frames (2 bytes/sample).
    if len(pcm_audio) % 2 != 0:
        pcm_audio += b"\x00"

    try:
        play_obj = sa.play_buffer(
            pcm_audio, num_channels=1, bytes_per_sample=2, sample_rate=TTS_SAMPLE_RATE
        )
        play_obj.wait_done()
    except Exception as exc:
        return f"Failed to play audio: {exc}"
    finally:
        time.sleep(0.75)  # Wait for the audio to finish playing
        resume_listening()

    return "Played generated speech."


def generate_tts_wav_b64(text: str) -> dict:
    """Generate TTS audio as WAV (base64), suitable for returning to a browser."""
    if not text or not text.strip():
        return {"audio_b64": "", "format": "wav", "sample_rate": TTS_SAMPLE_RATE}

    url = TTS_URL
    payload = {
        "model": TTS_MODEL,
        "voice": TTS_VOICE,
        "input": text,
        "response_format": "pcm",
    }

    response = requests.post(url, json=payload, timeout=60)
    response.raise_for_status()
    pcm_audio = response.content
    if len(pcm_audio) % 2 != 0:
        pcm_audio += b"\x00"

    with io.BytesIO() as buf:
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(TTS_SAMPLE_RATE)
            wf.writeframes(pcm_audio)
        wav_bytes = buf.getvalue()

    return {
        "audio_b64": base64.b64encode(wav_bytes).decode("ascii"),
        "format": "wav",
        "sample_rate": TTS_SAMPLE_RATE,
    }


def stream_tts_pcm_chunks(text: str) -> Iterator[bytes]:
    """Stream TTS audio as raw PCM int16 chunks (s16le).

    This follows the `test-tts-stream.py` approach for OpenAI-compatible audio streaming.
    Expects `TTS_URL` to be an OpenAI-compatible base URL ending in `/v1` (or similar).
    """
    if not text or not text.strip():
        return

    if not (TTS_URL.startswith("http://") or TTS_URL.startswith("https://")):
        raise RuntimeError(
            f"TTS_URL must be an OpenAI-compatible base URL (got {TTS_URL!r})."
        )

    voice_mode = (TTS_VOICE or "").strip().lower()

    def _encode_b64_file(p: Path) -> str:
        return base64.b64encode(p.read_bytes()).decode("utf-8")

    # Voice cloning (Higgs): condition the chat with a reference audio + its transcript,
    # matching the pattern from `test-tts-stream.py`.
    use_voice_clone = voice_mode in {"belinda", "mike", "clone", "voice_clone"}
    voice_wav = Path(__file__).resolve().parents[1] / f"{TTS_VOICE}.wav"
    voice_txt = Path(__file__).resolve().parents[1] / f"{TTS_VOICE}.txt"

    client = OpenAI(
        api_key=TTS_API_KEY or "fake",
        base_url=TTS_URL,
        timeout=TTS_TIMEOUT_S,
        max_retries=1,
    )

    if use_voice_clone:
        if not voice_wav.exists() or not voice_txt.exists():
            raise RuntimeError(
                f"Voice clone requested (TTS_VOICE={TTS_VOICE!r}) but files missing: "
                f"{voice_wav} / {voice_txt}"
            )
        audio_text = voice_txt.read_text(encoding="utf-8", errors="replace")
        audio_b64 = _encode_b64_file(voice_wav)
        messages = [
            {"role": "user", "content": audio_text},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_b64, "format": "wav"},
                    }
                ],
            },
            {"role": "user", "content": text},
        ]
    else:
        # Plain streamed TTS prompt (no voice conditioning).
        system_prompt = (
            "Generate audio following instruction.\n\n"
            "<|scene_desc_start|>\n"
            "Audio is recorded from a quiet room.\n"
            "<|scene_desc_end|>"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]

    chat_completion = client.chat.completions.create(
        messages=messages,
        model=TTS_MODEL,
        stream=True,
        modalities=["text", "audio"],
        temperature=1.0,
        top_p=0.95,
        extra_body={"top_k": 50, "audio_chunk_size": TTS_AUDIO_CHUNK_SIZE},
        stop=["<|eot_id|>", "<|end_of_text|>", "<|audio_eos|>"],
    )

    for chunk in chat_completion:
        if (
            chunk.choices
            and hasattr(chunk.choices[0].delta, "audio")
            and chunk.choices[0].delta.audio
        ):
            audio_b64 = chunk.choices[0].delta.audio.get("data")
            if audio_b64:
                yield base64.b64decode(audio_b64)


@tool
def convert_speech_to_text(audio: bytes):
    """Convert speech (audio bytes) to text using the Whisper endpoint."""
    print("convert_speech_to_text tool called ...")

    if not audio:
        return "No audio provided for speech-to-text."

    pause_listening()

    try:
        headers = {}
        if STT_TOKEN:
            headers["Authorization"] = f"Bearer {STT_TOKEN}"

        files = {
            "file": ("audio.wav", audio, "audio/wav"),
            "model": (None, STT_MODEL),
        }

        try:
            resp = requests.post(STT_URL, headers=headers, files=files, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as exc:
            return f"Failed to transcribe audio: {exc}"

        try:
            data = resp.json()
        except ValueError:
            return "Speech-to-text response was not valid JSON."

        transcript = data.get("text") or data.get("transcription")
        if not transcript:
            return "Speech-to-text succeeded but no transcript was returned."

        return transcript
    finally:
        resume_listening()


@tool
def lookup_account(query: str) -> dict:
    """Look up account information for a customer."""
    print("lookup_account tool called with query: ", query)
    return {"status": "Account information retrieved", "query": query}


@tool
def get_service_type(query: str) -> dict:
    """Supported banking service types."""
    service_type_dictionary = {
        "credit_card": "Credit Card",
        "personal_loan": "Personal Loan",
        "mortgage": "Mortgage",
        "savings_account": "Savings Account",
        "checking_account": "Checking Account",
        "investment": "Investment",
        "retirement": "Retirement Planning",
    }
    return service_type_dictionary


import hashlib
import random


@tool
def check_credit_score(
    ssn_last4: str = "0000",
    first_name: str = "John",
    last_name: str = "Doe",
    date_of_birth: str = "1985-01-15",
) -> dict:
    """Perform a credit score check (simulated Equifax-style report).

    Uses the customer's last 4 digits of SSN, name, and date of birth to
    pull a credit report. Returns a FICO score (300-850), rating tier,
    and key credit factors based on standard US credit bureau data.

    Args:
        ssn_last4: Last 4 digits of the customer's Social Security Number.
        first_name: Customer's first name.
        last_name: Customer's last name.
        date_of_birth: Customer's date of birth (YYYY-MM-DD).
    """
    print(
        f"check_credit_score tool called for {first_name} {last_name} "
        f"(SSN ***-**-{ssn_last4}, DOB {date_of_birth})"
    )

    # Deterministic but varied score seeded from inputs so the same
    # customer always gets the same result within a session.
    seed = hashlib.sha256(
        f"{ssn_last4}{first_name}{last_name}{date_of_birth}".encode()
    ).hexdigest()
    rng = random.Random(seed)

    # FICO score distribution roughly mirrors US population:
    #   ~20% Exceptional (800-850), ~25% Very Good (740-799),
    #   ~21% Good (670-739), ~18% Fair (580-669), ~16% Poor (300-579)
    score = rng.choices(
        population=[
            rng.randint(800, 850),  # Exceptional
            rng.randint(740, 799),  # Very Good
            rng.randint(670, 739),  # Good
            rng.randint(580, 669),  # Fair
            rng.randint(300, 579),  # Poor
        ],
        weights=[20, 25, 21, 18, 16],
        k=1,
    )[0]

    # Rating tier per Equifax/FICO ranges
    if score >= 800:
        rating = "Exceptional"
    elif score >= 740:
        rating = "Very Good"
    elif score >= 670:
        rating = "Good"
    elif score >= 580:
        rating = "Fair"
    else:
        rating = "Poor"

    # Simulate key credit factors (Equifax report style)
    num_accounts = rng.randint(3, 25)
    credit_utilization = rng.randint(1, 85)  # percentage
    oldest_account_years = rng.randint(1, 30)
    recent_inquiries = rng.randint(0, 8)
    late_payments = rng.randint(0, 6) if score < 740 else 0
    total_debt = rng.randint(500, 120000)
    available_credit = rng.randint(2000, 100000)
    collections = rng.randint(0, 3) if score < 670 else 0
    bankruptcies = 1 if score < 500 and rng.random() < 0.3 else 0

    # Key factors affecting score (similar to Equifax report)
    factors = []
    if credit_utilization > 30:
        factors.append("High credit utilization ratio")
    if late_payments > 0:
        factors.append(f"{late_payments} late payment(s) on record")
    if recent_inquiries > 3:
        factors.append("Too many recent credit inquiries")
    if oldest_account_years < 3:
        factors.append("Limited credit history length")
    if collections > 0:
        factors.append(f"{collections} account(s) in collections")
    if bankruptcies > 0:
        factors.append("Bankruptcy on record")
    if num_accounts < 5:
        factors.append("Few active credit accounts")
    if not factors:
        factors.append("Strong payment history")
        factors.append("Low credit utilization")
        factors.append("Long credit history")

    result = {
        "bureau": "Equifax",
        "report_type": "Soft Inquiry (no impact to score)",
        "customer": f"{first_name} {last_name}",
        "fico_score": score,
        "rating": rating,
        "score_range": "300-850",
        "credit_utilization_pct": credit_utilization,
        "total_accounts": num_accounts,
        "oldest_account_years": oldest_account_years,
        "recent_inquiries_last_2yr": recent_inquiries,
        "late_payments": late_payments,
        "collections": collections,
        "bankruptcies": bankruptcies,
        "total_debt_usd": total_debt,
        "available_credit_usd": available_credit,
        "key_factors": factors,
    }

    print(f"check_credit_score → FICO {score} ({rating})")
    return result
