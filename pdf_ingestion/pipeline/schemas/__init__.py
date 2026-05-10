"""Schema extractors package.

Provides rule-based field and table extraction per document type.
"""

from pipeline.schemas.bank_statement import BankStatementExtractor
from pipeline.schemas.base import BaseSchemaExtractor
from pipeline.schemas.custody_statement import CustodyStatementExtractor
from pipeline.schemas.router import detect_schema, get_extractor, route_and_extract
from pipeline.schemas.swift_confirm import SwiftConfirmExtractor

__all__ = [
    "BaseSchemaExtractor",
    "BankStatementExtractor",
    "CustodyStatementExtractor",
    "SwiftConfirmExtractor",
    "detect_schema",
    "get_extractor",
    "route_and_extract",
]
