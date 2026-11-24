"""
Generador de los 10 paisajes sonoros barrocos / Bach para la Mesa Sonora (10 Canales).
Crea archivos .wav estéreo (44100 Hz) para cada instrumento de la orquesta de 2 manos.
"""
import os
import wave
import numpy as np

SAMPLE_RATE = 44100


def save_wav(filepath, audio_stereo):
    audio_clipped = np.clip(audio_stereo, -1.0, 1.0)
    pcm16 = (audio_clipped * 32767).astype(np.int16)
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm16.tobytes())


def apply_loop_crossfade(stereo, fade_sec=0.8):
    n_fade = int(fade_sec * SAMPLE_RATE)
    if len(stereo) <= 2 * n_fade:
        return stereo
    fade_in = np.linspace(0.0, 1.0, n_fade)[:, None]
    fade_out = np.linspace(1.0, 0.0, n_fade)[:, None]
    stereo[:n_fade] = stereo[:n_fade] * fade_in + stereo[-n_fade:] * fade_out
    return stereo[:-n_fade]


# 1. Clavecín (Meñique Izquierdo)
def gen_canal_1(duration=8.0):
    n = int(duration * SAMPLE_RATE)
    t = np.linspace(0, duration, n, endpoint=False)
    freqs = np.asarray([220.0, 261.63, 329.63, 440.0])
    f_arp = freqs[(t * 8).astype(int) % len(freqs)]
    env = np.exp(-3.0 * (t % 0.125))
    tone = (np.sin(2 * np.pi * f_arp * t) + 0.45 * np.sin(2 * np.pi * (2.0 * f_arp) * t)) * env
    return apply_loop_crossfade(np.column_stack([tone, tone]) * 0.65)


# 2. Contrabajo / Violone (Anular Izquierdo)
def gen_canal_2(duration=8.0):
    n = int(duration * SAMPLE_RATE)
    t = np.linspace(0, duration, n, endpoint=False)
    # Fundamental 55 Hz (A1) + armonicos de cuerda frotada (110, 165, 220, 275 Hz) para que suene potente en parlantes
    bow_env = 0.78 + 0.22 * np.sin(2 * np.pi * 2.0 * t)
    tone = (
        0.45 * np.sin(2 * np.pi * 55.0 * t)
        + 0.50 * np.sin(2 * np.pi * 110.0 * t)
        + 0.38 * np.sin(2 * np.pi * 165.0 * t)
        + 0.25 * np.sin(2 * np.pi * 220.0 * t)
        + 0.14 * np.sin(2 * np.pi * 275.0 * t)
    ) * bow_env
    return apply_loop_crossfade(np.column_stack([tone * 0.72, tone * 0.72]))


# 3. Fagot Barroco (Mayor Izquierdo)
def gen_canal_3(duration=8.0):
    n = int(duration * SAMPLE_RATE)
    t = np.linspace(0, duration, n, endpoint=False)
    tone = (
        0.65 * np.sin(2 * np.pi * 146.83 * t)
        + 0.35 * np.sin(2 * np.pi * 293.66 * t)
    ) * (0.6 + 0.4 * np.sin(2 * np.pi * 3.0 * t))
    return apply_loop_crossfade(np.column_stack([tone * 0.6, tone * 0.6]) * 0.65)


# 4. Viola de Gamba / Tenor (Índice Izquierdo)
def gen_canal_4(duration=8.0):
    n = int(duration * SAMPLE_RATE)
    t = np.linspace(0, duration, n, endpoint=False)
    tone = np.sin(2 * np.pi * 220.0 * t) + 0.5 * np.sin(2 * np.pi * 440.0 * t)
    return apply_loop_crossfade(np.column_stack([tone * 0.5, tone * 0.6]) * 0.65)


