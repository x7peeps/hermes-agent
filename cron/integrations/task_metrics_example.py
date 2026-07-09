"""Example: Integrating Task Metrics with GitHub PR Monitor.

This shows how to use the TaskMetricsCollector in an existing cron job.
"""

# Example usage in your existing PR monitor script:

"""
# Before:
def main():
    print("Starting PR monitor...")
    prs = get_open_prs()
    for pr in prs:
        # process PR
        pass
    print("Done!")

# After:
from cron.task_metrics import track_task

def main():
    with track_task("github-pr-monitor") as tracker:
        print("Starting PR monitor...")
        
        # Track API calls
        tracker.record_api_call()  # for each API call
        
        prs = get_open_prs()
        
        for pr in prs:
            try:
                # process PR
                tracker.record_api_call()  # for each PR API call
            except Exception as e:
                tracker.record_error("processing_error", str(e))
                tracker.success = False
        
        print("Done!")
    
    # Metrics are automatically saved after the block
    # Report can be generated:
    from cron.task_optimizer import generate_report, save_report
    
    report = generate_report("github-pr-monitor")
    save_report(report)
    print(report.to_markdown())
"""

# Integration points for existing scripts:
# 1. Wrap main() with track_task context manager
# 2. Call record_api_call() for each API invocation
# 3. Call record_error() or record_timeout() on failures
# 4. After execution, generate optimization report

# Configuration:
# - Metrics stored in: ~/.hermes/cron/metrics/<task_name>/
# - Reports saved to: ~/.hermes/cron/reports/<task_name>_optimization_<date>.md
