import asyncio
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path

VENDOR_DIR = Path(__file__).parent / "vendor" / "wav2lip"
CHECKPOINT_PATH = VENDOR_DIR / "checkpoints" / "wav2lip_gan.pth"


class LipSyncEngine(ABC):
    @abstractmethod
    async def sync(self, face_path: Path, audio_path: Path, out_path: Path) -> Path:
        """Given a face image or silent face video plus an audio clip, produce
        a lip-synced video at out_path, same resolution as face_path."""
        ...


class Wav2LipEngine(LipSyncEngine):
    """Local, offline lip-sync via the vendored Wav2Lip inference script.

    Swappable later for a commercial API (D-ID/HeyGen) by adding another
    LipSyncEngine implementation — callers only depend on this interface,
    same pattern as TTSEngine/EdgeTTSEngine.
    """

    async def sync(self, face_path: Path, audio_path: Path, out_path: Path) -> Path:
        await asyncio.to_thread(self._run, face_path, audio_path, out_path)
        return out_path

    def _run(self, face_path: Path, audio_path: Path, out_path: Path) -> None:
        # inference.py parses argv at import time and does its own relative
        # path I/O, so it has to run as a subprocess rooted at the vendor dir.
        cmd = [
            sys.executable,
            "inference.py",
            "--checkpoint_path", str(CHECKPOINT_PATH),
            "--face", str(face_path.resolve()),
            "--audio", str(audio_path.resolve()),
            "--outfile", str(out_path.resolve()),
        ]
        print(f"[Wav2Lip] 启动推理: {audio_path.name} → {out_path.name}", flush=True)
        process = subprocess.Popen(
            cmd,
            cwd=VENDOR_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        output_tail = []
        assert process.stdout is not None
        for line in process.stdout:
            message = line.rstrip()
            if message:
                print(f"[Wav2Lip] {message}", flush=True)
                output_tail.append(message)
                output_tail = output_tail[-80:]

        returncode = process.wait()
        if returncode != 0:
            raise RuntimeError(
                f"Wav2Lip inference failed (exit {returncode}):\n"
                + "\n".join(output_tail)[-4000:]
            )
        print(f"[Wav2Lip] 推理完成: {out_path.name}", flush=True)
