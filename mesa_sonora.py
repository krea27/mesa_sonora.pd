"""
MESA SONORA - Controlador Gestual de 2 Estados + Mixer Vol/Pan + Sliders DSP -> PlugData
========================================================================================
Estados de interaccion por mano:
  - Estado 1 (Mano Abierta)  : sonidos/paisaje-de-aves.wav
  - Estado 2 (Puno Cerrado)  : sonidos/paisaje-de-sapos.wav
  - Fondo Constante          : sonidos/paisaje-de-mar.wav (Fade-In al interactuar,
                               10s de cola y Fade-Out al salir; [M] manual)

Controles en Pantalla de Trackeo (Ventana 1):
  - Panel Izquierdo (MIXER): Sliders de VOLUMEN (0%-200%) y PANEO (L-C-R) para Aves, Sapos y Mar.
  - Panel Derecho (EFECTOS DSP): Sliders muy marcados de LOW-PASS, WAH RESONANTE y DELAY/ECO.
  - Arrastrar con clic izquierdo | Clic derecho en un slider para resetear | [R]: Reset total.
  - [F]/[W]/[E]: Alternar control por MANO vs SLIDER para Low-Pass, Wah y Delay.
"""

import argparse
import gc
import math
import os
import socket
import subprocess
import sys
import threading
import time

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

WINDOW_NAME = "Mesa Sonora - Trackeo + Mixer + Filtros DSP -> PlugData"
VISUAL_WINDOW_NAME = "Mesa Sonora - Proyeccion Generativa Liquida"

STATES = [
    {
        "slot": 1,
        "key": "aves",
        "gesture_name": "Mano Abierta",
        "sound_title": "Paisaje de Aves",
        "filename": "paisaje-de-aves.wav",
        "color": (50, 210, 255),     # Dorado sol (BGR)
        "ripple_freq": 15.0,
    },
    {
        "slot": 2,
        "key": "sapos",
        "gesture_name": "Puno Cerrado",
        "sound_title": "Paisaje de Sapos",
        "filename": "paisaje-de-sapos.wav",
        "color": (80, 220, 110),     # Verde nocturno (BGR)
        "ripple_freq": 7.5,
    },
]

MAR_COLOR = (240, 190, 60)  # Cyan oceanico (BGR)

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
]
FINGER_TIPS = [4, 8, 12, 16, 20]


def format_pan_label(pan_val):
    """Formatea un valor de paneo 0.0..1.0 como texto legible (L100% .. C .. R100%)."""
    offset = (pan_val - 0.5) * 2.0
    if abs(offset) < 0.04:
        return "C"
    pct = int(round(abs(offset) * 100))
    return f"L{pct}%" if offset < 0 else f"R{pct}%"


def format_hz_label(hz):
    """Formatea frecuencia en Hz o kHz de forma compacta."""
    if hz >= 1000.0:
        return f"{hz / 1000.0:.1f}k"
    return f"{int(round(hz))}Hz"


def log_ratio_to_hz(ratio, f_min, f_max):
    r = float(np.clip(ratio, 0.0, 1.0))
    return float(f_min * ((f_max / f_min) ** r))


def hz_to_log_ratio(hz, f_min, f_max):
    clamped = float(np.clip(hz, f_min, f_max))
    return float(math.log(clamped / f_min) / math.log(f_max / f_min))


