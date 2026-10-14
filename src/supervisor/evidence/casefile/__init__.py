"""Case-file generator (WP6): bilingual (VN + EN) incident file as JSON, HTML or PDF."""

from supervisor.evidence.casefile.builder import (
    CaseFile,
    CaseFileError,
    ChainRef,
    JudgeFinding,
    RuleBroken,
    SbvClocks,
    SignoffItem,
    TimelineItem,
    build_case_file,
    case_chain_refs,
    load_case_inputs,
    record_case_file,
    write_case_file,
)
from supervisor.evidence.casefile.render_html import render_html
from supervisor.evidence.casefile.render_json import parse_json, render_json
from supervisor.evidence.casefile.render_pdf import RenderResult, render_pdf

__all__ = [
    "CaseFile",
    "CaseFileError",
    "ChainRef",
    "JudgeFinding",
    "RenderResult",
    "RuleBroken",
    "SbvClocks",
    "SignoffItem",
    "TimelineItem",
    "build_case_file",
    "case_chain_refs",
    "load_case_inputs",
    "parse_json",
    "record_case_file",
    "render_html",
    "render_json",
    "render_pdf",
    "write_case_file",
]
