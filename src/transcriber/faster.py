from src.transcriber.base import BaseTranscriber
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class FasterWhisperTranscriber(BaseTranscriber):
    """Transcriber using faster-whisper (CTranslate2) for Linux/CUDA."""

    def __init__(
        self,
        model_size: str = "large-v3",
        device: str = "auto",
        compute_type: str = "float16",
        vad_filter: bool = True,
        vad_min_silence_ms: int = 500,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.vad_filter = vad_filter
        self.vad_min_silence_ms = vad_min_silence_ms
        self._model = None

    def _get_model(self):
        """Lazy-load the Whisper model."""
        if self._model is None:
            from faster_whisper import WhisperModel

            logger.info(
                f"Loading faster-whisper model: {self.model_size} "
                f"(device={self.device}, compute_type={self.compute_type})"
            )
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def transcribe(
        self, video_path: str, language: str = "zh", task: str = "transcribe"
    ) -> list[dict]:
        """Transcribe using faster-whisper.

        Args:
            video_path: Path to video file.
            language: Source language code.
            task: 'transcribe' or 'translate'.

        Returns:
            List of segment dicts with 'start', 'end', 'text'.
        """
        model = self._get_model()

        vad_parameters = None
        if self.vad_filter:
            vad_parameters = dict(min_silence_duration_ms=self.vad_min_silence_ms)

        logger.info(f"Transcribing {video_path} (language={language}, task={task})")
        segments_gen, info = model.transcribe(
            video_path,
            language=language,
            task=task,
            vad_filter=self.vad_filter,
            vad_parameters=vad_parameters,
        )

        segments = []
        for seg in segments_gen:
            segments.append(
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                }
            )

        logger.info(
            f"Transcription complete: {len(segments)} segments, "
            f"detected language: {info.language} ({info.language_probability:.2%})"
        )
        return segments
