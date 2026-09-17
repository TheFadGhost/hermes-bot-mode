"""Bounded audio decoding. Actual decoded duration, not client metadata."""
import io
import shutil
import subprocess
import wave
from .errors import APIError


def prepare_dictation(audio: bytes) -> bytes:
    if not audio or len(audio)>10*1024*1024:
        raise APIError(413,'audio_size','Voice notes must be smaller than 10 MB.')
    executable=shutil.which('ffmpeg')
    if not executable:
        raise APIError(503,'audio_decoder_missing','Dictation needs the audio decoder installed by the administrator.')
    try:
        # No network/file protocols; fixed output rate bounds decoded memory.
        result=subprocess.run([executable,'-nostdin','-hide_banner','-loglevel','error',
            '-protocol_whitelist','pipe','-i','pipe:0','-vn','-ac','1','-ar','16000',
            '-t','121','-f','wav','pipe:1'],input=audio,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            timeout=20,check=False)
        if result.returncode or not result.stdout:
            raise ValueError('invalid audio')
        with wave.open(io.BytesIO(result.stdout),'rb') as source:
            pcm=source.readframes(121*16000+1)
        seconds=len(pcm)/32000
        if seconds>120:
            raise APIError(413,'audio_duration','Voice notes are limited to two minutes. Record a shorter note.')
        if seconds<0.1:
            raise ValueError('audio too short')
        output=io.BytesIO()
        with wave.open(output,'wb') as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(16000)
            target.writeframes(pcm)
        return output.getvalue()
    except (subprocess.TimeoutExpired,OSError,ValueError,wave.Error,EOFError):
        raise APIError(422,'audio_invalid','This recording could not be read. Try recording it again.') from None

