"""
Point d'entrée principal.
Changer USE_MOCK = False pour passer en mode hardware réel.
"""
import time
import json
from bitalino_mock import BitalinoMock
from signal_processor import SignalProcessor

USE_MOCK = True
SAMPLING_RATE = 100  # Hz
DEVICE_ADDRESS = "XX:XX:XX:XX:XX:XX"  # à remplacer par l'adresse réelle


def run():
    processor = SignalProcessor(sampling_rate=SAMPLING_RATE)

    if USE_MOCK:
        print("[Mode simulateur] Démarrage sans hardware.")
        source = BitalinoMock(sampling_rate=SAMPLING_RATE)
        read_frame = source.read_frame
    else:
        # TODO: remplacer par le vrai lecteur Bitalino
        raise NotImplementedError("Mode hardware non encore implémenté.")

    interval = 1.0 / SAMPLING_RATE
    print(f"Acquisition à {SAMPLING_RATE} Hz. Ctrl+C pour arrêter.\n")

    try:
        while True:
            start = time.perf_counter()

            raw = read_frame()
            output = processor.process(raw)

            # Afficher seulement les événements importants pour ne pas spammer
            if output["shot_triggered"]:
                print(f"[TIR] puissance={output['shot_power']:.2f}  "
                      f"visée=({output['aim_x']:.1f}°, {output['aim_y']:.1f}°)  "
                      f"stress={output['stress_level']:.2f}")
            elif int(start) % 2 == 0:  # toutes les ~2s
                print(f"stress={output['stress_level']:.2f}  "
                      f"aim=({output['aim_x']:.1f}°, {output['aim_y']:.1f}°)  "
                      f"calibré={'oui' if output['calibrated'] else 'non'}")

            # Maintenir le rythme d'échantillonnage
            elapsed = time.perf_counter() - start
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    run()
