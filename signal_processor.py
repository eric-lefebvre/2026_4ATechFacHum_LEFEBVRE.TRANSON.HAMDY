import numpy as np
from collections import deque


# Window sizes at 100 Hz
EMG_WINDOW = 50        # 0.5s for RMS
EDA_WINDOW = 500       # 5s for baseline
HRV_WINDOW = 10        # last 10 RR intervals


class SignalProcessor:
    """
    Converts raw sensor frames into semantic game values.

    Output per frame:
      - shot_triggered (bool)
      - shot_power (float 0-1)
      - aim_x, aim_y (float, degrees of tilt)
      - stress_level (float 0-1)
    """

    def __init__(self, sampling_rate=100):
        self.sampling_rate = sampling_rate

        # EMG
        self._emg_buf = deque(maxlen=EMG_WINDOW)
        self._emg_baseline_rms = None
        self._emg_peak_rms = 0.0
        self._emg_was_above = False

        # EDA
        self._eda_buf = deque(maxlen=EDA_WINDOW)
        self._eda_baseline = None

        # ECG / HRV
        self._ecg_buf = deque(maxlen=30)
        self._last_r_time = None
        self._rr_intervals = deque(maxlen=HRV_WINDOW)
        self._rmssd = 40.0  # default resting value ms

        # Calibration
        self._calibration_frames = 0
        self._calibration_done = False
        self._calibration_target = sampling_rate * 5  # 5s

    # ------------------------------------------------------------------
    def process(self, frame: dict) -> dict:
        """
        Feed one raw frame, get one semantic output dict.
        """
        self._calibrate(frame)

        shot_triggered, shot_power = self._process_emg(
            frame["emg"], frame["timestamp"]
        )
        aim_x, aim_y = self._process_acc(
            frame["acc_x"], frame["acc_y"], frame["acc_z"]
        )
        stress = self._process_stress(frame["eda"], frame["ecg"], frame["timestamp"])

        return {
            "shot_triggered": shot_triggered,
            "shot_power": round(shot_power, 3),
            "aim_x": round(aim_x, 2),
            "aim_y": round(aim_y, 2),
            "stress_level": round(stress, 3),
            "calibrated": self._calibration_done,
        }

    # ------------------------------------------------------------------
    def _calibrate(self, frame):
        """Collect 5s of resting data to set individual baselines."""
        if self._calibration_done:
            return
        self._calibration_frames += 1
        self._eda_buf.append(frame["eda"])
        self._emg_buf.append(frame["emg"])

        if self._calibration_frames >= self._calibration_target:
            self._eda_baseline = np.mean(self._eda_buf)
            self._emg_baseline_rms = self._rms(self._emg_buf)
            self._calibration_done = True
            print(
                f"[Calibration done] EDA baseline={self._eda_baseline:.2f}µS  "
                f"EMG baseline RMS={self._emg_baseline_rms:.4f}"
            )

    # ------------------------------------------------------------------
    def _process_emg(self, raw_emg, timestamp):
        self._emg_buf.append(raw_emg)
        current_rms = self._rms(self._emg_buf)

        shot_triggered = False
        shot_power = 0.0

        if not self._calibration_done:
            return shot_triggered, shot_power

        threshold = self._emg_baseline_rms * 3.0

        if current_rms > threshold:
            self._emg_peak_rms = max(self._emg_peak_rms, current_rms)
            self._emg_was_above = True
        elif self._emg_was_above:
            # muscle released → trigger shot
            shot_triggered = True
            # normalize: baseline*3 = 0, baseline*10 = 1.0
            shot_power = np.clip(
                (self._emg_peak_rms - threshold) / (self._emg_baseline_rms * 7), 0, 1
            )
            self._emg_peak_rms = 0.0
            self._emg_was_above = False

        return shot_triggered, float(shot_power)

    # ------------------------------------------------------------------
    def _process_acc(self, ax, ay, az):
        """
        Convert 3-axis accelerometer to pitch/roll in degrees.
        Pitch = tilt forward/back, Roll = tilt left/right.
        """
        pitch = float(np.degrees(np.arctan2(ay, np.sqrt(ax**2 + az**2))))
        roll = float(np.degrees(np.arctan2(-ax, az)))
        return pitch, roll

    # ------------------------------------------------------------------
    def _process_stress(self, raw_eda, raw_ecg, timestamp):
        """
        Combine EDA and HRV into a single stress_level [0, 1].
        0 = calm/coherent, 1 = highly stressed.
        """
        # --- EDA component ---
        self._eda_buf.append(raw_eda)
        eda_stress = 0.5
        if self._calibration_done and self._eda_baseline is not None:
            current_scl = np.mean(list(self._eda_buf)[-100:])  # last 1s
            # relative change from baseline
            delta = (current_scl - self._eda_baseline) / max(self._eda_baseline, 0.1)
            eda_stress = float(np.clip(delta / 2.0, 0, 1))

        # --- HRV component (RMSSD) ---
        self._ecg_buf.append(raw_ecg)
        self._detect_r_peak(raw_ecg, timestamp)
        hrv_stress = self._hrv_to_stress()

        # Weighted combination: HRV is more reliable, EDA captures slower trends
        stress = 0.4 * eda_stress + 0.6 * hrv_stress
        return float(np.clip(stress, 0, 1))

    def _detect_r_peak(self, ecg_val, timestamp):
        threshold = 0.7
        if ecg_val >= threshold:
            if self._last_r_time is None or (timestamp - self._last_r_time) > 0.3:
                if self._last_r_time is not None:
                    rr_ms = (timestamp - self._last_r_time) * 1000
                    if 400 < rr_ms < 1500:  # physiologically valid
                        self._rr_intervals.append(rr_ms)
                        self._update_rmssd()
                self._last_r_time = timestamp

    def _update_rmssd(self):
        if len(self._rr_intervals) < 2:
            return
        rr = np.array(self._rr_intervals)
        successive_diffs = np.diff(rr)
        self._rmssd = float(np.sqrt(np.mean(successive_diffs**2)))

    def _hrv_to_stress(self):
        # RMSSD: resting ~40-80ms, stressed ~15-30ms
        # Map: 80ms → 0 (calm), 15ms → 1 (stressed)
        return float(np.clip(1.0 - (self._rmssd - 15) / 65, 0, 1))

    # ------------------------------------------------------------------
    @staticmethod
    def _rms(buf):
        if not buf:
            return 0.0
        return float(np.sqrt(np.mean(np.array(buf) ** 2)))
