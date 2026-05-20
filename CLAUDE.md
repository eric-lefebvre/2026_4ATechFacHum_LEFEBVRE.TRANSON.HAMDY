# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projet

Jeu de mini-golf adaptatif : les capteurs physiologiques BITalino contrôlent le jeu Unity en temps réel.

- **ACC** → angle de visée
- **EMG** → déclenchement et puissance du tir
- **EDA + PZT** → score de stress
- **RESP + PZT** → fréquences respiratoire et cardiaque

## Lancer le programme

```powershell
# Activer l'environnement virtuel
.\mon_env\Scripts\Activate.ps1

# Lancer l'acquisition complète (graphique + WebSocket + CSV)
python acquisition.py
```

Arrêt propre : **Ctrl+C** (intercepté via `signal.signal`, pas via Tkinter).

## Dépendances

```powershell
pip install matplotlib websockets
```

Le module `plux` est un binaire C précompilé dans `Win64_313/plux.pyd` — il n'est pas sur PyPI. Il faut Python **3.13 64-bit** sur Windows.

## Matériel

- **Adresse Bluetooth** : `98:D3:91:FD:69:DD` (dans `acquisition.py`)
- **Mapping des ports** (A1–A6) :

| Port | Constante `ACTIVE_PORTS` | Canal `CHANNEL_NAMES` | Capteur |
|------|--------------------------|------------------------|---------|
| A1   | 1 | `acc_x`  | Accéléromètre axe X |
| A2   | 2 | `acc_z`  | Accéléromètre axe Z |
| A3   | 3 | `resp`   | Ceinture respiratoire |
| A4   | 4 | `pzt`    | Capteur piézoélectrique (pouls) |
| A5   | 5 | `eda`    | Conductance cutanée |
| A6   | 6 | `emg`    | Électromyogramme |

## Architecture

```
acquisition.py          ← point d'entrée, threading, graphique, CSV
signal_processor.py     ← traitement signal pur (pas de I/O)
websocket_bridge.py     ← serveur WebSocket asyncio → Unity
Win64_313/plux.pyd      ← extension C PLUX (ne pas modifier)
OneBITalinoAcquisitionExample.py  ← exemple de référence PLUX
```

### Threading

- **Thread principal** : boucle matplotlib (`plt.ion()` + `stop_event.wait(0.2s)`)
- **Thread daemon** : `device.start()` + `device.loop()` (bloque sur le callback PLUX)
- **Thread daemon** : boucle asyncio du WebSocket (`WebSocketBridge`)
- `signal.signal(SIGINT)` positionne un `threading.Event` → arrêt propre sans crash Tkinter

### Pipeline de données (par trame à 100 Hz)

```
onRawFrame(nSeq, data)
  └─ SignalProcessor.update(frame)
       ├─ Calibration 30s : calcule les baselines individuelles
       │     _process_pzt / _process_resp tournent mais ne renvoient rien à Unity
       └─ Après calibration : renvoie un dict "data" à chaque trame
             _process_emg  → shot_triggered, shot_power
             _process_acc  → aim_angle
             _process_pzt  → heart_rate
             _process_resp → breath_rate
             _process_stress(eda, hr) → stress [0–1]
```

### Messages WebSocket vers Unity

Trois types de messages JSON :

| `type` | Quand | Champs clés |
|--------|-------|-------------|
| `calibration_progress` | 1×/s pendant 30s | `progress`, `elapsed_sec`, `total_sec` |
| `calibration_complete` | 1× à la fin | `hr_rest`, `hr_label`, `resp_rest`, `resp_label`, `eda_baseline` |
| `data` | Chaque trame (100 Hz, limité à 10 Hz côté bridge) | `shot_triggered`, `shot_power`, `aim_angle`, `stress`, `heart_rate`, `breath_rate` |

## Quirks PLUX API

- `plux.SignalsDev.__init__(address)` — l'adresse est un **argument positionnel uniquement** (extension C, pas de kwargs).
  ```python
  plux.SignalsDev.__init__(address)   # ✓
  plux.SignalsDev.__init__(self=..., address=...)  # ✗ TypeError
  ```
- `device.start(frequency, active_ports, 16)` — le `16` est la résolution en bits.
- `onRawFrame` doit retourner `True` pour stopper la boucle → `return not self.running`.
- `self.frequency` doit être affecté **dans `__init__`** avant tout usage, sinon vaut 0 et cause un `ZeroDivisionError`.

## Algorithmes de détection de pics (PZT / RESP)

Détection par seuil adaptatif sur fenêtre glissante :

```python
amp = buf_sorted[int(n * 0.9)] - buf_sorted[int(n * 0.1)]   # robuste aux outliers
threshold = median + 0.4 * amp   # PZT : 0.4 / RESP : 0.3
```

Période réfractaire : 0.35s pour PZT, 2.0s pour RESP (évite les double-détections).  
Filtre d'intervalle : `0.4s < intervalle < 1.5s` (PZT) / `2.0s < intervalle < 10.0s` (RESP).

## Debug signal

Des logs de diagnostic sont activables dans `signal_processor.py` :

```python
# Dans update() après calibration :
debug_pzt  = (self._frame_count % 50 == 0)
debug_resp = (self._frame_count % 50 == 0)
```

Les lignes `[PZT]` et `[RESP]` affichent `raw`, `median`, `amp`, `threshold`, `rising` — utiles pour diagnostiquer un capteur non branché (amp ≈ 0) ou un seuil trop élevé.

## Valeurs brutes typiques par capteur

| Capteur | Valeurs typiques | Amplitude attendue |
|---------|-----------------|-------------------|
| ACC X/Z | 400–600 | ~100 selon inclinaison |
| RESP    | variable | peaks visibles sur 15s |
| PZT     | 400–600 | pics à ~60/min |
| EDA     | 100–800 | lente dérive |
| EMG     | bruit ~50, contraction >200 | |
