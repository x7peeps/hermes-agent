"""Task Optimization Advisor.

Analyzes cron job execution metrics, identifies problem patterns,
and generates actionable improvement suggestions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class Priority(Enum):
    """Priority level for optimization suggestions."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Dimension(Enum):
    """Analysis dimensions for task optimization."""
    EFFICIENCY = "efficiency"
    INTELLIGENCE = "intelligence"
    COVERAGE = "coverage"
    STABILITY = "stability"
    PREVENTION = "prevention"


@dataclass
class OptimizationSuggestion:
    """Represents a single optimization suggestion."""
    priority: Priority
    dimension: Dimension
    issue: str
    recommendation: str
    code_location: Optional[str] = None
    estimated_impact: Optional[str] = None
    confidence: float = 0.8
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "priority": self.priority.value,
            "dimension": self.dimension.value,
            "issue": self.issue,
            "recommendation": self.recommendation,
            "code_location": self.code_location,
            "estimated_impact": self.estimated_impact,
            "confidence": self.confidence
        }


@dataclass
class OptimizationReport:
    """Complete optimization report for a task."""
    task_name: str
    analysis_date: str
    metrics_summary: Dict[str, Any]
    suggestions: List[OptimizationSuggestion]
    overall_health: float  # 0.0 - 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_name": self.task_name,
            "analysis_date": self.analysis_date,
            "metrics_summary": self.metrics_summary,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "overall_health": self.overall_health
        }
    
    def to_markdown(self) -> str:
        """Convert report to markdown format."""
        lines = [
            f"# 任务优化分析报告: {self.task_name}",
            f"**分析时间**: {self.analysis_date}",
            f"**整体健康度**: {self.overall_health:.1%}",
            "",
            "## 指标摘要",
            ""
        ]
        
        for key, value in self.metrics_summary.items():
            lines.append(f"- **{key}**: {value}")
        
        lines.extend(["", "## 优化建议", ""])
        
        if not self.suggestions:
            lines.append("*暂无优化建议*")
        else:
            # Group by priority
            by_priority = {"high": [], "medium": [], "low": []}
            for s in self.suggestions:
                by_priority[s.priority.value].append(s)
            
            for priority in ["high", "medium", "low"]:
                items = by_priority[priority]
                if items:
                    lines.append(f"### {priority.upper()} 优先级")
                    for i, s in enumerate(items, 1):
                        lines.append(f"**{i}. {s.issue}**")
                        lines.append(f"   - 维度: {s.dimension.value}")
                        lines.append(f"   - 建议: {s.recommendation}")
                        if s.code_location:
                            lines.append(f"   - 位置: `{s.code_location}`")
                        if s.estimated_impact:
                            lines.append(f"   - 预期效果: {s.estimated_impact}")
                        lines.append("")
        
        return "\n".join(lines)


