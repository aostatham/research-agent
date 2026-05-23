"""
Output package for the research-agent pipeline.

Exports the public interface for report formatting and persistence:
  build_metadata()   — markdown metadata table for report headers
  convert_to_html()  — markdown-to-HTML conversion
  convert_to_pdf()   — HTML-to-PDF conversion (requires weasyprint)
  save_report()      — write report to output/ in markdown/HTML/PDF
  update_index()     — append run record to output/index.md
"""

from .formatter import build_metadata, convert_to_html, convert_to_pdf
from .writer import save_report, update_index

__all__ = [
    "build_metadata",
    "convert_to_html",
    "convert_to_pdf",
    "save_report",
    "update_index",
]
