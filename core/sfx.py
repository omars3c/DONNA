"""
Stark OS Procedural Sound Effects Engine for F.R.I.D.A.Y.
Generates crystal-clear 24 kHz / 44.1 kHz audio waveforms procedurally.
Zero external audio files required. Non-blocking threaded playback.
"""
import math
import sys
import threading
import numpy as np
import sounddevice as sd

SAMPLE_RATE = 24000


def _play_async(samples: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    def _worker():
        try:
            sd.play(samples, sr)
            sd.wait()
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


class StarkSFX:
    """Stark Industries Sound Effects Synthesizer."""

    @staticmethod
    def play_wake(volume: float = 0.35) -> None:
        """Crisp twin-tone Stark HUD activation ping (880Hz -> 1760Hz)."""
        sr = SAMPLE_RATE
        t1 = np.linspace(0, 0.07, int(sr * 0.07), endpoint=False)
        t2 = np.linspace(0, 0.12, int(sr * 0.12), endpoint=False)

        tone1 = np.sin(2 * np.pi * 880 * t1) * np.exp(-t1 * 35)
        tone2 = (
            0.7 * np.sin(2 * np.pi * 1760 * t2) + 0.3 * np.sin(2 * np.pi * 2640 * t2)
        ) * np.exp(-t2 * 25)

        waveform = np.concatenate([tone1, tone2]) * volume
        _play_async(waveform.astype(np.float32), sr)

    @staticmethod
    def play_startup(volume: float = 0.4) -> None:
        """Reactor power-up sound: deep resonance + rising harmonic sweep + startup chord."""
        sr = SAMPLE_RATE
        dur_sweep = 0.55
        t_sweep = np.linspace(0, dur_sweep, int(sr * dur_sweep), endpoint=False)

        # Rising reactor frequency: 60Hz -> 440Hz
        freq = 60 + 380 * (t_sweep / dur_sweep) ** 2
        reactor = np.sin(2 * np.pi * freq * t_sweep) * (1 - np.exp(-t_sweep * 10))

        # Add metallic harmonics
        harmonic = 0.3 * np.sin(2 * np.pi * freq * 2.5 * t_sweep)
        sub = 0.5 * np.sin(2 * np.pi * (freq * 0.5) * t_sweep)
        fade_out = np.clip((dur_sweep - t_sweep) / 0.1, 0, 1)
        sweep = (reactor + harmonic + sub) * fade_out

        # Final dual confirmation chime
        dur_chime = 0.25
        t_chime = np.linspace(0, dur_chime, int(sr * dur_chime), endpoint=False)
        chime = (
            0.6 * np.sin(2 * np.pi * 1046.5 * t_chime)  # C6
            + 0.5 * np.sin(2 * np.pi * 1318.5 * t_chime)  # E6
            + 0.4 * np.sin(2 * np.pi * 1567.98 * t_chime)  # G6
        ) * np.exp(-t_chime * 12)

        waveform = np.concatenate([sweep * 0.7, chime]) * volume
        _play_async(waveform.astype(np.float32), sr)

    @staticmethod
    def play_confirm(volume: float = 0.25) -> None:
        """Tactile micro-blip confirming an action or command completion."""
        sr = SAMPLE_RATE
        dur = 0.04
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        tone = (
            0.7 * np.sin(2 * np.pi * 2200 * t) + 0.3 * np.sin(2 * np.pi * 3300 * t)
        ) * np.exp(-t * 80)
        waveform = tone * volume
        _play_async(waveform.astype(np.float32), sr)

    @staticmethod
    def play_scan(volume: float = 0.3) -> None:
        """Tactical HUD scanner sweep (used for camera / screen analysis)."""
        sr = SAMPLE_RATE
        dur = 0.35
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)

        # FM synthesizer sweep
        mod = 120 * np.sin(2 * np.pi * 25 * t)
        carrier_freq = 1200 + 800 * np.sin(np.pi * t / dur) + mod
        tone = np.sin(2 * np.pi * carrier_freq * t) * np.sin(np.pi * t / dur) ** 0.5
        waveform = tone * volume
        _play_async(waveform.astype(np.float32), sr)

    @staticmethod
    def play_alert(volume: float = 0.35) -> None:
        """Stark OS tactical amber warning tone."""
        sr = SAMPLE_RATE
        dur = 0.18
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        beep1 = (
            0.7 * np.sin(2 * np.pi * 750 * t) + 0.4 * np.sin(2 * np.pi * 1500 * t)
        ) * np.exp(-t * 20)
        gap = np.zeros(int(sr * 0.05))
        beep2 = (
            0.7 * np.sin(2 * np.pi * 750 * t) + 0.4 * np.sin(2 * np.pi * 1500 * t)
        ) * np.exp(-t * 20)
        waveform = np.concatenate([beep1, gap, beep2]) * volume
        _play_async(waveform.astype(np.float32), sr)


sfx = StarkSFX()
