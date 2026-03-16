"""
Anomaly Detector - Reference Implementation
Detects infrastructure anomalies using adaptive baselines with
seasonal adjustment (time-of-day, day-of-week) and multiple
statistical methods (z-score, IQR).
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum
import math
import uuid

# Import persistence layer (optional - allows graceful degradation if DB unavailable)
try:
    from ..db import (
        save_anomaly_record,
        get_anomaly_streak,
        increment_anomaly_streak,
        reset_anomaly_streak,
        save_metric_snapshot,
    )
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


class AnomalyLevel(Enum):
    NORMAL = "normal"
    WARNING = "warning"       # approaching anomaly threshold
    ANOMALY = "anomaly"       # exceeds threshold, fire alert


@dataclass
class MetricPoint:
    resource_id: str
    metric_name: str
    value: float
    timestamp: datetime


@dataclass
class SeasonalBaseline:
    """Baseline statistics for a specific resource/metric/time combination."""
    resource_id: str
    metric_name: str
    hour_of_day: int           # 0-23
    day_of_week: int           # 0-6 (Monday=0)
    mean: float
    stddev: float
    iqr_lower: float           # 25th percentile
    iqr_upper: float           # 75th percentile
    sample_count: int
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AnomalyDetection:
    resource_id: str
    resource_name: str
    metric_name: str
    current_value: float
    baseline_mean: float
    baseline_stddev: float
    z_score: float
    iqr_status: str            # "normal", "mild_outlier", "extreme_outlier"
    level: AnomalyLevel
    persisted_points: int      # how many consecutive anomalous data points
    message: str


class AnomalyDetector:
    """
    Detects anomalies in infrastructure metrics using adaptive baselines
    that account for time-of-day and day-of-week seasonality.

    Detection methods:
    1. Z-score: flag if > 3 standard deviations from seasonal baseline
    2. IQR: flag if outside 1.5x (mild) or 3x (extreme) interquartile range
    3. Persistence: require anomaly to persist for 3+ data points before alerting
       (avoids single-point noise)

    In production, baselines are stored in TimescaleDB and updated nightly
    using an exponential moving average. This reference implementation
    demonstrates the detection logic and baseline management.
    """

    Z_SCORE_WARNING = 2.0
    Z_SCORE_ANOMALY = 3.0
    IQR_MILD_MULTIPLIER = 1.5
    IQR_EXTREME_MULTIPLIER = 3.0
    PERSISTENCE_THRESHOLD = 3     # consecutive anomalous points to alert

    def __init__(self, persist_to_db: bool = True):
        self.baselines: dict[str, SeasonalBaseline] = {}
        self.recent_values: dict[str, list[MetricPoint]] = defaultdict(list)
        self.anomaly_streak: dict[str, int] = defaultdict(int)
        self.persist_to_db = persist_to_db and DB_AVAILABLE

    def add_baseline(self, baseline: SeasonalBaseline):
        """Load a baseline (from TimescaleDB in production)."""
        key = self._baseline_key(
            baseline.resource_id, baseline.metric_name,
            baseline.hour_of_day, baseline.day_of_week,
        )
        self.baselines[key] = baseline

    def evaluate(
        self,
        point: MetricPoint,
        resource_name: str = "",
    ) -> AnomalyDetection:
        """
        Evaluate a single metric data point against its seasonal baseline.
        """
        hour = point.timestamp.hour
        dow = point.timestamp.weekday()
        baseline_key = self._baseline_key(
            point.resource_id, point.metric_name, hour, dow,
        )
        baseline = self.baselines.get(baseline_key)

        if not baseline or baseline.sample_count < 30:
            # Insufficient baseline data, can't detect anomalies
            return AnomalyDetection(
                resource_id=point.resource_id,
                resource_name=resource_name,
                metric_name=point.metric_name,
                current_value=point.value,
                baseline_mean=0, baseline_stddev=0,
                z_score=0, iqr_status="insufficient_data",
                level=AnomalyLevel.NORMAL,
                persisted_points=0,
                message="Insufficient baseline data for anomaly detection",
            )

        # Z-score calculation
        z_score = 0.0
        if baseline.stddev > 0:
            z_score = (point.value - baseline.mean) / baseline.stddev

        # IQR classification
        iqr = baseline.iqr_upper - baseline.iqr_lower
        iqr_status = "normal"
        if iqr > 0:
            if (point.value > baseline.iqr_upper + self.IQR_EXTREME_MULTIPLIER * iqr or
                    point.value < baseline.iqr_lower - self.IQR_EXTREME_MULTIPLIER * iqr):
                iqr_status = "extreme_outlier"
            elif (point.value > baseline.iqr_upper + self.IQR_MILD_MULTIPLIER * iqr or
                    point.value < baseline.iqr_lower - self.IQR_MILD_MULTIPLIER * iqr):
                iqr_status = "mild_outlier"

        # Determine anomaly level
        abs_z = abs(z_score)
        if abs_z >= self.Z_SCORE_ANOMALY or iqr_status == "extreme_outlier":
            raw_level = AnomalyLevel.ANOMALY
        elif abs_z >= self.Z_SCORE_WARNING or iqr_status == "mild_outlier":
            raw_level = AnomalyLevel.WARNING
        else:
            raw_level = AnomalyLevel.NORMAL

        # Persistence check: only alert if anomaly persists
        streak_key = f"{point.resource_id}:{point.metric_name}"

        if raw_level == AnomalyLevel.ANOMALY:
            # Increment anomaly streak (from DB or in-memory)
            if self.persist_to_db:
                persisted = increment_anomaly_streak(point.resource_id, point.metric_name)
            else:
                self.anomaly_streak[streak_key] += 1
                persisted = self.anomaly_streak[streak_key]
        else:
            # Reset streak when anomaly resolves
            if self.persist_to_db:
                reset_anomaly_streak(point.resource_id, point.metric_name)
            else:
                self.anomaly_streak[streak_key] = 0
            persisted = 0
        final_level = (
            AnomalyLevel.ANOMALY
            if persisted >= self.PERSISTENCE_THRESHOLD
            else raw_level if raw_level == AnomalyLevel.WARNING
            else AnomalyLevel.NORMAL
        )

        # Build message
        message = self._build_message(
            point, baseline, z_score, iqr_status, final_level, persisted,
        )

        detection = AnomalyDetection(
            resource_id=point.resource_id,
            resource_name=resource_name,
            metric_name=point.metric_name,
            current_value=point.value,
            baseline_mean=baseline.mean,
            baseline_stddev=baseline.stddev,
            z_score=round(z_score, 2),
            iqr_status=iqr_status,
            level=final_level,
            persisted_points=persisted,
            message=message,
        )

        # Persist anomaly record to database (audit trail)
        if self.persist_to_db and final_level == AnomalyLevel.ANOMALY:
            try:
                baseline_key = self._baseline_key(
                    point.resource_id, point.metric_name,
                    point.timestamp.hour, point.timestamp.weekday()
                )
                save_anomaly_record(
                    anomaly_id=str(uuid.uuid4()),
                    resource_id=point.resource_id,
                    resource_name=resource_name,
                    metric_name=point.metric_name,
                    current_value=point.value,
                    level=final_level.value,
                    persisted_points=persisted,
                    baseline_mean=baseline.mean,
                    baseline_stddev=baseline.stddev,
                    z_score=z_score,
                    iqr_status=iqr_status,
                    message=message,
                    baseline_key=baseline_key,
                )
            except Exception as e:
                # Log but don't fail: anomaly detection continues
                import logging
                logging.warning(f"Failed to persist anomaly record: {e}")

        return detection

    def update_baseline_ema(
        self,
        baseline: SeasonalBaseline,
        new_value: float,
        alpha: float = 0.1,
    ) -> SeasonalBaseline:
        """
        Update baseline using exponential moving average.
        Recent data points have more influence than older ones.

        alpha=0.1 means the new value contributes 10% to the updated mean.
        This smooths out noise while adapting to gradual changes
        (e.g., growing traffic over months).
        """
        new_mean = alpha * new_value + (1 - alpha) * baseline.mean

        # Update stddev with Welford-like EMA approach
        deviation = new_value - baseline.mean
        new_variance = alpha * (deviation ** 2) + (1 - alpha) * (baseline.stddev ** 2)
        new_stddev = math.sqrt(new_variance)

        baseline.mean = new_mean
        baseline.stddev = new_stddev
        baseline.sample_count += 1
        baseline.updated_at = datetime.utcnow()

        return baseline

    def _baseline_key(
        self, resource_id: str, metric_name: str, hour: int, dow: int,
    ) -> str:
        return f"{resource_id}:{metric_name}:{hour}:{dow}"

    def _build_message(
        self,
        point: MetricPoint,
        baseline: SeasonalBaseline,
        z_score: float,
        iqr_status: str,
        level: AnomalyLevel,
        persisted: int,
    ) -> str:
        if level == AnomalyLevel.NORMAL:
            return (
                f"{point.metric_name} = {point.value:.2f} is within normal range "
                f"(baseline: {baseline.mean:.2f} +/- {baseline.stddev:.2f})"
            )
        elif level == AnomalyLevel.WARNING:
            return (
                f"{point.metric_name} = {point.value:.2f} is elevated "
                f"(z-score: {z_score:.1f}, baseline: {baseline.mean:.2f}). "
                f"Monitoring for persistence."
            )
        else:
            return (
                f"ANOMALY: {point.metric_name} = {point.value:.2f} "
                f"(z-score: {z_score:.1f}, {persisted} consecutive breaches, "
                f"baseline: {baseline.mean:.2f} +/- {baseline.stddev:.2f} "
                f"for {baseline.hour_of_day}:00 on day {baseline.day_of_week})"
            )


def anomaly_example():
    """
    Example: detect CPU anomaly using seasonal baselines.
    Normal CPU at 2pm on Wednesday is 45% +/- 8%.
    Current reading is 89%, which is a clear anomaly.
    """
    detector = AnomalyDetector()

    # Load baseline: CPU usage at 2pm on Wednesdays
    detector.add_baseline(SeasonalBaseline(
        resource_id="api-prod-01",
        metric_name="cpu_utilization",
        hour_of_day=14,
        day_of_week=2,        # Wednesday
        mean=0.45,
        stddev=0.08,
        iqr_lower=0.38,
        iqr_upper=0.52,
        sample_count=180,     # ~6 months of Wednesdays at 2pm
    ))

    # Simulate 5 consecutive readings showing CPU spike
    readings = [0.48, 0.72, 0.85, 0.89, 0.91]
    base_time = datetime(2025, 2, 12, 14, 0)    # Wednesday 2pm

    print("CPU anomaly detection (baseline: 45% +/- 8% at Wed 2pm):\n")

    for i, cpu in enumerate(readings):
        point = MetricPoint(
            resource_id="api-prod-01",
            metric_name="cpu_utilization",
            value=cpu,
            timestamp=base_time + timedelta(minutes=i),
        )

        result = detector.evaluate(point, resource_name="payment-api-prod-01")

        icon = {"normal": ".", "warning": "!", "anomaly": "X"}[result.level.value]
        print(
            f"  [{icon}] t+{i}min: CPU={cpu:.0%}, z-score={result.z_score:+.1f}, "
            f"IQR={result.iqr_status}, streak={result.persisted_points}, "
            f"level={result.level.value}"
        )

    print(f"\n  Final: {result.message}")


if __name__ == "__main__":
    anomaly_example()