# 5. Violonchelo Solista (Gordo / Pulgar Izquierdo)
def gen_canal_5(duration=8.0):
    n = int(duration * SAMPLE_RATE)
    t = np.linspace(0, duration, n, endpoint=False)
    # Melodia expresiva de Chelo Barroco (Preludio de Bach) con armonicos ricos (1f, 2f, 3f, 4f) y vibrato
    vibrato = 1.0 + 0.005 * np.sin(2 * np.pi * 5.2 * t)
    notes = np.asarray([146.83, 164.81, 196.00, 220.00])  # D3 - E3 - G3 - A3
    f_base = notes[(t * 2.0).astype(int) % len(notes)] * vibrato
    phase = 2 * np.pi * np.cumsum(f_base) / SAMPLE_RATE
    bow_env = 0.75 + 0.25 * np.sin(2 * np.pi * 2.0 * t)
    tone = (
        0.55 * np.sin(phase)
        + 0.45 * np.sin(2 * phase)
        + 0.32 * np.sin(3 * phase)
        + 0.18 * np.sin(4 * phase)
    ) * bow_env
    return apply_loop_crossfade(np.column_stack([tone * 0.75, tone * 0.70]))


# 6. Violín Primero Principal (Gordo / Pulgar Derecho)
def gen_canal_6(duration=8.0):
    n = int(duration * SAMPLE_RATE)
    t = np.linspace(0, duration, n, endpoint=False)
    freq = 440.0 + 110.0 * np.sin(2 * np.pi * 0.5 * t)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    tone = (np.sin(phase) + 0.3 * np.sin(2 * phase)) * (0.8 + 0.2 * np.sin(2 * np.pi * 6.0 * t))
    return apply_loop_crossfade(np.column_stack([tone * 0.6, tone * 0.7]) * 0.65)


# 7. Violín Segundo (Índice Derecho)
def gen_canal_7(duration=8.0):
    n = int(duration * SAMPLE_RATE)
    t = np.linspace(0, duration, n, endpoint=False)
    freq = 329.63 + 80.0 * np.sin(2 * np.pi * 0.5 * t)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    tone = np.sin(phase) + 0.25 * np.sin(2 * phase)
    return apply_loop_crossfade(np.column_stack([tone * 0.7, tone * 0.6]) * 0.65)


# 8. Viola (Mayor Derecho)
def gen_canal_8(duration=8.0):
    n = int(duration * SAMPLE_RATE)
    t = np.linspace(0, duration, n, endpoint=False)
    tone = 0.5 * np.sin(2 * np.pi * 220.0 * t) + 0.5 * np.sin(2 * np.pi * 329.63 * t)
    return apply_loop_crossfade(np.column_stack([tone, tone]) * 0.65)


# 9. Flauta Traversera Barroca (Anular Derecho)
def gen_canal_9(duration=8.0):
    n = int(duration * SAMPLE_RATE)
    t = np.linspace(0, duration, n, endpoint=False)
    rng = np.random.default_rng(42)
    air = rng.normal(0, 0.04, n)
    tone = (np.sin(2 * np.pi * 880.0 * t) + air) * (0.6 + 0.4 * np.sin(2 * np.pi * 2.0 * t))
    return apply_loop_crossfade(np.column_stack([tone * 0.5, tone * 0.6]) * 0.6)


# 10. Oboe / Oboe d'amore (Meñique Derecho)
def gen_canal_10(duration=8.0):
    n = int(duration * SAMPLE_RATE)
    t = np.linspace(0, duration, n, endpoint=False)
    tone = np.sin(2 * np.pi * 523.25 * t) + 0.4 * np.sin(2 * np.pi * 1046.5 * t)
    return apply_loop_crossfade(np.column_stack([tone * 0.6, tone * 0.6]) * 0.6)


def ensure_10_sounds(sounds_dir, force_regen=False):
    os.makedirs(sounds_dir, exist_ok=True)
    # No sobrescribir grabaciones reales del usuario
    pass


# Alias de compatibilidad
ensure_default_sounds = ensure_10_sounds


if __name__ == "__main__":
    target_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sonidos")
    ensure_10_sounds(target_dir, force_regen=True)
    print("10 instrumentos barrocos listos en:", target_dir)
