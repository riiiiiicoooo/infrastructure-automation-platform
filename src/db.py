"""
Database connection pooling and persistence layer for infrastructure automation platform.

Provides SQLAlchemy with QueuePool connection management and Redis integration for
persisting anomaly detection state (recent metric values, anomaly streaks).

Design:
- QueuePool for efficient connection management (pool_size=10, max_overflow=20)
- Redis for high-speed reads of recent anomaly state (TTL: configurable)
- PostgreSQL for durable historical anomaly records and baseline storage
- SQLAlchemy ORM for queries and transactions

Models:
- SeasonalBaseline: baseline statistics per resource/metric/time combination
- AnomalyRecord: immutable audit trail of anomaly detections
- MetricSnapshot: recent metric values for quick lookup (also in Redis)
"""

import os
import json
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum

from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    Float,
    DateTime,
    JSON,
    Index,
    Enum as SQLEnum,
    event,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import QueuePool

# Try to import Redis (optional)
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Database configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/infrastructure_automation"
)

# Redis configuration (optional but recommended for anomaly state)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_AVAILABLE = REDIS_AVAILABLE and os.getenv("REDIS_ENABLED", "true").lower() == "true"

# Connection pool configuration
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))  # 1 hour
POOL_PRE_PING = True  # Verify connections are alive before using

# Create engine with QueuePool
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=POOL_PRE_PING,
    echo=False,
)

# Create session factory
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# Initialize Redis client (optional)
redis_client = None
if REDIS_AVAILABLE:
    try:
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
        )
        redis_client.ping()
    except Exception as e:
        import logging
        logging.warning(f"Redis connection failed: {e}. Anomaly state will use PostgreSQL only.")
        redis_client = None

# Declarative base for ORM models
Base = declarative_base()


# ============================================================================
# Enums
# ============================================================================


class AnomalyLevel(str, Enum):
    """Anomaly severity levels."""
    NORMAL = "normal"
    WARNING = "warning"  # approaching anomaly threshold
    ANOMALY = "anomaly"  # exceeds threshold, fire alert


class IQRStatus(str, Enum):
    """IQR classification for outlier detection."""
    NORMAL = "normal"
    MILD_OUTLIER = "mild_outlier"
    EXTREME_OUTLIER = "extreme_outlier"
    INSUFFICIENT_DATA = "insufficient_data"


# ============================================================================
# ORM Models
# ============================================================================


class SeasonalBaseline(Base):
    """
    Baseline statistics per resource/metric/time combination.

    Used for seasonal anomaly detection (account for time-of-day and
    day-of-week patterns). Updated nightly using exponential moving average.

    Immutable once created (updated_at tracks when stats were computed).
    """

    __tablename__ = "seasonal_baselines"

    # Primary key
    id = Column(Integer, primary_key=True)
    baseline_key = Column(String(255), nullable=False, unique=True, index=True)

    # Dimension identifiers
    resource_id = Column(String(255), nullable=False)
    metric_name = Column(String(255), nullable=False)
    hour_of_day = Column(Integer, nullable=False)  # 0-23
    day_of_week = Column(Integer, nullable=False)  # 0-6 (Monday=0)

    # Statistical measures
    mean = Column(Float, nullable=False)
    stddev = Column(Float, nullable=False)
    iqr_lower = Column(Float)  # 25th percentile
    iqr_upper = Column(Float)  # 75th percentile
    sample_count = Column(Integer, default=0)

    # Timestamps
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_baseline_resource_metric_time", "resource_id", "metric_name", "hour_of_day", "day_of_week"),
        Index("ix_baseline_updated_at", "updated_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<SeasonalBaseline(resource={self.resource_id}, "
            f"metric={self.metric_name}, hour={self.hour_of_day}, dow={self.day_of_week})>"
        )


