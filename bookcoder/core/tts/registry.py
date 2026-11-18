from __future__ import annotations

from typing import Optional

from .base import TTSProvider


class TTSRegistry:
    """Registry for available TTS providers. Designed for easy extension/replacement."""

    def __init__(self) -> None:
        self._providers: dict[str, TTSProvider] = {}
        self.piper_manager = None
        self.coqui_manager = None
        self.mms_manager = None
        self._register_defaults()

    def _register_defaults(self) -> None:
        # Register built-in providers.
        # Edge TTS: high-quality online neural voices.
        try:
            from .edge_tts_provider import EdgeTTSProvider

            self.register(EdgeTTSProvider())
        except Exception:
            pass

        # Piper: offline neural voices (models downloaded on demand).
        try:
            from .piper_manager import PiperModelManager
            from .piper_provider import PiperTTSProvider

            self.piper_manager = PiperModelManager()
            self.register(PiperTTSProvider(manager=self.piper_manager))
        except Exception:
            pass

        # Coqui XTTS v2: heavy multilingual neural TTS (optional deps).
        try:
            from .coqui_manager import CoquiModelManager
            from .coqui_tts_provider import CoquiXTTSProvider

            self.coqui_manager = CoquiModelManager()
            self.register(CoquiXTTSProvider(manager=self.coqui_manager))
        except Exception:
            pass

        # Meta MMS-TTS: heavy offline neural TTS via transformers/torch (optional deps).
        try:
            from .mms_manager import MMSModelManager
            from .mms_tts_provider import MMSTTSProvider

            self.mms_manager = MMSModelManager()
            self.register(MMSTTSProvider(manager=self.mms_manager))
        except Exception:
            pass

    def register(self, provider: TTSProvider) -> None:
        self._providers[provider.id] = provider

    def get(self, provider_id: str) -> Optional[TTSProvider]:
        if not provider_id:
            return None
        return self._providers.get(provider_id)

    def providers(self) -> list[TTSProvider]:
        return list(self._providers.values())

    def available_providers(self) -> list[TTSProvider]:
        result = []
        for p in self._providers.values():
            ok, _ = p.is_available()
            if ok:
                result.append(p)
        return result

    def resolve_provider(self, provider_id: str = "", language=None) -> Optional[TTSProvider]:
        """Resolve provider by explicit id, else pick best available for use.

        Preference: explicitly requested (if usable) -> edge-tts if runtime available
        -> piper if runtime available and has downloaded voices for language (or any)
        -> any available provider -> first registered.
        """
        # Explicit request
        if provider_id:
            p = self.get(provider_id)
            if p:
                ok, _ = p.is_available()
                if ok:
                    return p
                # if requested but not available, fall through to best effort

        edge = self.get("edge-tts")
        piper = self.get("piper")

        # Prefer Edge when available (online, broad voice selection)
        if edge:
            ok, _ = edge.is_available()
            if ok:
                return edge

        # Fallback to Piper if it has downloaded voices
        if piper:
            ok, _ = piper.is_available()
            if ok:
                try:
                    voices = piper.list_voices(language) if language is not None else piper.list_voices(None)
                    if voices:
                        return piper
                except Exception:
                    pass
                # Piper runtime installed but no voices downloaded yet - still return it
                # so UI can show download options
                return piper

        avail = self.available_providers()
        if avail:
            return avail[0]
        return next(iter(self._providers.values()), None)

    def default_provider(self) -> Optional[TTSProvider]:
        return self.resolve_provider("")
