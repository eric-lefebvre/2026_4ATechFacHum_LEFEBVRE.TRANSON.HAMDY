"""
Version test — fonctionne avec n'importe quel sous-ensemble de capteurs.
Pas de calcul de stress. Chaque capteur produit uniquement ses métriques propres.

Sorties selon les capteurs branchés :
    ppg   → heart_rate (bpm), heart_rate_variability (ms RMSSD)
    resp  → breath_rate (bpm), breath_amp_min, breath_amp_max
    eda   → eda_level (moyenne glissante 10s)
    acc_x + acc_z (les deux requis) → aim_angle (degrés)
    emg   → shot_triggered (bool), shot_power (0–1)

Pour changer les capteurs branchés, modifier ACTIVE_PORTS et CHANNEL_NAMES.
Ports disponibles : A1=acc_x  A2=acc_z  A3=resp  A4=ppg  A5=eda  A6=emg
"""

import math
import platform
import sys
import csv
import signal
import threading
from collections import deque
from datetime import datetime
import matplotlib.pyplot as plt
from websocket_bridge import WebSocketBridge

sys.path.append(f"Win{platform.architecture()[0][:2]}_{''.join(platform.python_version().split('.')[:2])}")
import plux

# ── Configuration ──────────────────────────────────────────────────────
DEVICE_ADDRESS  = "98:D3:91:FD:69:DD"
FREQUENCY       = 100    # Hz
CALIBRATION_SEC = 30     # secondes de repos pour mesurer les baselines

# ← Modifier ici selon les capteurs branchés (même ordre port / nom)
ACTIVE_PORTS  = [1]
CHANNEL_NAMES = ["emg"]

WINDOW_SAMPLES = FREQUENCY * 5
PLOT_INTERVAL  = 0.2
# ───────────────────────────────────────────────────────────────────────


