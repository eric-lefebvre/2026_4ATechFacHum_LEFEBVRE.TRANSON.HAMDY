"""
Traitement du signal pour le projet mini-golf.

Entrée  : trames brutes du Bitalino (entiers ADC 0–65535)
Sortie  : valeurs utilisables par le jeu Unity

    shot_triggered  bool    le joueur vient de relâcher le muscle → tir
    shot_power      0–1     force du tir (basée sur le pic EMG)
    aim_angle       degrés  angle de visée dérivé de l'accéléromètre
    stress          0–1     index de stress combiné (EDA + fréquence cardiaque)
    breath_rate     bpm     fréquence respiratoire

Fonctionnement :
    1. Les 10 premières secondes = calibration (joueur au repos, immobile)
    2. Ensuite chaque trame produit une sortie
"""

import math
from collections import deque

# ── Paramètres ─────────────────────────────────────────────────────────
FREQUENCY          = 100   # Hz — doit correspondre à acquisition.py
CALIBRATION_SEC    = 10    # secondes de repos pour établir les baselines

EMG_WINDOW_MS      = 200   # fenêtre RMS pour l'EMG (ms)
EMG_THRESHOLD_MULT = 4.0   # ratio baseline × N pour détecter une contraction

EDA_WINDOW_SEC     = 10    # fenêtre glissante pour la moyenne EDA
PZT_WINDOW_SEC     = 5     # fenêtre pour la détection de pics cardiaques
RESP_WINDOW_SEC    = 15    # fenêtre pour la fréquence respiratoire

# ── Classe principale ───────────────────────────────────────────────────