class TaskOptimizer:
    """Analyzes task metrics and generates optimization suggestions."""
    
    # Thresholds for triggering suggestions
    EFFICIENCY_THRESHOLD_MS = 30000  # 30 seconds
    API_CALL_THRESHOLD = 20
    ERROR_RATE_THRESHOLD = 0.1
    TIMEOUT_RATE_THRESHOLD = 0.05
    
    def __init__(self, metrics_dir: Optional[Path] = None):
        self.metrics_dir = metrics_dir or self._default_metrics_dir()
    
    def _default_metrics_dir(self) -> Path:
        from hermes_constants import get_hermes_home
        return get_hermes_home() / "cron" / "metrics"
    
    def analyze(self, task_name: str, recent_count: int = 10) -> OptimizationReport:
        """Analyze recent metrics for a task and generate optimization report."""
        from .task_metrics import TaskMetricsCollector
        
        metrics_list = TaskMetricsCollector.load_recent(
            task_name, 
            count=recent_count,
            storage_dir=self.metrics_dir
        )
        
        if not metrics_list:
            return OptimizationReport(
                task_name=task_name,
                analysis_date=datetime.utcnow().isoformat(),
                metrics_summary={},
                suggestions=[],
                overall_health=1.0
            )
        
        # Calculate summary statistics
        metrics_summary = self._calculate_summary(metrics_list)
        
        # Generate suggestions based on analysis
        suggestions = self._analyze_metrics(task_name, metrics_list, metrics_summary)
        
        # Calculate overall health
        overall_health = self._calculate_health(metrics_summary, suggestions)
        
        return OptimizationReport(
            task_name=task_name,
            analysis_date=datetime.utcnow().isoformat(),
            metrics_summary=metrics_summary,
            suggestions=suggestions,
            overall_health=overall_health
        )
    
    def _calculate_summary(self, metrics_list: List) -> Dict[str, Any]:
        """Calculate summary statistics from metrics."""
        if not metrics_list:
            return {}
        
        total_exec_time = sum(m.execution_time_ms for m in metrics_list)
        total_api_calls = sum(m.api_calls for m in metrics_list)
        total_errors = sum(len(m.errors) for m in metrics_list)
        total_timeouts = sum(m.timeout_count for m in metrics_list)
        success_count = sum(1 for m in metrics_list if m.success)
        
        return {
            "executions": len(metrics_list),
            "avg_execution_time_ms": total_exec_time // len(metrics_list),
            "total_api_calls": total_api_calls,
            "avg_api_calls": total_api_calls // len(metrics_list),
            "total_errors": total_errors,
            "total_timeouts": total_timeouts,
            "success_rate": success_count / len(metrics_list),
            "error_rate": total_errors / (len(metrics_list) * 10),  # normalize
        }
    
    def _analyze_metrics(self, task_name: str, metrics_list: List, summary: Dict) -> List[OptimizationSuggestion]:
        """Analyze metrics and generate suggestions."""
        suggestions = []
        
        # Efficiency analysis
        avg_time = summary.get("avg_execution_time_ms", 0)
        if avg_time > self.EFFICIENCY_THRESHOLD_MS:
            suggestions.append(OptimizationSuggestion(
                priority=Priority.HIGH,
                dimension=Dimension.EFFICIENCY,
                issue=f"执行时间过长 (平均 {avg_time}ms)",
                recommendation="考虑使用批量 API (如 GraphQL) 或并行处理",
                code_location=f"cron/{task_name}.py",
                estimated_impact=f"预计减少 {avg_time * 0.7:.0f}ms"
            ))
        
        avg_api = summary.get("avg_api_calls", 0)
        if avg_api > self.API_CALL_THRESHOLD:
            suggestions.append(OptimizationSuggestion(
                priority=Priority.HIGH,
                dimension=Dimension.EFFICIENCY,
                issue=f"API 调用过多 (平均 {avg_api} 次/执行)",
                recommendation="合并多个 API 调用，使用 GraphQL 批量查询",
                estimated_impact="预计减少 70% API 调用"
            ))
        
        # Stability analysis
        error_rate = summary.get("error_rate", 0)
        if error_rate > self.ERROR_RATE_THRESHOLD:
            suggestions.append(OptimizationSuggestion(
                priority=Priority.HIGH,
                dimension=Dimension.STABILITY,
                issue=f"错误率过高 ({error_rate:.1%})",
                recommendation="增加错误处理和重试机制",
                estimated_impact="预计减少 50% 错误"
            ))
        
        total_timeouts = summary.get("total_timeouts", 0)
        if total_timeouts > 0:
            suggestions.append(OptimizationSuggestion(
                priority=Priority.HIGH,
                dimension=Dimension.STABILITY,
                issue=f"发生 {total_timeouts} 次超时",
                recommendation="增加超时限制或优化查询性能",
                estimated_impact="预计消除超时"
            ))
        
        # Intelligence analysis - check for manual decision points
        # (This would require more detailed metrics about manual vs automatic decisions)
        
        # Prevention analysis - check for patterns that predict failures
        if summary.get("success_rate", 1.0) < 0.9:
            suggestions.append(OptimizationSuggestion(
                priority=Priority.MEDIUM,
                dimension=Dimension.PREVENTION,
                issue=f"成功率较低 ({summary.get('success_rate', 0):.1%})",
                recommendation="建立健康检查机制，提前发现问题",
                estimated_impact="预计提前 5 分钟发现问题"
            ))
        
        return suggestions
    
    def _calculate_health(self, summary: Dict, suggestions: List[OptimizationSuggestion]) -> float:
        """Calculate overall health score (0.0 - 1.0)."""
        if not summary:
            return 1.0
        
        health = 1.0
        
        # Deduct for low success rate
        success_rate = summary.get("success_rate", 1.0)
        health *= success_rate
        
        # Deduct for high error rate
        error_rate = summary.get("error_rate", 0)
        health -= error_rate * 0.3
        
        # Deduct for suggestions
        high_priority = sum(1 for s in suggestions if s.priority == Priority.HIGH)
        health -= high_priority * 0.1
        
        return max(0.0, min(1.0, health))


def generate_report(task_name: str) -> OptimizationReport:
    """Generate optimization report for a task."""
    optimizer = TaskOptimizer()
    return optimizer.analyze(task_name)


def save_report(report: OptimizationReport, output_path: Optional[Path] = None) -> Path:
    """Save report to file."""
    if output_path is None:
        from hermes_constants import get_hermes_home
        output_dir = get_hermes_home() / "cron" / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{report.task_name}_optimization_{datetime.utcnow().strftime('%Y%m%d')}.md"
    
    with open(output_path, 'w') as f:
        f.write(report.to_markdown())
    
    return output_path
