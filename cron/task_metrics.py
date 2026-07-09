"""Task metrics collection for cron jobs.

This module provides a standardized way to collect execution metrics
from cron jobs, enabling the Task Optimization Advisor to analyze
performance and generate improvement suggestions.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TaskError:
    """Represents an error that occurred during task execution."""
    error_type: str           # e.g., "timeout", "api_error", "auth_error"
    message: str             # Error message
    timestamp: str           # When the error occurred
    recoverable: bool        # Whether the error is recoverable


@dataclass
class TaskMetrics:
    """Metrics collected from a task execution."""
    task_name: str           # Name of the task
    start_time: str          # ISO timestamp when task started
    end_time: str            # ISO timestamp when task ended
    execution_time_ms: int   # Total execution time in milliseconds
    api_calls: int           # Number of API calls made
    errors: List[TaskError]  # List of errors encountered
    timeout_count: int       # Number of timeouts
    success: bool            # Whether the task succeeded
    output_length: int       # Length of output (chars)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate based on errors."""
        if self.api_calls == 0:
            return 1.0 if self.success else 0.0
        # Simple calculation: success if no errors and task succeeded
        return 1.0 if (self.success and len(self.errors) == 0) else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data['success_rate'] = self.success_rate
        return data


class TaskMetricsCollector:
    """Collects and stores task execution metrics."""
    
    def __init__(self, task_name: str, storage_dir: Optional[Path] = None):
        self.task_name = task_name
        self.storage_dir = storage_dir or self._default_storage_dir()
        self._start_time: Optional[float] = None
        self._api_calls = 0
        self._errors: List[TaskError] = []
        self._timeout_count = 0
    
    def _default_storage_dir(self) -> Path:
        """Get default storage directory for metrics."""
        from hermes_constants import get_hermes_home
        return get_hermes_home() / "cron" / "metrics"
    
    def start(self) -> None:
        """Mark the start of task execution."""
        self._start_time = time.time()
        self._api_calls = 0
        self._errors = []
        self._timeout_count = 0
    
    def record_api_call(self) -> None:
        """Record an API call."""
        self._api_calls += 1
    
    def record_error(self, error_type: str, message: str, recoverable: bool = True) -> None:
        """Record an error that occurred during execution."""
        self._errors.append(TaskError(
            error_type=error_type,
            message=message,
            timestamp=datetime.utcnow().isoformat(),
            recoverable=recoverable
        ))
    
    def record_timeout(self) -> None:
        """Record a timeout."""
        self._timeout_count += 1
    
    def finish(self, success: bool = True, output_length: int = 0, metadata: Optional[Dict] = None) -> TaskMetrics:
        """Mark the end of task execution and return metrics."""
        end_time = time.time()
        execution_time_ms = int((end_time - self._start_time) * 1000) if self._start_time else 0
        
        metrics = TaskMetrics(
            task_name=self.task_name,
            start_time=datetime.utcfromtimestamp(self._start_time).isoformat() if self._start_time else "",
            end_time=datetime.utcnow().isoformat(),
            execution_time_ms=execution_time_ms,
            api_calls=self._api_calls,
            errors=self._errors,
            timeout_count=self._timeout_count,
            success=success,
            output_length=output_length,
            metadata=metadata or {}
        )
        
        self.save(metrics)
        return metrics
    
    def save(self, metrics: TaskMetrics) -> None:
        """Save metrics to storage."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.task_name}_{timestamp}.json"
        filepath = self.storage_dir / filename
        
        with open(filepath, 'w') as f:
            json.dump(metrics.to_dict(), f, indent=2)
    
    @staticmethod
    def load_recent(task_name: str, count: int = 10, storage_dir: Optional[Path] = None) -> List[TaskMetrics]:
        """Load recent metrics for a task."""
        if storage_dir is None:
            from hermes_constants import get_hermes_home
            storage_dir = get_hermes_home() / "cron" / "metrics"
        
        task_dir = storage_dir / task_name
        if not task_dir.exists():
            return []
        
        metrics_files = sorted(task_dir.glob("*.json"), reverse=True)[:count]
        result = []
        
        for filepath in metrics_files:
            try:
                with open(filepath) as f:
                    data = json.load(f)
                    # Convert back to TaskMetrics
                    errors = [TaskError(**e) for e in data.get('errors', [])]
                    data['errors'] = errors
                    result.append(TaskMetrics(**data))
            except Exception:
                continue
        
        return result


# Context manager for easy usage
class track_task:
    """Context manager for tracking task execution metrics."""
    
    def __init__(self, task_name: str, storage_dir: Optional[Path] = None):
        self.collector = TaskMetricsCollector(task_name, storage_dir)
        self.success = True
        self.output_length = 0
        self.metadata: Dict[str, Any] = {}
    
    def __enter__(self):
        self.collector.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.success = False
            self.collector.record_error(
                error_type=exc_type.__name__,
                message=str(exc_val),
                recoverable=False
            )
        
        self.collector.finish(
            success=self.success,
            output_length=self.output_length,
            metadata=self.metadata
        )
    
    def record_api_call(self):
        """Record an API call."""
        self.collector.record_api_call()
    
    def record_error(self, error_type: str, message: str, recoverable: bool = True):
        """Record an error."""
        self.collector.record_error(error_type, message, recoverable)
    
    def record_timeout(self):
        """Record a timeout."""
        self.collector.record_timeout()
