import time
import uuid
import tempfile
import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import requests
from moviepy import VideoFileClip
from sync import Sync
from sync.common import Video, Audio, GenerationOptions
from sync.core.api_error import ApiError
import openai
from elevenlabs.client import ElevenLabs


@dataclass
class BabelfishArgs:
    sync_api_key: str
    openai_api_key: str
    eleven_api_key: str
    video_url: str
    target_language: str

    source_language: str = ""
    output_json_path: str = ""
    lipsync_model: str = "lipsync-2"
    tts_model: str = "eleven_multilingual_v2"
    gpt_model: str = "gpt-3.5-turbo"
    transcription_model: str = "whisper-1"
    voice_id: str = ""
    sync_mode: str = "bounce"
    segment_start: float = -1
    segment_end: float = -1
    poll_interval: int = 10  # hidden from frontend
    tmp_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "sync_translate")


class SyncTranslateInputNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_url": ("STRING", {"default": ""}),
                "target_language": ("STRING", {"default": "Spanish"}),
                "sync_api_key": ("STRING", {"default": ""}),
                "openai_api_key": ("STRING", {"default": ""}),
                "eleven_api_key": ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("BABELFISH_ARGS",)
    RETURN_NAMES = ("babelfish_args",)
    FUNCTION = "package_args"
    CATEGORY = "Sync.so"

    def package_args(self, video_url, target_language, sync_api_key, openai_api_key, eleven_api_key):
        args = BabelfishArgs(
            video_url=video_url,
            target_language=target_language,
            sync_api_key=sync_api_key,
            openai_api_key=openai_api_key,
            eleven_api_key=eleven_api_key,
        )
        return (args,)


class SyncTranslateNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "babelfish_args": ("BABELFISH_ARGS",),
            },
            "optional": {
                "source_language": ("STRING", {"default": ""}),
                "output_json_path": ("STRING", {"default": ""}),
                "voice_id": ("STRING", {"default": ""}),
                "lipsync_model": (["lipsync-2", "lipsync-1.9.0-beta"],),
                "sync_mode": (["loop", "bounce", "cut_off", "silence", "remap"], {"default": "bounce"}),
                "segment_start": ("FLOAT", {"default": -1}),
                "segment_end": ("FLOAT", {"default": -1}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_path",)
    FUNCTION = "translate_video"
    CATEGORY = "Sync.so"
    OUTPUT_NODE = True

    def translate_video(self, babelfish_args,
                        source_language="", output_json_path="",
                        voice_id="", lipsync_model="lipsync-2",
                        sync_mode="bounce", segment_start=-1, segment_end=-1):

        args = babelfish_args
        args.source_language = source_language
        args.output_json_path = output_json_path
        args.voice_id = voice_id
        args.lipsync_model = lipsync_model
        args.sync_mode = sync_mode
        args.segment_start = segment_start
        args.segment_end = segment_end

        args.tmp_dir.mkdir(parents=True, exist_ok=True)

        local_vid = Path(self._download(args.video_url, args.tmp_dir))
        extracted_wav = self._extract_audio(local_vid)
        generated_audio_mp3, translated_text = self._tts(args, extracted_wav.name)

        aud_url = self._upload_to_uguu(generated_audio_mp3)
        if not aud_url:
            return {"ui": {"texts": []}, "result": ("Generated speech upload failed",)}

        client = Sync(api_key=args.sync_api_key).generations
        try:
            res = client.create(
                input=[Video(url=args.video_url, segments_secs=[[args.segment_start, args.segment_end]]),
                       Audio(url=aud_url)],
                model=args.lipsync_model,
                options=GenerationOptions(sync_mode=args.sync_mode),
            )
        except ApiError as e:
            return {"ui": {"texts": []}, "result": (f"Sync error – {e.status_code}: {e.body}",)}

        job_id = res.id
        status = None
        while status not in ["COMPLETED", "FAILED"]:
            time.sleep(args.poll_interval)
            status = client.get(job_id).status

        if status != "COMPLETED":
            return {"ui": {"texts": []}, "result": (f"Lipsync job {job_id} failed: {status}",)}

        output_url = client.get(job_id).output_url

        # Save MP4 next to JSON if specified
        if args.output_json_path:
            json_dir = Path(args.output_json_path).parent
            json_dir.mkdir(parents=True, exist_ok=True)
            outfile = json_dir / f"translated_{uuid.uuid4().hex[:8]}.mp4"
        else:
            outfile = args.tmp_dir / f"translated_{uuid.uuid4().hex[:8]}.mp4"

        self._download(output_url, args.tmp_dir, outfile)

        if args.output_json_path:
            metadata = {
                "input_video_url": args.video_url,
                "translated_text": translated_text,
                "target_language": args.target_language,
                "source_language": args.source_language,
                "output_video_path": str(outfile),
                "voice_id": args.voice_id,
                "lipsync_model": args.lipsync_model,
                "sync_mode": args.sync_mode,
                "job_id": job_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
            with open(args.output_json_path, "w") as f:
                json.dump(metadata, f, indent=2)

        return {
            "ui": {
                "videos": [{
                    "filename": outfile.name,
                    "subfolder": "",
                    "type": "output"
                }]
            },
            "result": (str(outfile),)
        }

    def _download(self, url: str, dest_dir: Path, explicit_path: Optional[Path] = None) -> str:
        local_path = explicit_path or (dest_dir / Path(url).name)
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        return str(local_path)

    def _extract_audio(self, vid_path: Path) -> Path:
        clip = VideoFileClip(str(vid_path))
        wav_path = vid_path.with_suffix(".wav")
        clip.audio.write_audiofile(str(wav_path), logger=None)
        clip.close()
        return wav_path

    def _tts(self, args: BabelfishArgs, audio_file_stem: str) -> tuple[Path, str]:
        openai.api_key = args.openai_api_key
        audio_path = args.tmp_dir / audio_file_stem

        with open(audio_path, "rb") as f:
            transcription = openai.audio.transcriptions.create(
                model=args.transcription_model,
                file=f,
            ).text

        prompt = (f"Translate the following transcript to {args.target_language} "
                  f"preserving tone and emotion:\n{transcription}")
        translation = openai.chat.completions.create(
            model=args.gpt_model,
            messages=[{"role": "user", "content": prompt}],
        ).choices[0].message.content.strip()

        client = ElevenLabs(api_key=args.eleven_api_key)
        audio_bytes = client.text_to_speech.convert(
            text=translation,
            voice_id=args.voice_id or "21m00Tcm4TlvDq8ikWAM",
            model_id=args.tts_model,
            output_format="mp3_44100_128",
            optimize_streaming_latency=0,
        )

        mp3_path = args.tmp_dir / f"gen_{uuid.uuid4().hex[:6]}.mp3"
        with open(mp3_path, "wb") as f:
            for chunk in audio_bytes:
                f.write(chunk)

        return mp3_path, translation

    def _upload_to_uguu(self, file_path: Path) -> Optional[str]:
        try:
            with open(file_path, "rb") as f:
                r = requests.post("https://uguu.se/upload", files=[('files[]', f)])
            j = r.json()
            if j.get("success") and "files" in j and len(j["files"]) > 0:
                return j["files"][0]["url"]
            return None
        except Exception as e:
            print(f"Upload error: {e}")
            return None


NODE_CLASS_MAPPINGS = {
    "SyncTranslateInputNode": SyncTranslateInputNode,
    "SyncTranslateNode": SyncTranslateNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SyncTranslateInputNode": "Sync.so Translate – Input",
    "SyncTranslateNode": "Sync.so Translate – Worker",
}

print(" Sync.so translation nodes loaded.")
