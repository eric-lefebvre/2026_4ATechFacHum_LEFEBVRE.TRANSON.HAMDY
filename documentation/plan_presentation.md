# Plan de présentation — Mini-Golf Adaptatif par Biofeedback
## 12 minutes · 17 slides

---

## SLIDE 1 — Titre
**Titre :** Mini-Golf Adaptatif par Biofeedback Physiologique
**Sous-titre :** Mesure et induction du *flow* en temps réel
**Auteurs :** Transon Paul · Hamdy Maya · Lefebvre Eric
**ENSIM Le Mans — 2026**

> *Visuel suggéré : screenshot du jeu Unity ou photo du setup capteurs*

---

## SLIDE 2 — Accroche (1 min)
**Titre :** Et si le jeu s'adaptait à votre état mental ?

- Les interfaces classiques ignorent l'état du joueur
- Trop difficile → frustration | Trop facile → ennui
- **Notre idée :** mesurer le stress en temps réel et adapter le jeu en conséquence
- Terrain de jeu : le mini-golf → geste précis, objectif clair, mesurable par EMG

> *Visuel : schéma simple Joueur → Capteurs → Jeu*
> *À l'oral : "On s'est demandé : est-ce qu'on peut rendre un jeu intelligent en lui donnant accès à la physiologie du joueur ?"*

---

## SLIDE 3 — Le Flow (1 min 30)
**Titre :** Le concept de *flow* (Csikszentmihalyi, 1990)

- État de **concentration optimale** : absorption totale, automaticité, distorsion du temps
- 3 conditions nécessaires :
  - **Challenge-Skill Balance** : difficulté ≈ niveau du joueur
  - **Clear Goals** : objectif toujours visible
  - **Unambiguous Feedback** : retour immédiat sur la réussite

> *Visuel : schéma classique du flow (axe compétence / axe difficulté, zone de flow entre ennui et anxiété)*
> *À l'oral : "Notre rôle côté système, c'est de maintenir le joueur dans cette zone orange — ni trop facile, ni trop dur."*

---

## SLIDE 4 — Corrélats physiologiques (1 min)
**Titre :** Le corps parle : signature du *flow*

| Capteur | Ennui | **Flow** | Stress |
|---------|-------|----------|--------|
| EDA | bas | modéré, stable | élevé + SCR |
| FC | basse | intermédiaire | élevée |
| HRV | élevée | stable | basse |
| ACC (tremblement) | variable | faible, stable | élevé |

- EDA = arousal sympathique (conductance cutanée)
- HRV = variabilité cardiaque, reflet de la charge cognitive
- ACC = en état de flow, la motricité est contrôlée → moins de tremblement
- ⚠️ L'EMG n'est **pas** un indicateur de flow : c'est uniquement le mécanisme de tir (comme un bouton)

> *À l'oral : "Ces différences sont mesurables en temps réel — c'est ce qui rend le projet faisable."*

---

## SLIDE 5 — Architecture du système (1 min)
**Titre :** Vue d'ensemble

```
[BITalino BT] → acquisition.py → signal_processor.py → websocket_bridge.py → [Unity]
```

- **BITalino Core BT** : carte de capteurs Bluetooth, 100 Hz, 16 bits
- **Python** : acquisition + traitement du signal + serveur WebSocket
- **Unity** : jeu + adaptation de la difficulté
- Communication locale : `ws://localhost:8765`

> *Visuel : diagramme fléché avec les 3 blocs colorés*

---

## SLIDE 6 — Les capteurs (1 min)
**Titre :** 5 capteurs pour mesurer le joueur

| Capteur | Mesure |
|---------|--------|
| RESP | Fréquence respiratoire |
| PPG | Fréquence cardiaque + HRV |
| EDA | Conductance cutanée (stress) |
| EMG | Détection du tir |
| ACC (x2) | Tremblement pendant la visée |

- Tout sur une seule carte BITalino Core BT
- Connexion Bluetooth — sans fil pendant le jeu

> *Visuel : photo du BITalino avec les électrodes placées sur la main/bras*

---

## SLIDE 7 — Calibration individuelle (45 s)
**Titre :** 30 secondes pour personnaliser l'analyse

- Avant chaque partie : **30 secondes de repos**
- Le système mesure les **baselines individuelles** :
  - FC au repos, HRV au repos
  - Fréquence respiratoire au repos
  - Niveau EDA de base
  - Activité musculaire minimale (seuil EMG)
- Résultat : le score de stress est **relatif à chaque joueur**, pas absolu

> *À l'oral : "Deux joueurs avec des physiologies très différentes obtiendront un score comparable."*

---

## SLIDE 8 — Détection de pics PPG/RESP (1 min)
**Titre :** Comment mesurer la FC et la respiration ?

- Algorithme de détection de pics sur **fenêtre glissante**
- Seuil adaptatif : `seuil = médiane + α × amplitude(P90−P10)`
  - Robuste aux artefacts de mouvement
- Période réfractaire : 0,35 s (PPG) / 2,0 s (RESP)
  - Évite de compter deux fois le même battement
- HRV calculée sur les **20 derniers intervalles R-R**

> *Visuel : graphique d'un signal PPG avec les pics détectés marqués*

---

## SLIDE 9 — Score de stress (1 min)
**Titre :** Une formule multimodale inspirée de WESAD