class AnomalyRecord(Base):
    """
    Immutable audit trail of anomaly detections.

    Persisted whenever an anomaly is detected, allowing:
    - Historical trend analysis
    - Incident correlation
    - Baseline quality evaluation
    - Alert log audit trail

    Write-once: never updated or deleted (compliance requirement).
    """

    __tablename__ = "anomaly_records"

    # Primary key
    id = Column(Integer, primary_key=True)
    anomaly_id = Column(String(255), nullable=False, unique=True, index=True)

    # Resource and metric
    resource_id = Column(String(255), nullable=False, index=True)
    resource_name = Column(String(500))
    metric_name = Column(String(255), nullable=False)

    # Metric value
    current_value = Column(Float, nullable=False)
    baseline_mean = Column(Float)
    baseline_stddev = Column(Float)

    # Detection methods
    z_score = Column(Float)
    iqr_status = Column(SQLEnum(IQRStatus), default=IQRStatus.NORMAL)

    # Anomaly severity
    level = Column(SQLEnum(AnomalyLevel), nullable=False)
    persisted_points = Column(Integer, default=0)  # consecutive anomalous data points
    message = Column(String(500))

    # Baseline context
    baseline_key = Column(String(255), index=True)

    # Timing
    detected_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_anomaly_record_resource_id", "resource_id"),
        Index("ix_anomaly_record_level", "level"),
        Index("ix_anomaly_record_detected_at", "detected_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AnomalyRecord(anomaly_id={self.anomaly_id}, "
            f"resource={self.resource_id}, level={self.level}, "
            f"detected_at={self.detected_at})>"
        )


class MetricSnapshot(Base):
    """
    Recent metric values for quick lookup and anomaly streak tracking.

    Denormalized for performance: recent 100 metric points per resource/metric
    pair. Also cached in Redis for sub-millisecond retrieval.

    Enables:
    - Trend analysis: recent metric values
    - Persistence check: how long has anomaly persisted
    - Baseline quality: actual distribution vs baseline
    """

    __tablename__ = "metric_snapshots"

    # Primary key
    id = Column(Integer, primary_key=True)
    snapshot_key = Column(String(255), nullable=False, index=True)

    # Resource and metric
    resource_id = Column(String(255), nullable=False)
    metric_name = Column(String(255), nullable=False)

    # Recent values (JSON array of {timestamp, value})
    recent_values = Column(JSON, default=list)  # Max 100 points
    anomaly_streak = Column(Integer, default=0)  # consecutive anomalies

    # Metadata
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_metric_snapshot_key", "snapshot_key"),
        Index("ix_metric_snapshot_resource_metric", "resource_id", "metric_name"),
    )

    def __repr__(self) -> str:
        return (
            f"<MetricSnapshot(resource={self.resource_id}, "
            f"metric={self.metric_name}, values={len(self.recent_values)}, "
            f"streak={self.anomaly_streak})>"
        )


# ============================================================================
# Database Utilities
# ============================================================================


def init_db() -> None:
    """Initialize database schema. Call once on startup."""
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    """Get a database session. Use as context manager or with cleanup."""
    return SessionLocal()


def close_db() -> None:
    """Close all connections in the pool. Call on shutdown."""
    engine.dispose()