class SoundscapeMixer:
    """
    Mezclador interactivo (Panel Izquierdo) para controlar Volumen (0%-200%)
    y Paneo (L-C-R) individualmente para Aves, Sapos y Mar.
    """

    TRACK_SPECS = [
        {
            "key": "aves",
            "title": "[1] Mano Abierta: Aves",
            "color": (50, 210, 255),
            "default_vol": 1.35,
            "default_pan": 0.50,
        },
        {
            "key": "sapos",
            "title": "[2] Puno Cerrado: Sapos",
            "color": (80, 220, 110),
            "default_vol": 1.60,
            "default_pan": 0.50,
        },
        {
            "key": "mar",
            "title": "[FONDO] Paisaje de Mar",
            "color": MAR_COLOR,
            "default_vol": 0.35,
            "default_pan": 0.50,
        },
    ]

    VOL_MIN = 0.0
    VOL_MAX = 2.0

    def __init__(self, panel_x=12, panel_y=82, panel_w=386):
        self.panel_x = panel_x
        self.panel_y = panel_y
        self.panel_w = panel_w

        self.values = {}
        self.defaults = {}
        for spec in self.TRACK_SPECS:
            k = spec["key"]
            self.values[k] = {"vol": spec["default_vol"], "pan": spec["default_pan"]}
            self.defaults[k] = {"vol": spec["default_vol"], "pan": spec["default_pan"]}

        self.slider_rects = {}
        self.dragging = None
        self.dirty = True
        self._build_layout()

    def _build_layout(self):
        bar_x1 = self.panel_x + 56
        bar_x2 = self.panel_x + self.panel_w - 68
        card_h = 122
        card_gap = 10
        start_y = self.panel_y + 34

        self.card_boxes = {}
        for idx, spec in enumerate(self.TRACK_SPECS):
            k = spec["key"]
            cy0 = start_y + idx * (card_h + card_gap)
            cy1 = cy0 + card_h
            self.card_boxes[k] = (self.panel_x + 10, cy0, self.panel_x + self.panel_w - 10, cy1)
            self.slider_rects[(k, "vol")] = (bar_x1, cy0 + 62, bar_x2)
            self.slider_rects[(k, "pan")] = (bar_x1, cy0 + 98, bar_x2)

        self.panel_h = 34 + len(self.TRACK_SPECS) * (card_h + card_gap) + 8

    def reset_all(self):
        for k, d in self.defaults.items():
            self.values[k]["vol"] = d["vol"]
            self.values[k]["pan"] = d["pan"]
        self.dirty = True

    def _hit_test(self, x, y):
        for key_param, (x1, yc, x2) in self.slider_rects.items():
            if (x1 - 10) <= x <= (x2 + 10) and abs(y - yc) <= 13:
                return key_param
        return None

    def _set_from_x(self, key_param, x):
        track_key, param = key_param
        x1, _, x2 = self.slider_rects[key_param]
        ratio = float(np.clip((x - x1) / max(1.0, float(x2 - x1)), 0.0, 1.0))

        if param == "vol":
            val = self.VOL_MIN + ratio * (self.VOL_MAX - self.VOL_MIN)
            if abs(val - 1.0) < 0.025:
                val = 1.0
            self.values[track_key]["vol"] = round(val, 3)
        else:
            if abs(ratio - 0.5) < 0.025:
                ratio = 0.5
            self.values[track_key]["pan"] = round(ratio, 3)

        self.dirty = True

    def on_mouse(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            hit = self._hit_test(x, y)
            if hit is not None:
                self.dragging = hit
                self._set_from_x(hit, x)
                return True
        elif event == cv2.EVENT_MOUSEMOVE:
            if self.dragging is not None:
                self._set_from_x(self.dragging, x)
                return True
        elif event == cv2.EVENT_LBUTTONUP:
            if self.dragging is not None:
                k, p = self.dragging
                val = self.values[k][p]
                if p == "vol":
                    print(f"[MIXER] {k.upper()} Volumen -> {int(round(val * 100))}%")
                else:
                    print(f"[MIXER] {k.upper()} Paneo -> {format_pan_label(val)} ({val:.2f})")
                self.dragging = None
                return True
        elif event == cv2.EVENT_RBUTTONDOWN:
            hit = self._hit_test(x, y)
            if hit is not None:
                k, p = hit
                self.values[k][p] = self.defaults[k][p]
                self.dirty = True
                print(f"[MIXER] {k.upper()} {p.upper()} reseteado.")
                return True
        return False

    def send_udp(self, sock, target):
        for spec in self.TRACK_SPECS:
            k = spec["key"]
            udp_send_safe(sock, target, f"vol_{k} {self.values[k]['vol']:.3f};\n")
            udp_send_safe(sock, target, f"pan_{k} {self.values[k]['pan']:.3f};\n")
        self.dirty = False

    def draw(self, image, active_map, mar_status_label):
        px, py, pw, ph = self.panel_x, self.panel_y, self.panel_w, self.panel_h
        darken_rect_inplace(image, px, py, px + pw, py + ph, (18, 18, 24), 0.24)
        cv2.rectangle(image, (px, py), (px + pw, py + ph), (70, 75, 90), 1)

        cv2.putText(
            image,
            "MEZCLADOR EN VIVO (VOL / PAN)",
            (px + 12, py + 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (235, 235, 245),
            1,
        )
        cv2.putText(
            image,
            "[R] Reset",
            (px + pw - 80, py + 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (175, 185, 200),
            1,
        )

        for spec in self.TRACK_SPECS:
            k = spec["key"]
            col = spec["color"]
            is_on = active_map.get(k, False)
            x0, y0, x1, y1 = self.card_boxes[k]

            border_col = col if is_on else (75, 78, 90)
            cv2.rectangle(image, (x0, y0), (x1, y1), border_col, 2 if is_on else 1)

            header_h = 30
            if is_on:
                cv2.rectangle(image, (x0, y0), (x1, y0 + header_h), col, -1)
                title_col = (15, 15, 18)
                badge_col = (20, 20, 25)
            else:
                darken_rect_inplace(image, x0 + 1, y0 + 1, x1 - 1, y0 + header_h, (32, 34, 42), 0.35)
                title_col = col
                badge_col = (170, 175, 185)

            cv2.putText(
                image,
                spec["title"],
                (x0 + 8, y0 + 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.43,
                title_col,
                2 if is_on else 1,
            )

            badge_txt = mar_status_label if k == "mar" else ("SONANDO" if is_on else "ESPERA")
            cv2.putText(
                image,
                badge_txt,
                (x1 - 92, y0 + 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.37,
                badge_col,
                2 if is_on else 1,
            )

            # VOL slider (0% - 200%)
            vol_val = self.values[k]["vol"]
            vx1, vyc, vx2 = self.slider_rects[(k, "vol")]
            vol_ratio = float(np.clip((vol_val - self.VOL_MIN) / (self.VOL_MAX - self.VOL_MIN), 0.0, 1.0))
            v_handle_x = int(vx1 + vol_ratio * (vx2 - vx1))
            is_drag_vol = self.dragging == (k, "vol")

            cv2.putText(image, "VOL", (x0 + 8, vyc + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.37, (205, 210, 220), 1)
            cv2.rectangle(image, (vx1, vyc - 4), (vx2, vyc + 4), (55, 58, 68), -1)
            if v_handle_x > vx1:
                cv2.rectangle(image, (vx1, vyc - 4), (v_handle_x, vyc + 4), col, -1)
            mid_v = (vx1 + vx2) // 2
            cv2.line(image, (mid_v, vyc - 8), (mid_v, vyc + 8), (150, 155, 165), 1)
            r_v = 9 if is_drag_vol else 7
            cv2.circle(image, (v_handle_x, vyc), r_v, (255, 255, 255) if is_drag_vol else col, -1)
            cv2.circle(image, (v_handle_x, vyc), r_v, (255, 255, 255), 1)
            cv2.putText(
                image,
                f"{int(round(vol_val * 100)):3d}%",
                (vx2 + 10, vyc + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.41,
                (255, 255, 255) if is_drag_vol else col,
                2 if is_drag_vol else 1,
            )

            # PAN slider (L - C - R)
            pan_val = self.values[k]["pan"]
            px1, pyc, px2 = self.slider_rects[(k, "pan")]
            p_mid = (px1 + px2) // 2
            p_handle_x = int(px1 + pan_val * (px2 - px1))
            is_drag_pan = self.dragging == (k, "pan")

            cv2.putText(image, "PAN", (x0 + 8, pyc + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.37, (205, 210, 220), 1)
            cv2.rectangle(image, (px1, pyc - 4), (px2, pyc + 4), (55, 58, 68), -1)
            fill_a, fill_b = min(p_mid, p_handle_x), max(p_mid, p_handle_x)
            if fill_b > fill_a:
                cv2.rectangle(image, (fill_a, pyc - 4), (fill_b, pyc + 4), col, -1)
            cv2.line(image, (p_mid, pyc - 8), (p_mid, pyc + 8), (185, 190, 200), 1)
            cv2.putText(image, "L", (px1 - 2, pyc + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (150, 155, 165), 1)
            cv2.putText(image, "C", (p_mid - 3, pyc + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (150, 155, 165), 1)
            cv2.putText(image, "R", (px2 - 6, pyc + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (150, 155, 165), 1)
            r_p = 9 if is_drag_pan else 7
            cv2.circle(image, (p_handle_x, pyc), r_p, (255, 255, 255) if is_drag_pan else col, -1)
            cv2.circle(image, (p_handle_x, pyc), r_p, (255, 255, 255), 1)
            cv2.putText(
                image,
                format_pan_label(pan_val),
                (px2 + 10, pyc + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.41,
                (255, 255, 255) if is_drag_pan else col,
                2 if is_drag_pan else 1,
            )


class EffectsPanel:
    """
    Panel interactivo de Filtros y Efectos DSP (Panel Derecho) con rangos bien marcados:
      - LOW-PASS (Corte de agudos 120 Hz - 15 kHz, doble polo -12 dB/oct)
      - WAH RESONANTE (Mix 0%-100% + Frecuencia 180 Hz - 3.8 kHz, Q=9.0)
      - DELAY / ECO PING-PONG (Nivel 0%-100% + Repeticiones 0%-88%)
    """

    LP_MIN = 120.0
    LP_MAX = 15000.0
    WAH_FMIN = 180.0
    WAH_FMAX = 3800.0
    DELAY_FB_MAX = 0.88

    CARD_SPECS = [
        {
            "fx": "lp",
            "title": "LOW-PASS [F] (Agudos)",
            "color": (255, 190, 90),     # Celeste claro (BGR)
            "sliders": [
                {"id": "lp_cutoff", "label": "CORTE", "left_tag": "Grave", "right_tag": "Abierto"},
            ],
        },
        {
            "fx": "wah",
            "title": "WAH RESONANTE [W]",
            "color": (235, 110, 255),    # Magenta brillante (BGR)
            "sliders": [
                {"id": "wah_mix", "label": "MIX", "left_tag": "OFF", "right_tag": "Fuerte"},
                {"id": "wah_freq", "label": "FREQ", "left_tag": "Ooo", "right_tag": "Iii"},
            ],
        },
        {
            "fx": "delay",
            "title": "DELAY / ECO [E]",
            "color": (80, 165, 255),     # Naranja calido (BGR)
            "sliders": [
                {"id": "delay_wet", "label": "NIVEL", "left_tag": "OFF", "right_tag": "Lleno"},
                {"id": "delay_fb", "label": "REPET", "left_tag": "Corto", "right_tag": "Largo"},
            ],
        },
    ]

    DEFAULTS = {
        "lp_cutoff": 15000.0,   # Abierto / transparente
        "wah_mix": 0.0,         # OFF
        "wah_freq": 900.0,      # Frecuencia media lista para barrer
        "delay_wet": 0.0,       # OFF
        "delay_fb": 0.72,       # Repeticiones bien marcadas al subir Nivel
    }

    def __init__(self, panel_x=882, panel_y=82, panel_w=386):
        self.panel_x = panel_x
        self.panel_y = panel_y
        self.panel_w = panel_w

        self.values = dict(self.DEFAULTS)
        self.hand_mode = {"lp": False, "wah": False, "delay": False}
        self.slider_rects = {}  # slider_id -> (x1, y_center, x2, fx_group)
        self.card_boxes = {}
        self.dragging = None
        self.dirty = True
        self._build_layout()

    def _build_layout(self):
        bar_x1 = self.panel_x + 64
        bar_x2 = self.panel_x + self.panel_w - 68
        card_gap = 10
        cur_y = self.panel_y + 34

        for spec in self.CARD_SPECS:
            fx = spec["fx"]
            n_sl = len(spec["sliders"])
            card_h = 84 if n_sl == 1 else 132
            cy0 = cur_y
            cy1 = cy0 + card_h
            self.card_boxes[fx] = (self.panel_x + 10, cy0, self.panel_x + self.panel_w - 10, cy1)

            for i, sl in enumerate(spec["sliders"]):
                yc = cy0 + 56 + i * 48
                self.slider_rects[sl["id"]] = (bar_x1, yc, bar_x2, fx)

            cur_y = cy1 + card_gap

        self.panel_h = (cur_y - self.panel_y)

    def reset_all(self):
        self.values = dict(self.DEFAULTS)
        self.hand_mode = {"lp": False, "wah": False, "delay": False}
        self.dirty = True

    def _value_to_ratio(self, sid, val):
        if sid == "lp_cutoff":
            return hz_to_log_ratio(val, self.LP_MIN, self.LP_MAX)
        if sid == "wah_freq":
            return hz_to_log_ratio(val, self.WAH_FMIN, self.WAH_FMAX)
        if sid == "delay_fb":
            return float(np.clip(val / self.DELAY_FB_MAX, 0.0, 1.0))
        return float(np.clip(val, 0.0, 1.0))

    def _ratio_to_value(self, sid, ratio):
        r = float(np.clip(ratio, 0.0, 1.0))
        if sid == "lp_cutoff":
            if r > 0.97:
                return self.LP_MAX
            return round(log_ratio_to_hz(r, self.LP_MIN, self.LP_MAX), 1)
        if sid == "wah_freq":
            return round(log_ratio_to_hz(r, self.WAH_FMIN, self.WAH_FMAX), 1)
        if sid == "delay_fb":
            return round(r * self.DELAY_FB_MAX, 3)
        if r < 0.025:
            return 0.0
        return round(r, 3)

    def _format_value(self, sid, val):
        if sid == "lp_cutoff":
            return "OPEN" if val >= 14500.0 else format_hz_label(val)
        if sid == "wah_freq":
            return format_hz_label(val)
        if sid in ("wah_mix", "delay_wet"):
            return "OFF" if val <= 0.01 else f"{int(round(val * 100))}%"
        if sid == "delay_fb":
            return f"{int(round(val * 100))}%"
        return f"{val:.2f}"

    def _hit_test(self, x, y):
        for sid, (x1, yc, x2, _) in self.slider_rects.items():
            if (x1 - 10) <= x <= (x2 + 10) and abs(y - yc) <= 13:
                return sid
        return None

    def _set_from_x(self, sid, x):
        x1, _, x2, fx = self.slider_rects[sid]
        ratio = float(np.clip((x - x1) / max(1.0, float(x2 - x1)), 0.0, 1.0))
        self.values[sid] = self._ratio_to_value(sid, ratio)
        # Al mover manualmente un slider, desactiva modo mano de ese efecto para que no pelee con el mouse
        self.hand_mode[fx] = False
        self.dirty = True

    def on_mouse(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            hit = self._hit_test(x, y)
            if hit is not None:
                self.dragging = hit
                self._set_from_x(hit, x)
                return True
        elif event == cv2.EVENT_MOUSEMOVE:
            if self.dragging is not None:
                self._set_from_x(self.dragging, x)
                return True
        elif event == cv2.EVENT_LBUTTONUP:
            if self.dragging is not None:
                sid = self.dragging
                print(f"[FX] {sid} -> {self._format_value(sid, self.values[sid])}")
                self.dragging = None
                return True
        elif event == cv2.EVENT_RBUTTONDOWN:
            hit = self._hit_test(x, y)
            if hit is not None:
                _, _, _, fx = self.slider_rects[hit]
                self.values[hit] = self.DEFAULTS[hit]
                self.hand_mode[fx] = False
                self.dirty = True
                print(f"[FX] {hit} reseteado -> {self._format_value(hit, self.values[hit])}")
                return True
        return False

    def apply_hand_modulation(self, hand):
        """Si algun efecto esta en modo MANO ([F]/[W]/[E]), actualiza sus sliders en vivo."""
        if not hand.active:
            return
        if self.hand_mode["lp"]:
            self.values["lp_cutoff"] = round(log_ratio_to_hz(hand.norm_x, self.LP_MIN, self.LP_MAX), 1)
        if self.hand_mode["wah"]:
            self.values["wah_mix"] = 0.85
            self.values["wah_freq"] = round(log_ratio_to_hz(1.0 - hand.norm_y, self.WAH_FMIN, self.WAH_FMAX), 1)
        if self.hand_mode["delay"]:
            self.values["delay_wet"] = round(float(np.clip(hand.metrics["depth_norm"], 0.0, 1.0)), 3)

    def send_udp(self, sock, target):
        cutoff = self.values["lp_cutoff"]
        wah_mix = self.values["wah_mix"]
        wah_freq = self.values["wah_freq"]
        # Ganancia wet del delay escalada hasta 1.25 para que el rebote sea muy notorio al 100%
        delay_wet_pd = self.values["delay_wet"] * 1.25
        delay_fb = self.values["delay_fb"]

        udp_send_safe(sock, target, f"cutoff {cutoff:.1f};\n")
        udp_send_safe(sock, target, f"wah {wah_mix:.3f} {wah_freq:.1f};\n")
        udp_send_safe(sock, target, f"delay {delay_wet_pd:.3f};\n")
        udp_send_safe(sock, target, f"delay_fb {delay_fb:.3f};\n")
        self.dirty = False

    def is_fx_active(self, fx):
        if fx == "lp":
            return self.values["lp_cutoff"] < 14500.0 or self.hand_mode["lp"]
        if fx == "wah":
            return self.values["wah_mix"] > 0.01 or self.hand_mode["wah"]
        if fx == "delay":
            return self.values["delay_wet"] > 0.01 or self.hand_mode["delay"]
        return False

    def draw(self, image):
        px, py, pw, ph = self.panel_x, self.panel_y, self.panel_w, self.panel_h
        darken_rect_inplace(image, px, py, px + pw, py + ph, (18, 18, 24), 0.24)
        cv2.rectangle(image, (px, py), (px + pw, py + ph), (70, 75, 90), 1)

        cv2.putText(
            image,
            "FILTROS Y EFECTOS DSP",
            (px + 12, py + 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (235, 235, 245),
            1,
        )
        cv2.putText(
            image,
            "[F/W/E] Mano",
            (px + pw - 102, py + 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.37,
            (175, 185, 200),
            1,
        )

        for spec in self.CARD_SPECS:
            fx = spec["fx"]
            col = spec["color"]
            active_fx = self.is_fx_active(fx)
            x0, y0, x1, y1 = self.card_boxes[fx]

            cv2.rectangle(image, (x0, y0), (x1, y1), col if active_fx else (75, 78, 90), 2 if active_fx else 1)

            header_h = 28
            if active_fx:
                cv2.rectangle(image, (x0, y0), (x1, y0 + header_h), col, -1)
                t_col = (15, 15, 18)
                b_col = (20, 20, 25)
            else:
                darken_rect_inplace(image, x0 + 1, y0 + 1, x1 - 1, y0 + header_h, (32, 34, 42), 0.35)
                t_col = col
                b_col = (170, 175, 185)

            cv2.putText(image, spec["title"], (x0 + 8, y0 + 19), cv2.FONT_HERSHEY_SIMPLEX, 0.42, t_col, 2 if active_fx else 1)

            if self.hand_mode[fx]:
                badge = "MANO"
            elif active_fx:
                badge = "ACTIVO"
            else:
                badge = "OFF"
            cv2.putText(image, badge, (x1 - 66, y0 + 19), cv2.FONT_HERSHEY_SIMPLEX, 0.37, b_col, 2 if active_fx else 1)

            for sl in spec["sliders"]:
                sid = sl["id"]
                sx1, syc, sx2, _ = self.slider_rects[sid]
                val = self.values[sid]
                ratio = self._value_to_ratio(sid, val)
                hx = int(sx1 + ratio * (sx2 - sx1))
                is_drag = self.dragging == sid

                cv2.putText(image, sl["label"], (x0 + 8, syc + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (205, 210, 220), 1)
                cv2.rectangle(image, (sx1, syc - 4), (sx2, syc + 4), (55, 58, 68), -1)

                # Para Low-Pass, resaltar cuanto se recorto desde la derecha o rellenar hasta el corte
                if hx > sx1:
                    cv2.rectangle(image, (sx1, syc - 4), (hx, syc + 4), col, -1)

                # Etiquetas de extremos para orientacion rapida
                cv2.putText(image, sl["left_tag"], (sx1, syc + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (145, 150, 160), 1)
                cv2.putText(image, sl["right_tag"], (sx2 - 36, syc + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (145, 150, 160), 1)

                rad = 9 if is_drag else 7
                cv2.circle(image, (hx, syc), rad, (255, 255, 255) if is_drag else col, -1)
                cv2.circle(image, (hx, syc), rad, (255, 255, 255), 1)

                val_txt = self._format_value(sid, val)
                cv2.putText(
                    image,
                    val_txt,
                    (sx2 + 8, syc + 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.40,
                    (255, 255, 255) if is_drag else col,
                    2 if is_drag else 1,
                )


class LiquidArtGenerator:
    """Motor de sintesis visual liquida en tiempo real para la ventana de proyeccion."""

    STYLE_NAMES = [
        "1: Tinta Liquida en Agua",
        "2: Seda y Plasma Organico",
        "3: Ferrofluido Abisal",
    ]

    def __init__(self, sim_w=240, sim_h=135, out_w=1280, out_h=720):
        self.sim_w = sim_w
        self.sim_h = sim_h
        self.out_w = out_w
        self.out_h = out_h
        self.style_idx = 0

        self.canvas = np.zeros((sim_h, sim_w, 3), dtype=np.float32)

        x_lin = np.linspace(0.0, 1.0, sim_w, dtype=np.float32)
        y_lin = np.linspace(0.0, 1.0, sim_h, dtype=np.float32)
        self.gx, self.gy = np.meshgrid(x_lin, y_lin)

        px_lin = np.arange(sim_w, dtype=np.float32)
        py_lin = np.arange(sim_h, dtype=np.float32)
        self.px_grid, self.py_grid = np.meshgrid(px_lin, py_lin)

        self.prev_pos = None

        # Silueta organica de manos (Efecto Vidrio Esmerilado / Sombra sumergida)
        self.shadow_enabled = True
        self.shadow_intensity = 0.85
        self.shadow_scale = 1.0

    def toggle_shadow(self):
        self.shadow_enabled = not self.shadow_enabled
        return self.shadow_enabled

    def adjust_shadow_scale(self, delta):
        self.shadow_scale = float(np.clip(self.shadow_scale + delta, 0.20, 2.50))
        return self.shadow_scale

    def get_scaled_hand_coords(self, hand_obj, lm_idx):
        """Devuelve (x, y) en [0.0, 1.0] escalando la mano geometricamente alrededor del centro de la palma."""
        lms = hand_obj.landmarks
        if lms is None:
            return 0.5, 0.5
        lm = lms[lm_idx]
        if abs(self.shadow_scale - 1.0) < 1e-4:
            return float(lm.x), float(lm.y)
        # Centro anatomico de la palma (promedio muneca y base dedo mayor)
        hcx = (lms[0].x + lms[9].x) * 0.5
        hcy = (lms[0].y + lms[9].y) * 0.5
        sx = hcx + (lm.x - hcx) * self.shadow_scale
        sy = hcy + (lm.y - hcy) * self.shadow_scale
        return float(np.clip(sx, 0.0, 1.0)), float(np.clip(sy, 0.0, 1.0))

    def _draw_hand_shadow_mask(self, hand_obj, target_mask):
        """Dibuja exclusivamente la mano (palma + 5 dedos, sin antebrazo/muñeca) con escala geometrica."""
        if not hand_obj.active or hand_obj.landmarks is None:
            return

        lms = hand_obj.landmarks
        w = self.sim_w
        h = self.sim_h

        def to_p(lm_idx):
            sx, sy = self.get_scaled_hand_coords(hand_obj, lm_idx)
            return int(sx * w), int(sy * h)

        # 1. Palma (poligono cerrado que delimita la mano hasta su base)
        palm_indices = [0, 1, 5, 9, 13, 17]
        palm_pts = np.array([to_p(idx) for idx in palm_indices], dtype=np.int32)
        cv2.fillPoly(target_mask, [palm_pts], 1.0)

        # 2. Falanges y yemas de los dedos (solo la mano)
        finger_chains = [
            [0, 1, 2, 3, 4],     # Pulgar
            [5, 6, 7, 8],        # Indice
            [9, 10, 11, 12],     # Mayor
            [13, 14, 15, 16],    # Anular
            [17, 18, 19, 20],    # Menique
        ]

        scale = self.shadow_scale
        for chain in finger_chains:
            for i in range(len(chain) - 1):
                p1 = to_p(chain[i])
                p2 = to_p(chain[i + 1])
                thick = max(2, int(round((5.0 - i * 0.6) * (0.55 + 0.45 * scale))))
                cv2.line(target_mask, p1, p2, 1.0, thick)
                cv2.circle(target_mask, p1, thick, 1.0, -1)

            tip_p = to_p(chain[-1])
            tip_z = lms[chain[-1]].z
            tip_intensity = float(np.clip(1.0 - tip_z * 2.0, 0.85, 1.0))
            tip_r = max(2, int(round(4.0 * (0.60 + 0.40 * scale))))
            cv2.circle(target_mask, tip_p, tip_r, tip_intensity, -1)

    def next_style(self):
        self.style_idx = (self.style_idx + 1) % len(self.STYLE_NAMES)
        return self.STYLE_NAMES[self.style_idx]

    def clear(self):
        self.canvas.fill(0.0)

    def render(
        self,
        t_sec,
        active_state_idx,
        hand,
        cutoff_hz,
        wah_freq,
        delay_wet,
        active_vol,
        mar_vol,
        sea_active=False,
    ):
        open_ratio = hz_to_log_ratio(cutoff_hz, 120.0, 15000.0)
        wah_ratio = hz_to_log_ratio(wah_freq, 180.0, 3800.0)

        flow_speed = 0.8 + 1.6 * open_ratio + 0.8 * wah_ratio
        swirl_amp = 1.35 + 2.4 * open_ratio

        phase_t = t_sec * flow_speed
        angle_field = (
            np.sin(self.gx * 5.2 + phase_t * 0.7) * np.cos(self.gy * 4.4 - phase_t * 0.5)
            + 0.6 * np.sin((self.gx + self.gy) * 6.5 - phase_t * 0.9)
        )

        push_vx = np.zeros_like(self.gx)
        push_vy = np.zeros_like(self.gy)

        if hand.active:
            hx, hy = hand.norm_x, hand.norm_y
            if self.prev_pos is not None:
                dhx = (hx - self.prev_pos[0]) * 55.0
                dhy = (hy - self.prev_pos[1]) * 55.0
                dist_sq = (self.gx - hx) ** 2 + (self.gy - hy) ** 2
                influence = np.exp(-dist_sq / 0.045)
                push_vx -= dhx * influence * self.sim_w
                push_vy -= dhy * influence * self.sim_h
            self.prev_pos = (hx, hy)
        else:
            self.prev_pos = None

        map_x = (self.px_grid + np.cos(angle_field * 3.14159) * swirl_amp + push_vx).astype(np.float32)
        map_y = (self.py_grid + np.sin(angle_field * 3.14159) * swirl_amp + push_vy).astype(np.float32)

        decay = float(np.clip(0.935 + 0.048 * delay_wet, 0.91, 0.985))
        self.canvas = cv2.remap(
            self.canvas,
            map_x,
            map_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT,
        ) * decay
        self.canvas = cv2.GaussianBlur(self.canvas, (5, 5), 0)

        bg_wave = 0.5 + 0.5 * np.sin(self.gx * 3.5 + angle_field * 1.4 - t_sec * 0.4)
        if sea_active:
            mar_scale = float(np.clip(0.5 + mar_vol * 0.9, 0.2, 2.2))
            self.canvas[:, :, 0] += bg_wave * 1.3 * mar_scale
            self.canvas[:, :, 1] += (1.0 - bg_wave) * 0.65 * mar_scale
            self.canvas[:, :, 2] += bg_wave * 0.28 * mar_scale
        else:
            self.canvas[:, :, 0] += bg_wave * 0.7
            self.canvas[:, :, 1] += (1.0 - bg_wave) * 0.35
            self.canvas[:, :, 2] += bg_wave * 0.45

        # 2.5 Silueta translucida de las manos (Efecto Vidrio Esmerilado / Sombra organica sumergida)
        if self.shadow_enabled and hand.active:
            raw_shadow = np.zeros((self.sim_h, self.sim_w), dtype=np.float32)
            self._draw_hand_shadow_mask(hand, raw_shadow)

            # Desenfoque gaussiano proporcional al tamaño de la mano para mantener constante
            # la relacion entre el borde difuso y el cuerpo de la mano:
            scale = self.shadow_scale
            kw = max(5, int(round(27 * scale)) | 1)
            kc = max(3, int(round(11 * scale)) | 1)
            sw = max(1.2, 7.0 * scale)
            sc = max(0.6, 2.2 * scale)

            blur_wide = cv2.GaussianBlur(raw_shadow, (kw, kw), sw)
            blur_core = cv2.GaussianBlur(raw_shadow, (kc, kc), sc)
            combined = 0.55 * blur_wide + 0.45 * blur_core

            # Normalizacion de contraste constante: evita que la mano se lave o pierda presencia
            # cuando se achica (garantiza la misma densidad de sombra oscura en cualquier escala)
            peak_val = float(np.max(combined))
            if peak_val > 0.05:
                shadow_map = np.clip(combined * (0.92 / peak_val), 0.0, 1.0)
            else:
                shadow_map = combined

            # Atenua suavemente los fluidos bajo la mano creando la silueta oscura
            dimmer = 1.0 - shadow_map[:, :, None] * (0.82 * self.shadow_intensity)
            # Tinte sombrio organico (azul noche / tinta profunda)
            shadow_tint = np.array([22.0, 16.0, 12.0], dtype=np.float32) * (shadow_map[:, :, None] * self.shadow_intensity)
            self.canvas = self.canvas * dimmer + shadow_tint

        if active_state_idx in (0, 1) and hand.active and active_vol > 0.01:
            st = STATES[active_state_idx]
            col_b, col_g, col_r = st["color"]
            ripple_hz = st["ripple_freq"]
            vol_gain = float(np.clip(active_vol, 0.0, 2.0))

            if active_state_idx == 0 and hand.landmarks is not None:
                emitters = [
                    self.get_scaled_hand_coords(hand, idx)
                    for idx in FINGER_TIPS
                ]
                scale_gain = 0.55
            else:
                emitters = [
                    (
                        float(np.clip(hand.metrics["palm_cx"], 0.05, 0.95)),
                        float(np.clip(hand.metrics["palm_cy"], 0.05, 0.95)),
                    )
                ]
                scale_gain = 1.65

            for cx, cy in emitters:
                dx = (self.gx - cx) * 1.77 + 0.035 * np.sin(self.gy * 10.0 + t_sec * 2.0)
                dy = (self.gy - cy) + 0.035 * np.cos(self.gx * 10.0 - t_sec * 2.0)
                r = np.sqrt(dx * dx + dy * dy)

                if self.style_idx == 0:
                    blob = np.exp(-(r * r) / (0.020 + 0.015 * open_ratio))
                    ring = 0.65 + 0.35 * np.sin(r * 38.0 - t_sec * ripple_hz + angle_field * 2.2)
                    intensity = blob * ring * (12.0 + 10.0 * vol_gain) * scale_gain
                elif self.style_idx == 1:
                    blob = np.exp(-(r * r) / 0.045)
                    ring = (0.5 + 0.5 * np.cos(r * 52.0 - t_sec * ripple_hz + angle_field * 3.0)) ** 1.6
                    intensity = blob * ring * (16.0 + 11.0 * vol_gain) * scale_gain
                else:
                    blob = np.exp(-(r * r) / 0.025)
                    wave_crest = np.abs(np.sin(r * 60.0 - t_sec * ripple_hz + angle_field * 3.5)) ** 3.0
                    intensity = blob * wave_crest * (20.0 + 12.0 * vol_gain) * scale_gain

                self.canvas[:, :, 0] += intensity * (col_b / 255.0)
                self.canvas[:, :, 1] += intensity * (col_g / 255.0)
                self.canvas[:, :, 2] += intensity * (col_r / 255.0)

        mapped = 255.0 * (1.0 - np.exp(-self.canvas / 155.0))
        luma = 0.114 * mapped[:, :, 0] + 0.587 * mapped[:, :, 1] + 0.299 * mapped[:, :, 2]
        grad_x = cv2.Sobel(luma, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(luma, cv2.CV_32F, 0, 1, ksize=3)
        spec_mag = np.sqrt(grad_x * grad_x + grad_y * grad_y)
        specular = np.clip((spec_mag - 35.0) * 0.28, 0.0, 55.0)

        mapped[:, :, 0] = np.clip(mapped[:, :, 0] + specular, 0.0, 255.0)
        mapped[:, :, 1] = np.clip(mapped[:, :, 1] + specular, 0.0, 255.0)
        mapped[:, :, 2] = np.clip(mapped[:, :, 2] + specular, 0.0, 255.0)

        sim_u8 = mapped.astype(np.uint8)
        return cv2.resize(sim_u8, (self.out_w, self.out_h), interpolation=cv2.INTER_CUBIC)


class ThreadedCamera:
    """Lector de camara en segundo plano con reconexion automatica (Watchdog)."""

    def __init__(self, cam_index=0, width=1280, height=720):
        self.cam_index = cam_index
        self.width = width
        self.height = height
        self.cap = None
        self.lock = threading.Lock()
        self.frame = None
        self.running = False
        self.thread = None

    def _open_camera(self):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass

        cap = cv2.VideoCapture(self.cam_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            fallback = 1 if self.cam_index == 0 else 0
            cap = cv2.VideoCapture(fallback, cv2.CAP_DSHOW)
            if cap.isOpened():
                self.cam_index = fallback
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(self.cam_index)

        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap = cap
        return cap.isOpened()

    def start(self):
        if not self._open_camera():
            return False
        self.running = True
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()
        return True

    def _reader_loop(self):
        consecutive_failures = 0
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(0.2)
                self._open_camera()
                continue

            ok, frm = self.cap.read()
            if ok and frm is not None:
                consecutive_failures = 0
                with self.lock:
                    self.frame = frm
            else:
                consecutive_failures += 1
                time.sleep(0.01)
                if consecutive_failures >= 45:
                    print("[CAMARA] Reiniciando conexion USB de camara automaticamente...")
                    self._open_camera()
                    consecutive_failures = 0

    def read(self):
        with self.lock:
            if self.frame is None:
                return False, None
            return True, self.frame.copy()

    def release(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass


def darken_rect_inplace(img, x1, y1, x2, y2, bg_bgr=(20, 20, 26), alpha=0.28):
    """Oscurece solo la region del panel sin copiar toda la imagen en cada frame."""
    h, w = img.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return
    roi = img[y1:y2, x1:x2]
    bg = np.array(bg_bgr, dtype=np.uint8)
    cv2.addWeighted(roi, alpha, np.broadcast_to(bg, roi.shape), 1.0 - alpha, 0, dst=roi)


def ensure_plugdata_running(pd_patch_path):
    """Abre automaticamente PlugData (o Pure Data) con mesa_sonora.pd si no esta abierto."""
    try:
        out = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True,
            errors="ignore",
        ).lower()
        if "plugdata.exe" in out or "pd.exe" in out:
            print("[PLUGDATA] PlugData / Pure Data detectado activo (Motor de Audio principal).")
            return True
    except Exception:
        pass

    candidates = [
        r"C:\Program Files\plugdata\plugdata.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\plugdata\plugdata.exe"),
        r"C:\Program Files\Pd\bin\pd.exe",
        r"C:\Program Files (x86)\Pd\bin\pd.exe",
    ]
    for exe in candidates:
        if os.path.isfile(exe):
            try:
                print(f"[PLUGDATA] Iniciando motor de sonido: {exe} -> {os.path.basename(pd_patch_path)}")
                subprocess.Popen([exe, pd_patch_path], cwd=os.path.dirname(pd_patch_path))
                return True
            except Exception as e:
                print(f"[AVISO] No se pudo lanzar {exe}: {e}")

    print("[AVISO] No se encontro plugdata.exe ni pd.exe. Abri mesa_sonora.pd manualmente.")
    return False


def dist2d(p1, p2):
    return math.hypot(p1.x - p2.x, p1.y - p2.y)


def analyze_hand_posture(landmarks):
    """
    Detecta si la mano esta ABIERTA (0 = aves) o en PUNO CERRADO (1 = sapos).
    Retorna (raw_state_idx, main_fingers_up_count, metrics).
    """
    wrist = landmarks[0]
    index_mcp = landmarks[5]
    middle_mcp = landmarks[9]
    pinky_mcp = landmarks[17]

    palm_size = max(0.04, (dist2d(wrist, middle_mcp) + dist2d(index_mcp, pinky_mcp)) * 0.5)

    finger_specs = [
        (8, 7, 6, 5),     # Indice
        (12, 11, 10, 9),  # Mayor
        (16, 15, 14, 13), # Anular
        (20, 19, 18, 17), # Menique
    ]

    main_up = 0
    ext_ratios = []
    for tip_i, dip_i, pip_i, mcp_i in finger_specs:
        tip = landmarks[tip_i]
        dip = landmarks[dip_i]
        pip = landmarks[pip_i]
        mcp = landmarks[mcp_i]

        d_wrist_tip = dist2d(wrist, tip)
        d_wrist_dip = dist2d(wrist, dip)
        d_wrist_pip = dist2d(wrist, pip)
        d_wrist_mcp = max(1e-4, dist2d(wrist, mcp))

        ext_ratio = float(np.clip((d_wrist_tip - d_wrist_mcp) / (d_wrist_mcp * 0.92), 0.0, 1.0))
        ext_ratios.append(ext_ratio)

        if d_wrist_tip > d_wrist_pip * 1.05 and d_wrist_tip > d_wrist_dip * 1.01 and ext_ratio > 0.45:
            main_up += 1

    avg_ext = sum(ext_ratios) / 4.0

    if main_up >= 3:
        raw_state = 0
    elif main_up <= 1:
        raw_state = 1
    else:
        raw_state = None

    depth_norm = float(np.clip((palm_size - 0.07) / 0.22, 0.0, 1.0))
    palm_cx = float((wrist.x + middle_mcp.x) * 0.5)
    palm_cy = float((wrist.y + middle_mcp.y) * 0.5)

    metrics = {
        "openness": avg_ext,
        "depth_norm": depth_norm,
        "palm_size": palm_size,
        "palm_cx": palm_cx,
        "palm_cy": palm_cy,
    }
    return raw_state, main_up, metrics


class HandStateTracker:
    """Mantiene suavizado espacial y estabilizacion temporal (debounce) de los 2 estados."""

    DEBOUNCE_FRAMES = 3

    def __init__(self):
        self.active = False
        self.smooth_x = 0.5
        self.smooth_y = 0.5
        self.norm_x = 0.5
        self.norm_y = 0.5
        self.stable_state = None
        self.candidate_state = None
        self.candidate_streak = 0
        self.main_fingers_up = 0
        self.landmarks = None
        self.metrics = {
            "openness": 0.0,
            "depth_norm": 0.3,
            "palm_size": 0.1,
            "palm_cx": 0.5,
            "palm_cy": 0.5,
        }

    def reset_inactive(self):
        self.active = False
        self.landmarks = None
        self.stable_state = None
        self.candidate_state = None
        self.candidate_streak = 0
        self.main_fingers_up = 0

    def update(self, landmarks, smooth_factor, margin):
        was_active = self.active
        self.active = True
        self.landmarks = landmarks

        raw_state, self.main_fingers_up, self.metrics = analyze_hand_posture(landmarks)

        if raw_state is None and self.stable_state is None:
            raw_state = 0 if self.metrics["openness"] >= 0.50 else 1

        if raw_state is not None:
            if raw_state == self.candidate_state:
                self.candidate_streak += 1
            else:
                self.candidate_state = raw_state
                self.candidate_streak = 1

            if self.candidate_streak >= self.DEBOUNCE_FRAMES:
                self.stable_state = self.candidate_state

        raw_x = max(0.0, min(1.0, self.metrics["palm_cx"]))
        raw_y = max(0.0, min(1.0, self.metrics["palm_cy"]))

        if not was_active:
            self.smooth_x = raw_x
            self.smooth_y = raw_y
        else:
            self.smooth_x = smooth_factor * self.smooth_x + (1.0 - smooth_factor) * raw_x
            self.smooth_y = smooth_factor * self.smooth_y + (1.0 - smooth_factor) * raw_y

        denom = 1.0 - 2.0 * margin
        self.norm_x = max(0.0, min(1.0, (self.smooth_x - margin) / denom if denom > 0 else self.smooth_x))
        self.norm_y = max(0.0, min(1.0, (self.smooth_y - margin) / denom if denom > 0 else self.smooth_y))


def draw_hand_skeleton(image, hand, w, h):
    """Dibuja el esqueleto de la mano coloreado segun el estado activo."""
    landmarks = hand.landmarks
    if landmarks is None:
        return

    if hand.stable_state in (0, 1):
        st = STATES[hand.stable_state]
        color = st["color"]
        label = f"{st['gesture_name'].upper()} -> {st['sound_title'].upper()}"
    else:
        color = (200, 200, 200)
        label = "DETECTANDO..."

    for c0, c1 in HAND_CONNECTIONS:
        p0, p1 = landmarks[c0], landmarks[c1]
        cv2.line(image, (int(p0.x * w), int(p0.y * h)), (int(p1.x * w), int(p1.y * h)), color, 2)

    for tip_idx in FINGER_TIPS:
        lm = landmarks[tip_idx]
        fx, fy = int(lm.x * w), int(lm.y * h)
        radius = 9 if hand.stable_state == 0 else 6
        cv2.circle(image, (fx, fy), radius, color, -1)
        cv2.circle(image, (fx, fy), radius + 2, (255, 255, 255), 1)

    wx = int(landmarks[0].x * w)
    wy = int(landmarks[0].y * h)
    cv2.putText(
        image,
        label,
        (max(16, wx - 110), min(h - 54, wy + 30)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        color,
        2,
    )


def udp_send_safe(sock, target, msg_str):
    """Envio UDP no bloqueante hacia PlugData."""
    try:
        sock.sendto(msg_str.encode("ascii"), target)
    except (BlockingIOError, OSError):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Mesa Sonora - 2 Estados + Mixer Vol/Pan + Sliders DSP -> PlugData"
    )
    parser.add_argument("--cam", type=int, default=0, help="Indice de camara; por defecto 0")
    parser.add_argument("--port", type=int, default=9000, help="Puerto UDP de PlugData / Pure Data")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="IP de PlugData / Pure Data")
    parser.add_argument("--model", type=str, default=None, help="Ruta opcional a hand_landmarker.task")
    parser.add_argument("--smooth", type=float, default=0.70, help="Factor de suavizado EMA")
    parser.add_argument("--margin", type=float, default=0.08, help="Margen activo en bordes")
    parser.add_argument("--no-pd", action="store_true", help="No abrir PlugData automaticamente")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = args.model or os.path.join(script_dir, "hand_landmarker.task")
    if not os.path.isfile(model_path):
        print(f"[ERROR] No encuentro el modelo: {model_path}")
        sys.exit(1)

    pd_patch_path = os.path.join(script_dir, "mesa_sonora.pd")
    if not args.no_pd and os.path.isfile(pd_patch_path):
        ensure_plugdata_running(pd_patch_path)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    target = (args.host, args.port)
    udp_send_safe(sock, target, "ambient 0.0 50;\n")

    smooth_factor = max(0.0, min(0.95, args.smooth))
    margin = max(0.0, min(0.20, args.margin))

    print("=" * 88)
    print("MESA SONORA - 2 ESTADOS + MIXER VOL/PAN + SLIDERS DE FILTROS DSP -> PLUGDATA")
    print("=" * 88)
    print("  * ESTADO 1 (Mano Abierta) : paisaje-de-aves.wav  (Vol: 135% | Pan: C)")
    print("  * ESTADO 2 (Puno Cerrado) : paisaje-de-sapos.wav (Vol: 160% | Pan: C)")
    print("  * FONDO CONSTANTE         : paisaje-de-mar.wav   (Vol:  35% | Pan: C)")
    print("  * PANEL DERECHO (DSP)     : Sliders de LOW-PASS, WAH RESONANTE y DELAY / ECO")
    print("-" * 88)
    print("  MOUSE IZQ   : Arrastrar sliders (Vol/Pan a la izq | Low/Wah/Delay a la der)")
    print("  MOUSE DER   : Resetear un slider individual | [R] : Resetear mixer y filtros")
    print("  [F]/[W]/[E] : Alternar control por MANO vs SLIDER para Low-Pass, Wah y Delay")
    print("  [S]         : Activar / Desactivar Silueta difusa de manos (Efecto Vidrio Esmerilado)")
    print("  [+] / [-]   : Aumentar / Disminuir tamaño de la mano en vivo (adaptar a proyector o PC)")
    print("  [F11] / [P] : PANTALLA COMPLETA en ventana de Proyeccion Liquida")
    print("  [V]         : Cambiar estilo visual | [M] : Mar manual")
    print("  [C]         : Silenciar todo | [Q]/ESC : Salir")
    print("=" * 88)

    cam_stream = ThreadedCamera(args.cam, width=1280, height=720)
    if not cam_stream.start():
        sock.close()
        print("[ERROR] No se pudo abrir la camara.")
        sys.exit(1)

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1280, 720)

    cv2.namedWindow(VISUAL_WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(VISUAL_WINDOW_NAME, 1280, 720)

    mixer = SoundscapeMixer(panel_x=12, panel_y=82, panel_w=386)
    fx_panel = EffectsPanel(panel_x=882, panel_y=82, panel_w=386)

    def handle_mouse(event, x, y, flags, param):
        if mixer.on_mouse(event, x, y, flags, param):
            return
        fx_panel.on_mouse(event, x, y, flags, param)

    cv2.setMouseCallback(WINDOW_NAME, handle_mouse)
    mixer.send_udp(sock, target)
    fx_panel.send_udp(sock, target)

    liquid_gen = LiquidArtGenerator(sim_w=240, sim_h=135, out_w=1280, out_h=720)
    projector_fullscreen = False

    base_options = python.BaseOptions(model_asset_path=model_path)
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
    )
    detector = vision.HandLandmarker.create_from_options(options)

    hand = HandStateTracker()

    last_active = -1
    last_state_id = -1
    last_sent_channels = ""
    last_udp_fx_time = 0.0
    last_channels_heartbeat = 0.0
    last_mixer_heartbeat = 0.0
    last_gc_time = time.monotonic()
    last_video_ts_ms = 0
    start_time = time.monotonic()

    fps = 0.0
    prev_time = time.monotonic()

    # Pista base de fondo (Paisaje de Mar): Fade-In al interactuar y Fade-Out tras 10s de inactividad
    last_interaction_time = -999.0
    ambient_active = False
    last_ambient_state = False

    try:
        while True:
            ok, image = cam_stream.read()
            if not ok or image is None:
                key = cv2.waitKey(5) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    break
                continue

            if image.shape[1] != 1280 or image.shape[0] != 720:
                image = cv2.resize(image, (1280, 720), interpolation=cv2.INTER_LINEAR)
            image = cv2.flip(image, 1)
            h, w = image.shape[:2]

            small_bgr = cv2.resize(image, (640, 360), interpolation=cv2.INTER_LINEAR)
            rgb = np.ascontiguousarray(cv2.cvtColor(small_bgr, cv2.COLOR_BGR2RGB))
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            now_mono = time.monotonic()
            ts_ms = int(now_mono * 1000)
            if ts_ms <= last_video_ts_ms:
                ts_ms = last_video_ts_ms + 1
            last_video_ts_ms = ts_ms

            result = detector.detect_for_video(mp_image, ts_ms)
            hands = result.hand_landmarks or []
            active = 1 if len(hands) > 0 else 0

            if active:
                hand.update(hands[0], smooth_factor, margin)
                draw_hand_skeleton(image, hand, w, h)
            else:
                hand.reset_inactive()

            # ================= DOS ESTADOS -> 2 CANALES EN PLUGDATA =================
            active_channels = [
                hand.active and hand.stable_state == 0,  # Canal 1: Mano abierta -> paisaje-de-aves
                hand.active and hand.stable_state == 1,  # Canal 2: Puno cerrado -> paisaje-de-sapos
            ]
            state_id = 1 if active_channels[0] else (2 if active_channels[1] else 0)
            n_playing = 1 if state_id > 0 else 0

            # Si algun efecto tiene modo MANO activo ([F]/[W]/[E]), actualiza sus sliders en vivo
            fx_panel.apply_hand_modulation(hand)

            # ================= ENVIO UDP HACIA PLUGDATA =================
            ch_str = f"{1 if active_channels[0] else 0} {1 if active_channels[1] else 0}"
            if ch_str != last_sent_channels or (now_mono - last_channels_heartbeat) > 0.45:
                udp_send_safe(sock, target, f"channels {ch_str};\n")
                last_sent_channels = ch_str
                last_channels_heartbeat = now_mono

            if mixer.dirty or (now_mono - last_mixer_heartbeat) > 0.50:
                mixer.send_udp(sock, target)
                last_mixer_heartbeat = now_mono

            any_hand_fx = any(fx_panel.hand_mode.values())
            if fx_panel.dirty or (any_hand_fx and (now_mono - last_udp_fx_time) >= 0.040) or (now_mono - last_udp_fx_time) > 0.50:
                fx_panel.send_udp(sock, target)
                last_udp_fx_time = now_mono

            if active != last_active:
                udp_send_safe(sock, target, f"active {active};\n")
                last_active = active

            if state_id != last_state_id:
                udp_send_safe(sock, target, f"state {state_id};\n")
                last_state_id = state_id

            # Control dinamico de la pista base (Paisaje de Mar):
            is_interacting = (active == 1) or (n_playing > 0)
            if is_interacting:
                last_interaction_time = now_mono

            time_since_interaction = now_mono - last_interaction_time
            ambient_active = time_since_interaction < 10.0

            if ambient_active != last_ambient_state:
                last_ambient_state = ambient_active
                target_vol = 1.0 if ambient_active else 0.0
                ramp_ms = 2500 if ambient_active else 4500
                udp_send_safe(sock, target, f"ambient {target_vol:.2f} {ramp_ms};\n")
                if ambient_active:
                    print("[PAISAJE DE MAR] Interaccion detectada -> Entrando (Fade In 2.5s)...")
                else:
                    print("[PAISAJE DE MAR] 10s de inactividad -> Saliendo (Fade Out 4.5s)...")

            if (now_mono - last_gc_time) > 30.0:
                gc.collect(0)
                last_gc_time = now_mono

            dt = now_mono - prev_time
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)
            prev_time = now_mono

            # ================= VENTANA 2: PROYECCION LIQUIDA =================
            active_vol = (
                mixer.values["aves"]["vol"]
                if state_id == 1
                else (mixer.values["sapos"]["vol"] if state_id == 2 else 0.0)
            )
            t_elapsed = now_mono - start_time
            liquid_frame = liquid_gen.render(
                t_sec=t_elapsed,
                active_state_idx=hand.stable_state if hand.active else None,
                hand=hand,
                cutoff_hz=fx_panel.values["lp_cutoff"],
                wah_freq=fx_panel.values["wah_freq"],
                delay_wet=fx_panel.values["delay_wet"],
                active_vol=active_vol,
                mar_vol=mixer.values["mar"]["vol"],
                sea_active=ambient_active,
            )
            cv2.imshow(VISUAL_WINDOW_NAME, liquid_frame)

            # ================= VENTANA 1: HUD DE TRACKEO + MIXER + FILTROS =================
            darken_rect_inplace(image, 0, 0, w, 72, (18, 18, 22), 0.28)
            darken_rect_inplace(image, 0, h - 40, w, h, (16, 16, 22), 0.24)

            if state_id == 1:
                state_text = "ESTADO 1: MANO ABIERTA -> PAISAJE DE AVES"
                state_color = STATES[0]["color"]
            elif state_id == 2:
                state_text = "ESTADO 2: PUNO CERRADO -> PAISAJE DE SAPOS"
                state_color = STATES[1]["color"]
            else:
                state_text = "MOSTRA TU MANO: ABIERTA (AVES) O PUNO CERRADO (SAPOS)"
                state_color = (140, 175, 255)

            cv2.putText(image, state_text, (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.56, state_color, 2)

            if ambient_active:
                if is_interacting:
                    mar_badge = "ACTIVO"
                else:
                    rem_sec = max(0.0, 10.0 - time_since_interaction)
                    mar_badge = f"COLA {rem_sec:.1f}s"
            else:
                mar_badge = "REPOSO"

            lp_v = fx_panel._format_value("lp_cutoff", fx_panel.values["lp_cutoff"])
            wm_v = fx_panel._format_value("wah_mix", fx_panel.values["wah_mix"])
            wf_v = fx_panel._format_value("wah_freq", fx_panel.values["wah_freq"])
            dl_v = fx_panel._format_value("delay_wet", fx_panel.values["delay_wet"])
            shadow_lbl = f"ON (Mano:{int(liquid_gen.shadow_scale * 100)}% [+ / -])" if liquid_gen.shadow_enabled else "OFF"
            sub_header = (
                f"LP:{lp_v} | Wah:{wm_v}@{wf_v} | Eco:{dl_v} | Mar[M]:{mar_badge} | Sombra[S]:{shadow_lbl} | "
                f"Visual[V]: {liquid_gen.STYLE_NAMES[liquid_gen.style_idx]} | Proyector[F11/P] | FPS:{int(fps)}"
            )
            cv2.putText(image, sub_header, (16, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.39, (225, 225, 225), 1)

            # Panel Izquierdo: Mixer Vol / Pan por paisaje
            mixer.draw(
                image,
                active_map={
                    "aves": active_channels[0],
                    "sapos": active_channels[1],
                    "mar": ambient_active,
                },
                mar_status_label=mar_badge,
            )

            # Panel Derecho: Sliders de Low-Pass, Wah y Delay
            fx_panel.draw(image)

            # Barra inferior de monitoreo rapido en tiempo real
            av = mixer.values["aves"]
            sp = mixer.values["sapos"]
            mr = mixer.values["mar"]
            monitor_txt = (
                f"AVES[{'ON' if active_channels[0] else 'OFF'}] {int(round(av['vol']*100))}% {format_pan_label(av['pan'])} | "
                f"SAPOS[{'ON' if active_channels[1] else 'OFF'}] {int(round(sp['vol']*100))}% {format_pan_label(sp['pan'])} | "
                f"MAR[{'ON' if ambient_active else 'OFF'}] {int(round(mr['vol']*100))}% {format_pan_label(mr['pan'])} || "
                f"LP:{lp_v}  WAH:{wm_v}({wf_v})  ECO:{dl_v} | Clic der: reset slider | [R]: Reset"
            )
            cv2.putText(image, monitor_txt, (14, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.39, (225, 230, 240), 1)

            cv2.imshow(WINDOW_NAME, image)

            key_raw = cv2.waitKeyEx(1)
            key = key_raw & 0xFF if key_raw != -1 else -1
            if key in (ord("q"), ord("Q"), 27):
                break
            elif key in (ord("p"), ord("P")) or key_raw in (0x7A0000, 0x0100003A, 0xFFC8, 0x1008FFC8, 63246, 7995392):
                projector_fullscreen = not projector_fullscreen
                prop = cv2.WINDOW_FULLSCREEN if projector_fullscreen else cv2.WINDOW_NORMAL
                cv2.setWindowProperty(VISUAL_WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, prop)
                print(f"[PROYECTOR] Pantalla completa (F11/P): {'ACTIVADA' if projector_fullscreen else 'VENTANA NORMAL'}")
            elif key in (ord("v"), ord("V")):
                style_name = liquid_gen.next_style()
                print(f"[VISUALES LIQUIDAS] Estilo cambiado a -> {style_name}")
            elif key in (ord("s"), ord("S")):
                sh_on = liquid_gen.toggle_shadow()
                print(f"[VISUALES] Silueta difusa de manos: {'ACTIVADA (Efecto Vidrio Esmerilado)' if sh_on else 'DESACTIVADA'}")
            elif key in (ord("r"), ord("R")):
                mixer.reset_all()
                fx_panel.reset_all()
                mixer.send_udp(sock, target)
                fx_panel.send_udp(sock, target)
                print("[RESET] Mixer y filtros DSP reseteados a valores iniciales.")
            elif key in (ord("f"), ord("F")):
                fx_panel.hand_mode["lp"] = not fx_panel.hand_mode["lp"]
                if not fx_panel.hand_mode["lp"]:
                    fx_panel.values["lp_cutoff"] = fx_panel.DEFAULTS["lp_cutoff"]
                fx_panel.dirty = True
                print(f"[LOW-PASS] Modo: {'CONTROL POR MANO (Eje X)' if fx_panel.hand_mode['lp'] else 'SLIDER MANUAL (Abierto)'}")
            elif key in (ord("w"), ord("W")):
                fx_panel.hand_mode["wah"] = not fx_panel.hand_mode["wah"]
                if not fx_panel.hand_mode["wah"]:
                    fx_panel.values["wah_mix"] = 0.0
                fx_panel.dirty = True
                print(f"[WAH] Modo: {'CONTROL POR MANO (Eje Y)' if fx_panel.hand_mode['wah'] else 'SLIDER MANUAL (OFF)'}")
            elif key in (ord("e"), ord("E")):
                fx_panel.hand_mode["delay"] = not fx_panel.hand_mode["delay"]
                if not fx_panel.hand_mode["delay"]:
                    fx_panel.values["delay_wet"] = 0.0
                fx_panel.dirty = True
                print(f"[DELAY] Modo: {'CONTROL POR MANO (Profundidad Z)' if fx_panel.hand_mode['delay'] else 'SLIDER MANUAL (OFF)'}")
            elif key in (ord("m"), ord("M")):
                ambient_active = not ambient_active
                last_ambient_state = ambient_active
                target_vol = 1.0 if ambient_active else 0.0
                last_interaction_time = now_mono if ambient_active else -999.0
                udp_send_safe(sock, target, f"ambient {target_vol:.2f} 1500;\n")
                print(f"[PAISAJE DE MAR] Manual [M]: {'ACTIVADO (Fade In 1.5s)' if ambient_active else 'APAGADO (Fade Out 1.5s)'}")
            elif key in (ord("c"), ord("C")):
                last_interaction_time = -999.0
                last_ambient_state = False
                udp_send_safe(sock, target, "ambient 0.0 1200;\n")
                last_sent_channels = ""
                liquid_gen.clear()
                udp_send_safe(sock, target, "channels 0 0;\n")
                print("[SILENCIO EN PD] Todos los paisajes fueron silenciados.")
            elif key in (ord("+"), ord("="), 43, 61):
                new_scale = liquid_gen.adjust_shadow_scale(+0.10)
                print(f"[MANO] Tamaño de la mano aumentado a: {int(new_scale * 100)}%")
            elif key in (ord("-"), ord("_"), 45):
                new_scale = liquid_gen.adjust_shadow_scale(-0.10)
                print(f"[MANO] Tamaño de la mano reducido a: {int(new_scale * 100)}%")
            elif key in (ord("["), ord("{")):
                smooth_factor = max(0.0, smooth_factor - 0.05)
                print(f"[SUAVIDAD] Reducida a: {smooth_factor:.2f}")
            elif key in (ord("]"), ord("}")):
                smooth_factor = min(0.95, smooth_factor + 0.05)
                print(f"[SUAVIDAD] Incrementada a: {smooth_factor:.2f}")

    except KeyboardInterrupt:
        pass
    finally:
        udp_send_safe(sock, target, "ambient 0.0 300;\n")
        udp_send_safe(sock, target, "channels 0 0;\n")
        udp_send_safe(sock, target, "active 0;\n")
        udp_send_safe(sock, target, "state 0;\n")
        udp_send_safe(sock, target, "quit;\n")
        cam_stream.release()
        detector.close()
        sock.close()
        cv2.destroyAllWindows()
        print("Mesa Sonora cerrada.")


if __name__ == "__main__":
    main()
