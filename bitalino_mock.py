import numpy as np
import time


class BitalinoMock:
    """
    Simulates realistic Bitalino sensor data for development without hardware.
    Generates EMG, ACC (x/y/z), EDA, and ECG signals.
    """

    def __init__(self, sampling_rate=100):
        self.sampling_rate = sampling_rate
        self._start_time = time.time()
        self._rng = np.random.default_rng(seed=42)

        # EMG state
        self._emg_contracting = False
        self._emg_contraction_start = 0.0
        self._emg_next_contraction = 3.0

        # EDA state — slowly rising baseline with occasional phasic peaks
        self._eda_baseline = 5.0  # µS
        self._eda_next_peak = 8.0

        # ACC state — slow oscillation simulating arm movement
        self._acc_phase = 0.0

        # ECG state — R-peak timing
        self._ecg_last_r = 0.0
        self._ecg_rr_interval = 0.85  # ~70 bpm

    def read_frame(self):
        """
        Returns one frame of simulated data as a dict with raw channel values.
        Call this at self.sampling_rate Hz.
        """
        t = time.time() - self._start_time

        emg = self._generate_emg(t)
        acc_x, acc_y, acc_z = self._generate_acc(t)
        eda = self._generate_eda(t)
        ecg = self._generate_ecg(t)

        return {
            "emg": emg,
            "acc_x": acc_x,
            "acc_y": acc_y,
            "acc_z": acc_z,
            "eda": eda,
            "ecg": ecg,
            "timestamp": t,
        }

    def _generate_emg(self, t):
        noise = self._rng.normal(0, 0.02)

        if not self._emg_contracting and t > self._emg_next_contraction:
            self._emg_contracting = True
            self._emg_contraction_start = t
            # next contraction in 5-10 seconds
            self._emg_next_contraction = t + self._rng.uniform(5, 10)

        if self._emg_contracting:
            elapsed = t - self._emg_contraction_start
            # contraction lasts ~1.5s: rise then fall
            if elapsed < 0.75:
                signal = np.sin(np.pi * elapsed / 0.75) * self._rng.uniform(0.6, 1.0)
            elif elapsed < 1.5:
                signal = np.sin(np.pi * elapsed / 0.75) * 0.3
            else:
                self._emg_contracting = False
                signal = 0.0
            return float(np.clip(signal + noise, 0, 1))

        return float(np.clip(abs(noise) * 0.5, 0, 1))

    def _generate_acc(self, t):
        # Slow oscillation simulating arm tilt for aiming
        acc_x = np.sin(0.3 * t) * 0.4 + self._rng.normal(0, 0.01)
        acc_y = np.cos(0.2 * t) * 0.3 + self._rng.normal(0, 0.01)
        acc_z = np.sqrt(max(0, 1.0 - acc_x**2 - acc_y**2)) + self._rng.normal(0, 0.01)
        return float(acc_x), float(acc_y), float(acc_z)

    def _generate_eda(self, t):
        # Slow rising baseline + phasic peaks
        self._eda_baseline += self._rng.normal(0, 0.002)
        self._eda_baseline = np.clip(self._eda_baseline, 2.0, 20.0)

        peak = 0.0
        if t > self._eda_next_peak:
            # SCR peak: fast rise, slow decay
            elapsed = t - self._eda_next_peak
            peak = 3.0 * np.exp(-elapsed / 2.0) if elapsed < 6.0 else 0.0
            if elapsed > 8.0:
                self._eda_next_peak = t + self._rng.uniform(5, 15)

        return float(self._eda_baseline + peak + self._rng.normal(0, 0.05))

    def _generate_ecg(self, t):
        # Simple R-peak simulation with variable RR intervals (basic HRV)
        noise = self._rng.normal(0, 0.05)

        if t - self._ecg_last_r >= self._ecg_rr_interval:
            self._ecg_last_r = t
            # Slight HRV: RR varies ±50ms
            self._ecg_rr_interval = 0.85 + self._rng.normal(0, 0.05)
            self._ecg_rr_interval = np.clip(self._ecg_rr_interval, 0.5, 1.2)
            return float(1.0 + noise)  # R-peak

        phase = (t - self._ecg_last_r) / self._ecg_rr_interval
        # Rough ECG waveform shape
        if phase < 0.1:
            return float(0.1 * np.sin(phase * np.pi / 0.1) + noise)
        elif phase < 0.15:
            return float(-0.1 + noise)
        return float(noise * 0.3)