class PeakTracker:
    """Détecte les pics dans un signal glissant.
    Pour PPG : calcule heart_rate et heart_rate_variability.
    Pour RESP : calcule breath_rate, breath_amp_min, breath_amp_max.
    """

    def __init__(self, freq, refractory_sec, min_interval, max_interval):
        self.freq             = freq
        self._buf             = deque(maxlen=freq * 15)
        self._rising          = False
        self._peaks_t         = deque(maxlen=20)
        self._peaks_amp       = deque(maxlen=20)
        self._rr_intervals    = deque(maxlen=20)
        self._last_peak_frame = 0
        self._frame           = 0
        self._refractory      = int(freq * refractory_sec)
        self._min_interval    = min_interval
        self._max_interval    = max_interval
        self._cal_amp         = 0.0

        # Métriques publiques
        self.rate    = 0.0
        self.amp_min = 0.0
        self.amp_max = 0.0

    def set_cal_amp(self, amp):
        self._cal_amp = amp

    @property
    def hrv_ms(self) -> float:
        rr = list(self._rr_intervals)
        if len(rr) < 2:
            return 0.0
        diffs = [rr[i+1] - rr[i] for i in range(len(rr)-1)]
        return math.sqrt(sum(d*d for d in diffs) / len(diffs)) * 1000

    def update(self, raw):
        self._frame += 1
        self._buf.append(raw)

        if len(self._buf) < 20:
            return

        buf_sorted = sorted(self._buf)
        n          = len(buf_sorted)
        median     = buf_sorted[n // 2]
        amp        = buf_sorted[int(n * 0.9)] - buf_sorted[int(n * 0.1)]
        threshold  = median + 0.3 * amp

        if raw > threshold and not self._rising:
            self._rising = True
        elif raw < threshold and self._rising:
            self._rising = False
            if self._frame - self._last_peak_frame < self._refractory:
                return
            self._last_peak_frame = self._frame
            t = self._frame / self.freq

            if self._peaks_t:
                interval = t - self._peaks_t[-1]
                if self._min_interval < interval < self._max_interval:
                    self._peaks_t.append(t)
                    self._peaks_amp.append(amp)
                    self._rr_intervals.append(interval)
                    intervals = [self._peaks_t[i+1] - self._peaks_t[i]
                                 for i in range(len(self._peaks_t)-1)]
                    self.rate = 60.0 / (sum(intervals) / len(intervals))
                    # amp min/max
                    self.amp_max = max(self.amp_max, amp)
                    self.amp_min = amp if self.amp_min == 0.0 \
                                   else min(self.amp_min, amp)
            else:
                self._peaks_t.append(t)
                self._peaks_amp.append(amp)


_TRACKER_PARAMS = {
    "ppg":  {"refractory_sec": 0.35, "min_interval": 0.4,  "max_interval": 1.5},
    "resp": {"refractory_sec": 2.0,  "min_interval": 2.0,  "max_interval": 10.0},
}


class SimpleProcessor:
    """Calibration + métriques temps réel par capteur. Pas de calcul de stress."""

    def __init__(self, channel_names, frequency, calibration_sec):
        self.channels    = channel_names
        self.freq        = frequency
        self._cal_sec    = calibration_sec
        self._cal_target = frequency * calibration_sec
        self._cal_count  = 0
        self._cal_data   = {ch: [] for ch in channel_names}
        self._baselines  = {}
        self.calibrated  = False

        # Trackers pics (PPG et RESP)
        self._trackers = {
            ch: PeakTracker(frequency, **_TRACKER_PARAMS[ch])
            for ch in channel_names if ch in _TRACKER_PARAMS
        }

        # Buffer EDA
        self._eda_buf = deque(maxlen=frequency * 10) if "eda" in channel_names else None

        # EMG : seuil et état
        self._emg_threshold         = 0.0   # calculé à la fin de la calibration
        self._emg_release_threshold = 0.0
        self._emg_contracting       = False
        self._emg_below_frames      = 0
        self._emg_refractory        = 0

    # ── Mise à jour trame par trame ──────────────────────────────────────
    def update(self, frame: dict) -> dict | None:
        self._cal_count += 1
        if not self.calibrated:
            return self._calibrate(frame)

        out = {"type": "data"}

        if "ppg" in self.channels:
            self._trackers["ppg"].update(frame["ppg"])
            out["heart_rate"]             = round(self._trackers["ppg"].rate, 1)
            out["heart_rate_variability"] = round(self._trackers["ppg"].hrv_ms, 1)

        if "resp" in self.channels:
            self._trackers["resp"].update(frame["resp"])
            out["breath_rate"]    = round(self._trackers["resp"].rate, 1)
            out["breath_amp_min"] = round(self._trackers["resp"].amp_min, 1)
            out["breath_amp_max"] = round(self._trackers["resp"].amp_max, 1)

        if "eda" in self.channels:
            self._eda_buf.append(frame["eda"])
            out["eda_level"] = round(sum(self._eda_buf) / len(self._eda_buf), 1)

        if "acc_x" in self.channels and "acc_z" in self.channels:
            dx = frame["acc_x"] - self._baselines.get("acc_x", 512.0)
            dz = frame["acc_z"] - self._baselines.get("acc_z", 512.0)
            out["aim_angle"] = round(math.degrees(math.atan2(dx, dz)), 1)

        if "emg" in self.channels:
            shot_start, shot_end = self._process_emg(frame["emg"])
            out["shot_start"] = shot_start
            out["shot_end"]   = shot_end

        return out

    # ── Calibration ──────────────────────────────────────────────────────
    def _calibrate(self, frame) -> dict | None:
        for ch in self.channels:
            self._cal_data[ch].append(frame[ch])
        for ch, tracker in self._trackers.items():
            tracker.update(frame[ch])

        if self._cal_count % self.freq != 0:
            return None

        elapsed  = self._cal_count // self.freq
        progress = self._cal_count / self._cal_target

        if self._cal_count >= self._cal_target:
            # Baselines neutres pour ACC
            for ch in ("acc_x", "acc_z"):
                if ch in self.channels:
                    vals = self._cal_data[ch]
                    self._baselines[ch] = sum(vals) / len(vals)

            # Seuil EMG : mean + 8 * std
            if "emg" in self.channels:
                vals = self._cal_data["emg"]
                emg_mean = sum(vals) / len(vals)
                emg_std  = math.sqrt(sum((v - emg_mean)**2 for v in vals) / len(vals))
                self._emg_threshold         = emg_mean + 20 * emg_std
                self._emg_release_threshold = emg_mean + 0.25 * 20 * emg_std
                print(f"[Calibration OK] emg: seuil={self._emg_threshold:.0f} (moy={emg_mean:.0f}, std={emg_std:.1f})")

            # Amplitude de référence pour les trackers
            for ch, tracker in self._trackers.items():
                vals = sorted(self._cal_data[ch])
                n    = len(vals)
                amp  = vals[int(n * 0.9)] - vals[int(n * 0.1)]
                tracker.set_cal_amp(amp)

            self.calibrated = True

            baselines_out = {}
            for ch in self.channels:
                vals = sorted(self._cal_data[ch])
                n    = len(vals)
                baselines_out[ch] = {
                    "mean": round(sum(self._cal_data[ch]) / n, 1),
                    "amp":  round(vals[int(n * 0.9)] - vals[int(n * 0.1)], 1),
                    "rate": round(self._trackers[ch].rate, 1) if ch in self._trackers else 0.0,
                }
                print(f"[Calibration OK] {ch}: {baselines_out[ch]}")

            return {"type": "calibration_complete", "baselines": baselines_out}

        print(f"[Calibration] {elapsed}s / {self._cal_sec}s  ({int(progress * 100)}%)")
        return {
            "type":        "calibration_progress",
            "progress":    round(progress, 2),
            "elapsed_sec": elapsed,
            "total_sec":   self._cal_sec,
        }

    # ── EMG → tir ────────────────────────────────────────────────────────
    def _process_emg(self, raw) -> tuple[bool, bool]:
        if self._emg_refractory > 0:
            self._emg_refractory -= 1
            return False, False

        shot_start = False
        shot_end   = False

        if raw > self._emg_threshold:
            if not self._emg_contracting:
                shot_start = True
            self._emg_contracting  = True
            self._emg_below_frames = 0
        elif self._emg_contracting and raw < self._emg_release_threshold:
            self._emg_below_frames += 1
            if self._emg_below_frames >= 20:   # 0.2s à 100Hz
                self._emg_contracting  = False
                self._emg_below_frames = 0
                self._emg_refractory   = 100   # 1s à 100Hz
                shot_end = True

        return shot_start, shot_end


# ── Classe Acquisition PLUX ─────────────────────────────────────────────

class Acquisition(plux.SignalsDev):

    def __init__(self, address, bridge: WebSocketBridge = None):
        plux.SignalsDev.__init__(address)
        self.frequency = FREQUENCY
        self.data      = [[] for _ in ACTIVE_PORTS]
        self.processor = SimpleProcessor(CHANNEL_NAMES, FREQUENCY, CALIBRATION_SEC)
        self.bridge    = bridge
        self.running   = True

    def onRawFrame(self, nSeq, data):
        for i in range(len(ACTIVE_PORTS)):
            self.data[i].append(data[i])

        frame  = {name: data[i] for i, name in enumerate(CHANNEL_NAMES)}
        result = self.processor.update(frame)

        if result is None:
            return not self.running

        if self.bridge:
            self.bridge.send(result)

        if result.get("type") == "data":
            if result.get("shot_start"):
                print("[TIR DEBUT]")
            elif result.get("shot_end"):
                print("[TIR FIN]")
            elif nSeq % (self.frequency * 2) == 0:
                parts = []
                for key, val in result.items():
                    if key in ("type", "shot_start", "shot_end"):
                        continue
                    parts.append(f"{key}={val}")
                print(f"[Live] {'  '.join(parts)}")

        return not self.running


# ── Point d'entrée ──────────────────────────────────────────────────────

def acquérir_et_afficher():
    bridge = WebSocketBridge()
    bridge.start()

    print(f"[Connexion] Tentative de connexion à {DEVICE_ADDRESS}...")
    try:
        device = Acquisition(DEVICE_ADDRESS, bridge=bridge)
    except RuntimeError as e:
        print(f"[Erreur] Impossible de se connecter : {e}")
        print("[Erreur] Vérifiez que le BITalino est allumé et couplé en Bluetooth.")
        return

    print(f"[Connexion] Connecté. Démarrage sur ports {ACTIVE_PORTS} ({CHANNEL_NAMES}).")
    print("[Acquisition] Appuyez sur Ctrl+C pour arrêter.\n")

    n = len(ACTIVE_PORTS)
    fig, axes = plt.subplots(n, 1, figsize=(10, 3 * n))
    axes  = [axes] if n == 1 else list(axes)
    lines = []
    for ax, name in zip(axes, CHANNEL_NAMES):
        line, = ax.plot([], [])
        ax.set_title(name)
        ax.set_ylabel("Valeur brute")
        lines.append(line)
    axes[-1].set_xlabel("Échantillon")
    plt.tight_layout()
    plt.ion()
    plt.show()

    def run_acquisition():
        try:
            device.start(FREQUENCY, ACTIVE_PORTS, 16)
            device.loop()
        except Exception as e:
            if device.running:
                print(f"\n[Erreur] {e}")
        finally:
            try:
                device.stop()
                device.close()
            except Exception:
                pass
            print("[Connexion] Déconnecté du BITalino.")

    acq_thread = threading.Thread(target=run_acquisition, daemon=True)
    acq_thread.start()

    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())

    while acq_thread.is_alive() and not stop_event.is_set():
        for i, (line, ax) in enumerate(zip(lines, axes)):
            y = device.data[i][-WINDOW_SAMPLES:]
            line.set_data(range(len(y)), y)
            ax.relim()
            ax.autoscale_view()
        fig.canvas.draw()
        fig.canvas.flush_events()
        stop_event.wait(PLOT_INTERVAL)

    if stop_event.is_set():
        print("\n[Acquisition] Arrêt demandé.")
        device.running = False
        acq_thread.join(timeout=3)

    n_samples = len(device.data[0])
    if n_samples == 0:
        print("[Export] Aucune donnée reçue, pas de fichier créé.")
        return

    print(f"[Export] {n_samples} échantillons ({n_samples // FREQUENCY}s) — sauvegarde en cours...")
    filename = f"data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["index"] + CHANNEL_NAMES)
        for i, row in enumerate(zip(*device.data), start=1):
            writer.writerow([i] + list(row))
    print(f"[Export] Fichier créé : {filename}")

    bridge.stop()
    plt.ioff()
    plt.show()


if __name__ == "__main__":
    acquérir_et_afficher()
