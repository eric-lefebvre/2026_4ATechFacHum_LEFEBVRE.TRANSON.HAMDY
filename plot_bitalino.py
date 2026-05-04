import platform
import sys
import matplotlib.pyplot as plt

sys.path.append(f"Win{platform.architecture()[0][:2]}_{''.join(platform.python_version().split('.')[:2])}")

import plux


class PlotDevice(plux.SignalsDev):
    def __init__(self, address):
        plux.SignalsDev.__init__(address)
        self.duration = 0
        self.frequency = 0
        self.nSeqs = []
        self.values = []

        plt.ion()
        self.fig, self.ax = plt.subplots()
        self.line, = self.ax.plot([], [])
        self.ax.set_xlabel("Numéro d'acquisition")
        self.ax.set_ylabel("Valeur")
        self.ax.set_title("Signal BITalino")

    def onRawFrame(self, nSeq, data):
        self.nSeqs.append(nSeq)
        self.values.append(data[0])

        if nSeq % 50 == 0:  # rafraîchit le graphique toutes les 50 trames
            self.line.set_data(self.nSeqs, self.values)
            self.ax.relim()
            self.ax.autoscale_view()
            self.fig.canvas.draw()
            self.fig.canvas.flush_events()

        return nSeq > self.duration * self.frequency


def acquisitionAvecGraphique(
    address="98:D3:91:FD:69:DD",
    duration=20,
    frequency=100,
    active_ports=[1],
):
    device = PlotDevice(address)
    device.duration = int(duration)
    device.frequency = int(frequency)
    device.start(device.frequency, active_ports, 16)
    device.loop()
    device.stop()
    device.close()

    plt.ioff()
    plt.show()


if __name__ == "__main__":
    acquisitionAvecGraphique(*sys.argv[1:])
