"""Measure word error rate and latency of a local Whisper server per model (#2596).

Run from a LAN machine against an OpenAI-compatible server such as Speaches:

    python scripts/measure_transcription.py --base-url http://<server>:8000/v1 \
        --model Systran/faster-whisper-small \
        --model deepdml/faster-whisper-large-v3-turbo-ct2

The samples are public German read speech from Google FLEURS (dev split,
CC BY 4.0), streamed until enough clips are cached; never the athlete's
recordings. An optional server key comes from TRANSCRIPTION_API_KEY. The
request matches the app's: multipart `file`, `model`, `language=de`, `prompt`. Prints a
Markdown table for the issue.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import statistics
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.providers.audio import TRANSCRIPTION_PROMPT
from backend.providers.http import multipart_form_data

FLEURS = "https://huggingface.co/datasets/google/fleurs/resolve/main/data/de_de/"


def normalized_words(text: str) -> list[str]:
    """Lowercase words without punctuation, so only wording counts."""
    return re.sub(r"[^\w\s]", " ", text.casefold()).split()


def word_errors(reference: list[str], hypothesis: list[str]) -> int:
    """Word-level Levenshtein distance (substitutions, insertions, deletions)."""
    previous = list(range(len(hypothesis) + 1))
    for i, word in enumerate(reference, 1):
        current = [i]
        for j, guess in enumerate(hypothesis, 1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (word != guess),
                )
            )
        previous = current
    return previous[-1]


def fetch_samples(cache: Path, count: int) -> list[tuple[Path, str]]:
    """Cache `count` clips with distinct sentences; returns (wav, reference)."""
    cache.mkdir(parents=True, exist_ok=True)
    index = cache / "samples.json"
    if index.exists():
        stored = json.loads(index.read_text(encoding="utf-8"))
        if len(stored) >= count:
            return [(cache / name, text) for name, text in stored[:count]]
    with urllib.request.urlopen(FLEURS + "dev.tsv", timeout=60) as response:
        rows = csv.reader(
            io.StringIO(response.read().decode("utf-8")),
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
        )
        references = {row[1]: row[2] for row in rows if len(row) > 2}
    chosen: list[tuple[str, str]] = []
    seen: set[str] = set()
    url = FLEURS + "audio/dev.tar.gz"
    with (
        urllib.request.urlopen(url, timeout=60) as response,
        tarfile.open(fileobj=response, mode="r|gz") as archive,
    ):
        for member in archive:
            name = Path(member.name).name
            text = references.get(name)
            if not member.isfile() or not text or text in seen:
                continue
            data = archive.extractfile(member)
            if data is None:
                continue
            (cache / name).write_bytes(data.read())
            seen.add(text)
            chosen.append((name, text))
            if len(chosen) >= count:
                break
    index.write_text(json.dumps(chosen, ensure_ascii=False), encoding="utf-8")
    return [(cache / name, text) for name, text in chosen]


def transcribe(base_url: str, key: str, model: str, audio: Path) -> str:
    body, content_type = multipart_form_data(
        [("model", model), ("language", "de"), ("prompt", TRANSCRIPTION_PROMPT)],
        "file",
        audio.name,
        "audio/wav",
        audio.read_bytes(),
    )
    request = urllib.request.Request(
        base_url.rstrip("/") + "/audio/transcriptions",
        data=body,
        headers={
            "Content-Type": content_type,
            **({"Authorization": f"Bearer {key}"} if key else {}),
        },
        method="POST",
    )
    # The app's own limit for one voice note.
    with urllib.request.urlopen(request, timeout=90) as response:
        return str(json.loads(response.read().decode("utf-8")).get("text") or "")


def seconds(audio: Path) -> float:
    """Duration from the RIFF chunks; FLEURS stores float WAV, which `wave` refuses."""
    data = audio.read_bytes()
    position, byte_rate, size = 12, 0, 0
    while position + 8 <= len(data):
        chunk, length = (
            data[position : position + 4],
            int.from_bytes(data[position + 4 : position + 8], "little"),
        )
        if chunk == b"fmt ":
            byte_rate = int.from_bytes(data[position + 16 : position + 20], "little")
        elif chunk == b"data":
            size = length
        position += 8 + length + (length & 1)
    return size / byte_rate if byte_rate else 0.0


def measure(
    base_url: str, key: str, model: str, samples: list[tuple[Path, str]]
) -> str:
    transcribe(base_url, key, model, samples[0][0])  # load the model first
    errors = words = 0
    latencies: list[float] = []
    for audio, reference in samples:
        started = time.perf_counter()
        text = transcribe(base_url, key, model, audio)
        latencies.append(time.perf_counter() - started)
        expected = normalized_words(reference)
        errors += word_errors(expected, normalized_words(text))
        words += len(expected)
    audio_seconds = sum(seconds(audio) for audio, _ in samples)
    latencies.sort()
    p90 = latencies[min(len(latencies) - 1, int(0.9 * len(latencies)))]
    return (
        f"| `{model}` | {len(samples)} | {100 * errors / max(words, 1):.1f} % "
        f"| {statistics.median(latencies):.2f} s | {p90:.2f} s "
        f"| {sum(latencies) / audio_seconds if audio_seconds else 0:.2f} |"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--base-url", required=True, help="e.g. http://<server>:8000/v1"
    )
    parser.add_argument("--model", action="append", required=True, help="repeatable")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(tempfile.gettempdir()) / "pacecraft-fleurs-de",
    )
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    samples = fetch_samples(args.cache, args.samples)
    if not samples:
        parser.error("no FLEURS samples could be fetched")
    key = os.environ.get("TRANSCRIPTION_API_KEY", "")
    total = sum(seconds(audio) for audio, _ in samples)
    print(
        f"{len(samples)} FLEURS de_de dev clips, {total:.0f} s audio (float WAV, 16 kHz).\n"
    )
    print("| Model | Clips | WER | Median latency | p90 latency | Real-time factor |")
    print("|---|---|---|---|---|---|")
    for model in args.model:
        print(measure(args.base_url, key, model, samples), flush=True)


if __name__ == "__main__":
    main()