class SignalProcessor:

    def __init__(self, frequency=FREQUENCY):
        self.freq = frequency
        self.calibrated = False
        self._cal_count  = 0
        self._cal_target = frequency * CALIBRATION_SEC

        # Buffers de calibration
        self._cal_emg  = []
        self._cal_eda  = []
        self._cal_accx = []
        self._cal_accz = []

        # Baselines (remplies après calibration)
        self._emg_baseline  = 1.0
        self._eda_baseline  = 1.0
        self._acc_x_neutral = 512.0
        self._acc_z_neutral = 512.0

        # Buffer EMG (fenêtre glissante)
        self._emg_buf = deque(maxlen=int(frequency * EMG_WINDOW_MS / 1000))

        # État tir
        self._emg_contracting = False
        self._emg_peak_rms    = 0.0

        # Buffer EDA
        self._eda_buf = deque(maxlen=frequency * EDA_WINDOW_SEC)

        # Buffer et état PZT (pouls)
        self._pzt_buf        = deque(maxlen=frequency * PZT_WINDOW_SEC)
        self._pzt_prev       = 0
        self._pzt_rising     = False
        self._pzt_peaks      = deque(maxlen=20)   # timestamps des derniers pics
        self._heart_rate_bpm = 70.0               # valeur par défaut

        # Buffer et état RESP (respiration)
        self._resp_buf       = deque(maxlen=frequency * RESP_WINDOW_SEC)
        self._resp_prev      = 0
        self._resp_rising    = False
        self._resp_peaks     = deque(maxlen=10)   # timestamps des derniers cycles
        self._breath_rate    = 15.0               # valeur par défaut (bpm)

        # Compteur global de trames (pour horodatage interne)
        self._frame_count = 0

    # ───────────────────────────────────────────────────────────────────
    def update(self, frame: dict) -> dict | None:
        """
        Appeler à chaque trame reçue du Bitalino.
        Retourne None pendant la calibration, puis un dict de valeurs.

        frame doit contenir les clés :
            acc_x, acc_z, resp, pzt, eda, emg
        """
        self._frame_count += 1

        if not self.calibrated:
            self._run_calibration(frame)
            return None      # pas encore de sortie pendant la calibration

        shot_triggered, shot_power = self._process_emg(frame["emg"])
        aim_angle                  = self._process_acc(frame["acc_x"], frame["acc_z"])
        heart_rate                 = self._process_pzt(frame["pzt"])
        breath_rate                = self._process_resp(frame["resp"])
        stress                     = self._process_stress(frame["eda"], heart_rate)

        return {
            "shot_triggered": shot_triggered,
            "shot_power":     round(shot_power, 3),
            "aim_angle":      round(aim_angle, 1),
            "stress":         round(stress, 3),
            "heart_rate":     round(heart_rate, 1),
            "breath_rate":    round(breath_rate, 1),
        }

    # ── Calibration ─────────────────────────────────────────────────────
    def _run_calibration(self, frame):
        self._cal_emg.append(frame["emg"])
        self._cal_eda.append(frame["eda"])
        self._cal_accx.append(frame["acc_x"])
        self._cal_accz.append(frame["acc_z"])
        self._cal_count += 1

        if self._cal_count >= self._cal_target:
            self._emg_baseline  = _rms(self._cal_emg) or 1.0
            self._eda_baseline  = _mean(self._cal_eda) or 1.0
            self._acc_x_neutral = _mean(self._cal_accx)
            self._acc_z_neutral = _mean(self._cal_accz)
            self.calibrated = True
            print(
                f"[Calibration OK] "
                f"EMG baseline RMS={self._emg_baseline:.1f}  "
                f"EDA baseline={self._eda_baseline:.1f}  "
                f"ACC neutre=({self._acc_x_neutral:.0f}, {self._acc_z_neutral:.0f})"
            )

    # ── EMG → tir ───────────────────────────────────────────────────────
    def _process_emg(self, raw):
        self._emg_buf.append(raw)
        rms = _rms(self._emg_buf)
        threshold = self._emg_baseline * EMG_THRESHOLD_MULT

        shot_triggered = False
        shot_power     = 0.0

        if rms > threshold:
            # Muscle contracté : on mémorise le pic
            self._emg_peak_rms    = max(self._emg_peak_rms, rms)
            self._emg_contracting = True
        elif self._emg_contracting:
            # Muscle relâché → tir !
            shot_triggered = True
            # Normalise : 0 = juste au-dessus du seuil, 1 = 10× la baseline
            shot_power = min(1.0, (self._emg_peak_rms - threshold) /
                            (self._emg_baseline * 6.0))
            self._emg_peak_rms    = 0.0
            self._emg_contracting = False

        return shot_triggered, shot_power

    # ── ACC → angle de visée ─────────────────────────────────────────────
    def _process_acc(self, raw_x, raw_z):
        # Décalage par rapport à la position neutre calibrée
        dx = raw_x - self._acc_x_neutral
        dz = raw_z - self._acc_z_neutral
        # Angle en degrés (0° = position neutre)
        angle = math.degrees(math.atan2(dx, dz))
        return angle

    # ── PZT → fréquence cardiaque ────────────────────────────────────────
    def _process_pzt(self, raw):
        self._pzt_buf.append(raw)

        # Détection de pic : on cherche un passage par un maximum local
        # Un pic = la valeur dépasse la moyenne + 30 % de la plage
        if len(self._pzt_buf) < 10:
            return self._heart_rate_bpm

        buf_list = list(self._pzt_buf)
        mean_pzt = _mean(buf_list)
        amp_pzt  = max(buf_list) - min(buf_list)
        peak_threshold = mean_pzt + 0.3 * amp_pzt

        # Détection front montant → descendant (pic)
        if raw > peak_threshold and not self._pzt_rising:
            self._pzt_rising = True
        elif raw < peak_threshold and self._pzt_rising:
            # On vient de passer le pic
            self._pzt_rising = False
            t = self._frame_count / self.freq    # timestamp en secondes

            if self._pzt_peaks:
                interval = t - self._pzt_peaks[-1]
                # Intervalle physiologique valide : 0.4 s – 1.5 s (40–150 bpm)
                if 0.4 < interval < 1.5:
                    self._pzt_peaks.append(t)
                    if len(self._pzt_peaks) >= 2:
                        intervals = [self._pzt_peaks[i+1] - self._pzt_peaks[i]
                                     for i in range(len(self._pzt_peaks)-1)]
                        self._heart_rate_bpm = 60.0 / _mean(intervals)
            else:
                self._pzt_peaks.append(t)

        return self._heart_rate_bpm

    # ── RESP → fréquence respiratoire ────────────────────────────────────
    def _process_resp(self, raw):
        self._resp_buf.append(raw)

        if len(self._resp_buf) < 20:
            return self._breath_rate

        buf_list = list(self._resp_buf)
        mean_resp = _mean(buf_list)
        amp_resp  = max(buf_list) - min(buf_list)
        threshold = mean_resp + 0.2 * amp_resp

        if raw > threshold and not self._resp_rising:
            self._resp_rising = True
        elif raw < threshold and self._resp_rising:
            self._resp_rising = False
            t = self._frame_count / self.freq

            if self._resp_peaks:
                interval = t - self._resp_peaks[-1]
                # Intervalle respiratoire valide : 2 s – 10 s (6–30 bpm)
                if 2.0 < interval < 10.0:
                    self._resp_peaks.append(t)
                    if len(self._resp_peaks) >= 2:
                        intervals = [self._resp_peaks[i+1] - self._resp_peaks[i]
                                     for i in range(len(self._resp_peaks)-1)]
                        self._breath_rate = 60.0 / _mean(intervals)
            else:
                self._resp_peaks.append(t)

        return self._breath_rate

    # ── Stress combiné ───────────────────────────────────────────────────
    def _process_stress(self, raw_eda, heart_rate):
        self._eda_buf.append(raw_eda)

        # Composante EDA : variation relative par rapport à la baseline
        mean_eda = _mean(self._eda_buf)
        if self._eda_baseline > 1:
            eda_stress = min(1.0, max(0.0,
                (mean_eda - self._eda_baseline) / self._eda_baseline))
        else:
            eda_stress = 0.0   # EDA non disponible

        # Composante fréquence cardiaque
        # Repos ~60–70 bpm → stress 0 ; > 100 bpm → stress 1
        hr_stress = min(1.0, max(0.0, (heart_rate - 65) / 40.0))

        # Combinaison pondérée (60 % HR, 40 % EDA)
        stress = 0.6 * hr_stress + 0.4 * eda_stress
        return stress


# ── Fonctions utilitaires ───────────────────────────────────────────────

def _rms(values) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))

def _mean(values) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
