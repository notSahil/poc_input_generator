"""Custom exception hierarchy for the input generator."""


class InputGeneratorError(Exception):
    """Base exception for all application errors."""
    pass


class ConfigNotFoundError(InputGeneratorError):
    """YAML config file for a report was not found."""
    pass


class ConfigInvalidError(InputGeneratorError):
    """YAML config file is malformed or missing required fields."""
    pass


class MappingError(InputGeneratorError):
    """Error in the mapping file (missing columns, bad data, etc.)."""
    pass


class MappingFileNotFoundError(MappingError):
    """The Excel mapping file does not exist."""
    pass


class ValidationError(InputGeneratorError):
    """Input data failed validation checks."""
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


class EngineSkipError(InputGeneratorError):
    """Engine skipped execution because input files are missing."""
    pass


class SalesforceAuthError(InputGeneratorError):
    """Salesforce authentication failed or token is expired."""
    pass


class SalesforceAPIError(InputGeneratorError):
    """Salesforce API returned an error response."""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
