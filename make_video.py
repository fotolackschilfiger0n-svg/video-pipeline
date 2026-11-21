import asyncio
import json
import os
import random
import subprocess

import edge_tts
import requests

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
PEXELS_KEY = os.environ["PEXELS_API_KEY"]
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
TOPIC = os.environ.get("TOPIC") or "überraschende Fakten über den Weltraum"
VOICE = os.environ.get("VOICE") or "de-DE-KatjaNeural"
OUT = "out"
os.makedirs(OUT, exist_ok=True)


def run(cmd):
    subprocess.run(cmd, check=True)


def duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def make_script():
    prompt = (
        f"Schreibe ein Skript für ein 30-Sekunden-Kurzvideo auf Deutsch zum Thema: {TOPIC}. "
        "Starte mit einem starken Hook. 6 bis 8 kurze Sätze, je maximal 15 Wörter. "
        "Antworte NUR als JSON: "
        '{"title": "...", "sentences": ["..."], "search_query": "englisches Stichwort für Stock-Videos"}'
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    r = requests.post(
        url,
        headers={"x-goog-api-key": GEMINI_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"responseMimeType": "application/json"}},
        timeout=90)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


async def tts_all(sentences):
    files = []
    for i, s in enumerate(sentences):
        p = f"{OUT}/a{i}.mp3"
        await edge_tts.Communicate(s, VOICE).save(p)
        files.append(p)
    return files


def srt_time(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02}:{int(m):02}:{int(s):02},{int((s % 1) * 1000):03}"


def fetch_clip(query):
    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": PEXELS_KEY},
        params={"query": query, "orientation": "portrait", "per_page": 10},
        timeout=60)
    r.raise_for_status()
    videos = r.json()["videos"]
    if not videos:
        raise SystemExit(f"Keine Clips für '{query}' gefunden")
    files = random.choice(videos)["video_files"]
    files = sorted(files, key=lambda f: abs(f["height"] - 1920))
    data = requests.get(files[0]["link"], timeout=120)
    data.raise_for_status()
    path = f"{OUT}/clip.mp4"
    with open(path, "wb") as f:
        f.write(data.content)
    return path


def main():
    script = make_script()
    sentences = script["sentences"]
    print("Titel:", script["title"])

    audio_files = asyncio.run(tts_all(sentences))

    # Untertitel (SRT) aus den Dauern der Einzelsätze
    t = 0.0
    srt = []
    for i, (s, p) in enumerate(zip(sentences, audio_files), 1):
        d = duration(p)
        srt.append(f"{i}\n{srt_time(t)} --> {srt_time(t + d)}\n{s}\n")
        t += d
    total = t
    with open(f"{OUT}/subs.srt", "w", encoding="utf-8") as f:
        f.write("\n".join(srt))

    # Audio zusammenfügen
    with open(f"{OUT}/list.txt", "w") as f:
        for p in audio_files:
            f.write(f"file '{os.path.basename(p)}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"{OUT}/list.txt",
         "-c", "copy", f"{OUT}/audio.mp3"])

    clip = fetch_clip(script["search_query"])

    style = "FontSize=11,Bold=1,Outline=3,Alignment=2,MarginV=45"
    vf = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          f"subtitles={OUT}/subs.srt:force_style='{style}'")
    run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", clip, "-i", f"{OUT}/audio.mp3",
         "-vf", vf, "-map", "0:v", "-map", "1:a", "-t", f"{total:.2f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
         "-pix_fmt", "yuv420p", "-c:a", "aac", f"{OUT}/video.mp4"])

    with open(f"{OUT}/title.txt", "w", encoding="utf-8") as f:
        f.write(script["title"])
    print("Fertig:", f"{OUT}/video.mp4")


if __name__ == "__main__":
    main()
