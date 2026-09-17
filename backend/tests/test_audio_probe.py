import io
import shutil
import wave
import pytest
from app.audio_probe import prepare_dictation
from app.errors import APIError


def wav(seconds):
    out=io.BytesIO()
    with wave.open(out,'wb') as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(16000)
        writer.writeframes(b'\0\0'*int(seconds*16000))
    return out.getvalue()


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='ffmpeg required')
def test_audio_decoded_bounds_and_invalid_input():
    result=prepare_dictation(wav(0.5))
    with wave.open(io.BytesIO(result),'rb') as reader:
        assert reader.getframerate()==16000
        assert reader.getnframes()==8000
    with pytest.raises(APIError) as error:
        prepare_dictation(wav(122))
    assert error.value.code=='audio_duration'
    with pytest.raises(APIError):
        prepare_dictation(b'not a recording, do not forward this')


def test_audio_decoder_missing_fails_without_upload(monkeypatch):
    monkeypatch.setattr('app.audio_probe.shutil.which',lambda _:None)
    with pytest.raises(APIError) as error: prepare_dictation(wav(1))
    assert error.value.code=='audio_decoder_missing'

