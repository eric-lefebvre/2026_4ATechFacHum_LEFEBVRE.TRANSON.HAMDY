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

    def onRawFrame(self, nSeq, data):
        self.nSeqs.append(nSeq)
        self.values.append(data[0])
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

    plt.plot(device.nSeqs, device.values)
    plt.xlabel("Numéro d'acquisition")
    plt.ylabel("Valeur")
    plt.title("Signal BITalino")
    plt.show()


if __name__ == "__main__":
    acquisitionAvecGraphique(*sys.argv[1:])
