"""Recorder (WP4): agent spans -> ``agent_event`` rows.

Input paths (``source`` column): ``otel`` (in-process exporter), ``otlp`` (OTLP/HTTP JSON
receiver), ``proxy`` (black-box proxy log). Every path goes through
``supervisor.recorder.normalise`` so the same span gives the same row. Masking happens at
capture, per the agent's capture level (digest / masked / raw).
"""