def save_anomaly_record(
    anomaly_id: str,
    resource_id: str,
    metric_name: str,
    current_value: float,
    level: str,
    persisted_points: int = 0,
    baseline_mean: Optional[float] = None,
    baseline_stddev: Optional[float] = None,
    z_score: Optional[float] = None,
    iqr_status: Optional[str] = None,
    message: Optional[str] = None,
    resource_name: Optional[str] = None,
    baseline_key: Optional[str] = None,
) -> AnomalyRecord:
    """
    Persist an anomaly detection record.

    Args:
        anomaly_id: Unique anomaly identifier
        resource_id: Resource being monitored
        metric_name: Metric name (e.g., "cpu_usage", "memory_percent")
        current_value: The metric value that triggered anomaly
        level: "normal", "warning", or "anomaly"
        persisted_points: How many consecutive anomalous points
        baseline_mean: Baseline mean for this time slot
        baseline_stddev: Baseline stddev for this time slot
        z_score: Computed z-score
        iqr_status: IQR classification
        message: Human-readable anomaly description
        resource_name: Resource friendly name
        baseline_key: Reference to SeasonalBaseline

    Returns:
        Persisted AnomalyRecord
    """
    session = get_session()
    try:
        record = AnomalyRecord(
            anomaly_id=anomaly_id,
            resource_id=resource_id,
            resource_name=resource_name,
            metric_name=metric_name,
            current_value=current_value,
            baseline_mean=baseline_mean,
            baseline_stddev=baseline_stddev,
            z_score=z_score,
            iqr_status=IQRStatus(iqr_status) if iqr_status else None,
            level=AnomalyLevel(level),
            persisted_points=persisted_points,
            message=message,
            baseline_key=baseline_key,
        )
        session.add(record)
        session.commit()
        return record
    finally:
        session.close()


def save_metric_snapshot(
    resource_id: str,
    metric_name: str,
    recent_values: list,
    anomaly_streak: int = 0,
) -> MetricSnapshot:
    """
    Persist or update recent metric values and anomaly streak.

    Args:
        resource_id: Resource being monitored
        metric_name: Metric name
        recent_values: List of recent metric points (with timestamps)
        anomaly_streak: Current consecutive anomaly count

    Returns:
        Persisted MetricSnapshot
    """
    session = get_session()
    try:
        snapshot_key = f"{resource_id}:{metric_name}"
        snapshot = (
            session.query(MetricSnapshot)
            .filter(MetricSnapshot.snapshot_key == snapshot_key)
            .first()
        )

        if snapshot:
            # Update existing
            snapshot.recent_values = recent_values
            snapshot.anomaly_streak = anomaly_streak
            snapshot.updated_at = datetime.utcnow()
        else:
            # Create new
            snapshot = MetricSnapshot(
                snapshot_key=snapshot_key,
                resource_id=resource_id,
                metric_name=metric_name,
                recent_values=recent_values,
                anomaly_streak=anomaly_streak,
            )
            session.add(snapshot)

        session.commit()

        # Also update Redis cache for low-latency reads
        if redis_client:
            try:
                redis_client.setex(
                    f"anomaly_state:{snapshot_key}",
                    3600,  # 1 hour TTL
                    json.dumps({
                        "recent_values": recent_values,
                        "anomaly_streak": anomaly_streak,
                        "updated_at": datetime.utcnow().isoformat(),
                    })
                )
            except Exception as e:
                import logging
                logging.warning(f"Failed to update Redis cache: {e}")

        return snapshot
    finally:
        session.close()


def get_metric_snapshot(resource_id: str, metric_name: str) -> Optional[MetricSnapshot]:
    """Retrieve recent metric values for a resource/metric pair."""
    session = get_session()
    try:
        return (
            session.query(MetricSnapshot)
            .filter(
                MetricSnapshot.resource_id == resource_id,
                MetricSnapshot.metric_name == metric_name,
            )
            .first()
        )
    finally:
        session.close()


def get_anomaly_streak(resource_id: str, metric_name: str) -> int:
    """
    Get current anomaly streak (from Redis cache if available, else from DB).

    Returns:
        Number of consecutive anomalous data points, or 0 if none
    """
    snapshot_key = f"{resource_id}:{metric_name}"

    # Try Redis first (fast path)
    if redis_client:
        try:
            cached = redis_client.get(f"anomaly_state:{snapshot_key}")
            if cached:
                data = json.loads(cached)
                return data.get("anomaly_streak", 0)
        except Exception as e:
            import logging
            logging.warning(f"Redis lookup failed: {e}")

    # Fall back to database
    snapshot = get_metric_snapshot(resource_id, metric_name)
    return snapshot.anomaly_streak if snapshot else 0


