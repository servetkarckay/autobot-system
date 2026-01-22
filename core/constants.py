from enum import Enum


class Indicator(Enum):
    """
    Enum for technical indicator identifiers.
    Using an Enum prevents silent errors from typos in strings ('magic strings')
    and makes the codebase safer and easier to refactor.
    """
    RSI = "RSI_14"
    EMA_20 = "EMA_20"
    EMA_50 = "EMA_50"
