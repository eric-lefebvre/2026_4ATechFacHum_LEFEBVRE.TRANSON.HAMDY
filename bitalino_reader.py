"""
Lecture des capteurs Bitalino via l'API PLUX.

BRANCHEMENT PHYSIQUE (à adapter selon ce que tu vois sur la carte) :
┌─────────────┬────────┬─────────────────────────────────────┐
│ Capteur     │ Port   │ Slot sur la carte                   │
├─────────────┼────────┼─────────────────────────────────────┤
│ EMG         │ A1 → 1 │ Slot "EMG"                          │
│ EDA         │ A2 → 2 │ Slot "EDA"                          │
│ RESP        │ A3 → 3 │ Slot libre (capteur respiration)    │
│ PZT         │ A4 → 4 │ Slot libre (capteur piézo)          │
│ ACC axe X   │ A5 → 5 │ Slot "ACC" (donne 3 canaux)        │
│ ACC axe Y   │ A6 → 6 │ (suite ACC)                         │
│ ACC axe Z   │ A7 → 7 │ (suite ACC) — si dispo              │
└─────────────┴────────┴─────────────────────────────────────┘

Si tu ne sais pas quel port est quoi : lance d'abord test_ports() pour
voir ce que chaque port renvoie en temps réel, puis ajuste PORT_CONFIG.
"""

import os
import sys
import platform
import time

# ── Chargement de l'API PLUX ──────────────────────────────────────────
_os_map = {
    "Darwin": f"MacOS/Intel{''.join(platform.python_version().split('.')[:2])}",
    "Linux":  "Linux64",
    "Windows": f"Win{platform.architecture()[0][:2]}_{''.join(platform.python_version().split('.')[:2])}",
}
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(_script_dir, _os_map[platform.system()]))
import plux


# ═══════════════════════════════════════════════════════════════════════
#  CONFIGURATION — modifie ici selon ton branchement physique
# ═══════════════════════════════════════════════════════════════════════

DEVICE_ADDRESS = "XX:XX:XX:XX:XX:XX"   # ← adresse Bluetooth de ta carte
SAMPLING_RATE  = 100                    # Hz (100 = bon compromis)
RESOLUTION     = 16                     # bits

# Numéros de ports actifs à lire (A1=1, A2=2, …)
ACTIVE_PORTS = [1, 2, 3, 4, 5, 6]

# Correspondance index dans data[] → nom du signal
# data[0] = premier port de ACTIVE_PORTS, data[1] = deuxième, etc.
CHANNEL_MAP = {
    0: "emg",      # data[0] → port A1
    1: "eda",      # data[1] → port A2
    2: "resp",     # data[2] → port A3
    3: "pzt",      # data[3] → port A4
    4: "acc_x",    # data[4] → port A5
    5: "acc_y",    # data[5] → port A6
    # 6: "acc_z",  # décommenter si tu as un 7e port disponible
}


# ═══════════════════════════════════════════════════════════════════════
#  Classe principale
# ═══════════════════════════════════════════════════════════════════════

class BitalinoReader(plux.SignalsDev):
    """
    Lit les capteurs Bitalino et appelle on_frame(frame_dict) pour
    chaque nouvelle trame reçue.

    Utilisation :
        reader = BitalinoReader(address=DEVICE_ADDRESS, on_frame=ma_fonction)
        reader.start_acquisition(duration=30)   # 30 secondes
    """

    def __init__(self, address: str, on_frame=None):
        """
        address  : adresse Bluetooth de la carte (ex: "98:D3:91:FD:69:DD")
        on_frame : fonction appelée à chaque trame, reçoit un dict de signaux
        """
        plux.SignalsDev.__init__(address)
        self.on_frame = on_frame or self._default_print
        self._duration  = 0
        self._frequency = SAMPLING_RATE
        self._start_time = None

    # ── Callback appelé automatiquement par l'API pour chaque trame ───
    def onRawFrame(self, nSeq, data):
        """
        nSeq : numéro de séquence de la trame (commence à 0)
        data : tuple de valeurs brutes, une par port actif
        """
        if self._start_time is None:
            self._start_time = time.time()

        timestamp = time.time() - self._start_time

        # Construire un dict lisible à partir de data[]
        frame = {"timestamp": timestamp, "nSeq": nSeq}
        for idx, name in CHANNEL_MAP.items():
            if idx < len(data):
                frame[name] = data[idx]

        # Appeler la fonction utilisateur
        self.on_frame(frame)

        # Retourner True arrête l'acquisition
        return nSeq >= self._duration * self._frequency

    # ── Lancement de l'acquisition ────────────────────────────────────
    def start_acquisition(self, duration: int = 60):
        """
        Lance l'acquisition pendant `duration` secondes.
        Bloquant — revient quand la durée est écoulée ou Ctrl+C.
        """
        self._duration = duration
        self._start_time = None

        print(f"Connexion à {DEVICE_ADDRESS}...")
        print(f"Capteurs actifs : {list(CHANNEL_MAP.values())}")
        print(f"Fréquence : {SAMPLING_RATE} Hz  |  Durée : {duration}s")
        print("Ctrl+C pour arrêter.\n")

        try:
            self.start(SAMPLING_RATE, ACTIVE_PORTS, RESOLUTION)
            self.loop()
        except KeyboardInterrupt:
            print("\nArrêt manuel.")
        finally:
            self.stop()
            self.close()
            print("Connexion fermée.")

    # ── Callback par défaut : affiche tout ────────────────────────────
    @staticmethod
    def _default_print(frame):
        vals = "  ".join(
            f"{k}={v:.1f}" if isinstance(v, float) else f"{k}={v}"
            for k, v in frame.items()
            if k not in ("nSeq",)
        )
        print(vals)


# ═══════════════════════════════════════════════════════════════════════
#  Outil de diagnostic : voir tous les ports en brut
# ═══════════════════════════════════════════════════════════════════════

class PortTester(plux.SignalsDev):
    """
    Affiche les valeurs brutes de tous les ports pour identifier
    quel capteur est branché où.
    Lance avec : test_ports()
    """

    def __init__(self, address):
        plux.SignalsDev.__init__(address)
        self._count = 0

    def onRawFrame(self, nSeq, data):
        if nSeq % 50 == 0:   # afficher toutes les 0.5s
            line = "  ".join(f"A{i+1}={data[i]:5d}" for i in range(len(data)))
            print(f"[{nSeq:06d}]  {line}")
        self._count += 1
        return nSeq > 500    # arrêt après 5s

    def run(self):
        print("=== TEST DES PORTS (5 secondes) ===")
        print("Bouge chaque capteur pour voir quel canal réagit.\n")
        self.start(SAMPLING_RATE, ACTIVE_PORTS, RESOLUTION)
        self.loop()
        self.stop()
        self.close()


def test_ports(address: str = DEVICE_ADDRESS):
    """Lance un test de 5 secondes pour identifier tes capteurs."""
    tester = PortTester(address)
    tester.run()


# ═══════════════════════════════════════════════════════════════════════
#  Test rapide en standalone
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # python bitalino_reader.py test
        test_ports()
    else:
        # python bitalino_reader.py
        def afficher(frame):
            if int(frame["timestamp"]) % 2 == 0 and frame["nSeq"] % 100 == 0:
                print(frame)

        reader = BitalinoReader(address=DEVICE_ADDRESS, on_frame=afficher)
        reader.start_acquisition(duration=30)