def increment_anomaly_streak(resource_id: str, metric_name: str, max_streak: int = 100) -> int:
    """
    Increment anomaly streak for a resource/metric pair.

    Args:
        resource_id: Resource being monitored
        metric_name: Metric name
        max_streak: Cap streak at this value

    Returns:
        Updated streak count
    """
    snapshot = get_metric_snapshot(resource_id, metric_name)
    if snapshot:
        new_streak = min(snapshot.anomaly_streak + 1, max_streak)
        snapshot_key = f"{resource_id}:{metric_name}"

        # Update both DB and Redis
        session = get_session()
        try:
            snapshot.anomaly_streak = new_streak
            snapshot.updated_at = datetime.utcnow()
            session.commit()
        finally:
            session.close()

        # Update Redis
        if redis_client:
            try:
                redis_client.setex(
                    f"anomaly_state:{snapshot_key}",
                    3600,
                    json.dumps({
                        "recent_values": snapshot.recent_values,
                        "anomaly_streak": new_streak,
                        "updated_at": datetime.utcnow().isoformat(),
                    })
                )
            except Exception as e:
                import logging
                logging.warning(f"Failed to update Redis: {e}")

        return new_streak
    return 1


def reset_anomaly_streak(resource_id: str, metric_name: str) -> None:
    """Reset anomaly streak (metric returned to normal)."""
    snapshot = get_metric_snapshot(resource_id, metric_name)
    if snapshot:
        snapshot_key = f"{resource_id}:{metric_name}"

        session = get_session()
        try:
            snapshot.anomaly_streak = 0
            snapshot.updated_at = datetime.utcnow()
            session.commit()
        finally:
            session.close()

        # Update Redis
        if redis_client:
            try:
                redis_client.delete(f"anomaly_state:{snapshot_key}")
            except Exception as e:
                import logging
                logging.warning(f"Failed to clear Redis: {e}")


def get_seasonal_baseline(
    resource_id: str,
    metric_name: str,
    hour_of_day: int,
    day_of_week: int,
) -> Optional[SeasonalBaseline]:
    """Retrieve baseline statistics for a specific time slot."""
    session = get_session()
    try:
        return (
            session.query(SeasonalBaseline)
            .filter(
                SeasonalBaseline.resource_id == resource_id,
                SeasonalBaseline.metric_name == metric_name,
                SeasonalBaseline.hour_of_day == hour_of_day,
                SeasonalBaseline.day_of_week == day_of_week,
            )
            .first()
        )
    finally:
        session.close()


def save_seasonal_baseline(
    resource_id: str,
    metric_name: str,
    hour_of_day: int,
    day_of_week: int,
    mean: float,
    stddev: float,
    iqr_lower: Optional[float] = None,
    iqr_upper: Optional[float] = None,
    sample_count: int = 0,
) -> SeasonalBaseline:
    """Save or update seasonal baseline statistics."""
    session = get_session()
    try:
        baseline_key = f"{resource_id}:{metric_name}:{hour_of_day}:{day_of_week}"
        baseline = (
            session.query(SeasonalBaseline)
            .filter(SeasonalBaseline.baseline_key == baseline_key)
            .first()
        )

        if baseline:
            baseline.mean = mean
            baseline.stddev = stddev
            baseline.iqr_lower = iqr_lower
            baseline.iqr_upper = iqr_upper
            baseline.sample_count = sample_count
            baseline.updated_at = datetime.utcnow()
        else:
            baseline = SeasonalBaseline(
                baseline_key=baseline_key,
                resource_id=resource_id,
                metric_name=metric_name,
                hour_of_day=hour_of_day,
                day_of_week=day_of_week,
                mean=mean,
                stddev=stddev,
                iqr_lower=iqr_lower,
                iqr_upper=iqr_upper,
                sample_count=sample_count,
            )
            session.add(baseline)

        session.commit()
        return baseline
    finally:
        session.close()


if __name__ == "__main__":
    # Example: initialize database and create tables
    init_db()
    print("Database initialized successfully")
