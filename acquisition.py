import platform
import sys
import matplotlib.pyplot as plt

sys.path.append(f"Win{platform.architecture()[0][:2]}_{''.join(platform.python_version().split('.')[:2])}")
import plux

# ── Configuration ──────────────────────────────────────────────────────
DEVICE_ADDRESS = "98:D3:91:FD:69:DD"
DURATION       = 20    # secondes
FREQUENCY      = 100   # Hz
ACTIVE_PORTS   = [1, 2]              # ports à lire (A1=1, A2=2, …)
CHANNEL_NAMES  = ["acc_x", "pzt"]   # un nom par port, dans le même ordre
WINDOW_SAMPLES = FREQUENCY * 5      # fenêtre glissante : 5 dernières secondes
# ───────────────────────────────────────────────────────────────────────


class Acquisition(plux.SignalsDev):
    def __init__(self, address):
        plux.SignalsDev.__init__(address)
        self.duration  = 0
        self.frequency = 0
        self.data = [[] for _ in ACTIVE_PORTS]

        # Graphique temps réel
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

        # Rafraîchir 10 fois par seconde
        if nSeq % (self.frequency // 10) == 0:
            for i, (line, ax) in enumerate(zip(self.lines, self.axes)):
                y = self.data[i][-WINDOW_SAMPLES:]
                line.set_data(range(len(y)), y)
                ax.relim()
                ax.autoscale_view()
            self.fig.canvas.draw()
            self.fig.canvas.flush_events()

        return nSeq > self.duration * self.frequency


def acquérir_et_afficher():
    print(f"Connexion à {DEVICE_ADDRESS}...")
    device = Acquisition(DEVICE_ADDRESS)
    device.duration  = DURATION
    device.frequency = FREQUENCY

    device.start(FREQUENCY, ACTIVE_PORTS, 16)
    print(f"Acquisition {DURATION}s sur ports {ACTIVE_PORTS}... Ctrl+C pour arrêter.")
    try:
        device.loop()
    except KeyboardInterrupt:
        pass
    device.stop()
    device.close()
    print("Terminé.")

    plt.ioff()
    plt.show()  # garde la fenêtre ouverte à la fin


if __name__ == "__main__":
    acquérir_et_afficher()
