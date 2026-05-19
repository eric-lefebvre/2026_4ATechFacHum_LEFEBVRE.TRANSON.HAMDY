import platform
import sys
import csv
from datetime import datetime
import matplotlib.pyplot as plt
from signal_processor import SignalProcessor

sys.path.append(f"Win{platform.architecture()[0][:2]}_{''.join(platform.python_version().split('.')[:2])}")
import plux

# ── Configuration ──────────────────────────────────────────────────────
DEVICE_ADDRESS = "98:D3:91:FD:69:DD"
FREQUENCY      = 100   # Hz
ACTIVE_PORTS   = [1, 2, 3, 4, 5, 6]
CHANNEL_NAMES  = ["acc_x", "acc_z", "resp", "pzt", "eda", "emg"]
WINDOW_SAMPLES = FREQUENCY * 5      # fenêtre glissante : 5 dernières secondes
# ───────────────────────────────────────────────────────────────────────


class Acquisition(plux.SignalsDev):
    def __init__(self, address):
        plux.SignalsDev.__init__(address)
        self.frequency = 0
        self.data = [[] for _ in ACTIVE_PORTS]
        self.processor = SignalProcessor(frequency=FREQUENCY)

        print("[Graphique] Ouverture de la fenêtre...")
        plt.ion()
        n = len(ACTIVE_PORTS)
        self.fig, axes = plt.subplots(n, 1, figsize=(10, 3 * n))
        self.axes  = [axes] if n == 1 else list(axes)
        self.lines = []
        for ax, name in zip(self.axes, CHANNEL_NAMES):
            line, = ax.plot([], [])
            ax.set_title(name)
            ax.set_ylabel("Valeur brute")
            self.lines.append(line)
        self.axes[-1].set_xlabel("Échantillon")
        plt.tight_layout()
        plt.show()

    def onRawFrame(self, nSeq, data):
        for i in range(len(ACTIVE_PORTS)):
            self.data[i].append(data[i])

        # Traitement du signal
        frame = {name: data[i] for i, name in enumerate(CHANNEL_NAMES)}
        result = self.processor.update(frame)
        if result:
            if result["shot_triggered"]:
                print(f"[TIR] puissance={result['shot_power']:.2f}  "
                      f"angle={result['aim_angle']:.1f}°  "
                      f"stress={result['stress']:.2f}")
            elif nSeq % (self.frequency * 2) == 0:
                print(f"[Live] stress={result['stress']:.2f}  "
                      f"FC={result['heart_rate']:.0f}bpm  "
                      f"resp={result['breath_rate']:.1f}bpm  "
                      f"angle={result['aim_angle']:.1f}°")

        # Log toutes les 10 secondes
        if nSeq % (self.frequency * 10) == 0 and nSeq > 0:
            total = nSeq + 1
            print(f"[Acquisition] {total} échantillons reçus ({total // self.frequency}s)")

        # Rafraîchir le graphique 10 fois par seconde
        if nSeq % (self.frequency // 10) == 0:
            for i, (line, ax) in enumerate(zip(self.lines, self.axes)):
                y = self.data[i][-WINDOW_SAMPLES:]
                line.set_data(range(len(y)), y)
                ax.relim()
                ax.autoscale_view()
            self.fig.canvas.draw()
            self.fig.canvas.flush_events()

        return False  # ne s'arrête jamais tout seul — Ctrl+C pour stopper


def acquérir_et_afficher():
    print(f"[Connexion] Tentative de connexion à {DEVICE_ADDRESS}...")
    try:
        device = Acquisition(DEVICE_ADDRESS)
    except RuntimeError as e:
        print(f"[Erreur] Impossible de se connecter : {e}")
        print("[Erreur] Vérifiez que le BITalino est allumé et couplé en Bluetooth.")
        return

    print(f"[Connexion] Connecté. Démarrage de l'acquisition sur ports {ACTIVE_PORTS}.")
    print("[Acquisition] Appuyez sur Ctrl+C pour arrêter.\n")

    try:
        device.start(FREQUENCY, ACTIVE_PORTS, 16)
        device.loop()
    except KeyboardInterrupt:
        print("\n[Acquisition] Arrêt demandé.")
    except Exception as e:
        print(f"\n[Erreur] Problème pendant l'acquisition : {e}")
    finally:
        device.stop()
        device.close()
        print("[Connexion] Déconnecté du BITalino.")

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

    plt.ioff()
    plt.show()


if __name__ == "__main__":
    acquérir_et_afficher()