$$\text{stress} = 0.35 \cdot s_{HR} + 0.30 \cdot s_{HRV} + 0.20 \cdot s_{EDA} + 0.15 \cdot s_{RESP}$$

- Chaque composante normalisée par la baseline individuelle
- HR et HRV : poids les plus élevés → indicateurs les plus fiables
- Score entre 0 (repos) et 1 (stress maximal)
- Envoyé à Unity à **10 Hz** via WebSocket

> *À l'oral : "On s'est inspiré du dataset WESAD qui a validé cette approche multimodale sur plusieurs sujets."*

---

## SLIDE 10 — Déclenchement du tir EMG (45 s)
**Titre :** Tirer avec ses muscles

- Le joueur **contracte** le muscle → EMG dépasse le seuil calibré
- Le joueur **relâche** → signal `shot_triggered` envoyé à Unity
- Reproduit la mécanique naturelle d'un tir de golf
- Seuil = `moyenne + 15 × écart-type` (calculé à la calibration)

> *Visuel : courbe EMG montrant contraction → relâchement → tir*

---

## SLIDE 11 — Le jeu Unity (1 min)
**Titre :** Adaptation en temps réel

- **Écran de calibration** : barre de progression pendant les 30 s
- **Jeu principal** : 3 mécanismes adaptatifs

| Paramètre | Comportement |
|-----------|-------------|
| Vent | Proportionnel au stress |
| Tremblement balle | Piloté par l'accéléromètre, amplifié si stress > 0,5 |
| Chrono par trou | Inversement proportionnel au stress |

- Transitions lissées avec Lerp (3–5 s) pour éviter les sauts brusques
- Le score de stress n'est **pas affiché** au joueur

> *Visuel : screenshot du jeu avec annotations*

---

## SLIDE 12 — Organisation du projet (45 s)
**Titre :** Comment on a travaillé

- **3 personnes** : 2 sur Unity, 1 sur le pipeline Python
- Interface définie en amont → **développement en parallèle**
- 4 phases : acquisition brute → traitement signal → WebSocket → Unity
- Défi : un membre ne pouvait pas coupler le BITalino sur sa machine
  → Séparation développement (en aveugle) / test (sur la machine fonctionnelle)

---

## SLIDE 13 — Développement assisté par IA (1 min)
**Titre :** Co-développement humain-IA avec Claude Code

**Ce que l'IA a apporté :**
- Architecture multi-thread (matplotlib + acquisition + WebSocket)
- Algorithmes de détection de pics adaptatifs
- Débogage du bug de filtrage WebSocket

**Les limites :**
- L'IA ne peut pas tester sur le vrai matériel
- Paramètres (seuil EMG, multiplicateur de pics) ajustés empiriquement
- Risque de dépendance sans comprendre les paramètres

> *À l'oral : "On estime le gain de temps à environ 3× sur le pipeline Python. Mais ça n'a pas remplacé la validation sur le matériel réel."*

---

## SLIDE 14 — Défis techniques (1 min)
**Titre :** Ce qui ne s'est pas passé comme prévu

**EDA capricieux**
- Signal inutilisable au départ (mauvais contact)
- Après ajustement : valeurs brutes 27–31 sur 65535 → effet "escalier"
- Valeurs aberrantes ponctuelles → filtre P90-P10 + écrêtage

**Threading**
- 3 threads simultanés → crash Tkinter au Ctrl+C
- Corrigé avec `signal.signal(SIGINT)` + `threading.Event`

> *À l'oral : "Ces problèmes sont typiques d'un projet matériel : on ne les voit pas en simulation."*

---

## SLIDE 15 — Ce qui fonctionne (45 s)
**Titre :** Bilan positif

✅ Détection EMG du tir — fiable après calibration
✅ Fréquence cardiaque via PPG — précision suffisante
✅ WebSocket Python-Unity — latence < 100 ms, 10 Hz stables
✅ Calibration individuelle — score de stress robuste inter-sujets
✅ Chaîne complète fonctionnelle de bout en bout

---

## SLIDE 16 — Limites (30 s)
**Titre :** Ce qu'on ne peut pas affirmer

- **EDA peu fiable** dans un contexte de jeu casual (faible réponse sympathique)
- **Pas de validation scientifique** : pas de Flow Short Scale, pas de condition contrôlée
- → Démonstration de **faisabilité technique**, pas une preuve scientifique du flow induit

---

## SLIDE 17 — Conclusion & Perspectives (30 s)
**Titre :** Et ensuite ?

**Ce qu'on a montré :** un système temps réel complet, capteurs → jeu adaptatif, faisable à faible coût

**Pour aller plus loin :**
- ECG à la place du PPG → HRV plus précise
- Questionnaire Flow Short Scale + condition contrôlée
- Affiner l'algorithme de tremblement accéléromètre

> *Terminer par :* **"Des questions ?"**

---

## Notes générales

- **Durée estimée par slide** : ~40 secondes en moyenne
- **Slides visuels à prévoir** : schéma flow (S3), diagramme architecture (S5), photo BITalino (S6), graphique PPG (S8), screenshot Unity (S11)
- **Démo live** (optionnel) : si le BITalino est disponible, montrer 10 secondes de signal en direct entre S6 et S7
