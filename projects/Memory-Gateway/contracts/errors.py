class GatewayError(Exception): pass
class ScopeViolation(GatewayError): pass
class Unauthorized(GatewayError): pass
class ModelNotAllowed(GatewayError):
    def __init__(self, model, allowed):
        super().__init__(f"model {model} not allowed"); self.model = model
        self.allowed = sorted(allowed)
class PoolBusy(GatewayError):
    def __init__(self, model, retry_after_s, resident_alternatives=()):
        super().__init__(f"{model} busy, retry after {retry_after_s}s")
        self.model, self.retry_after_s = model, retry_after_s
        self.resident_alternatives = list(resident_alternatives)
class IndexUnavailable(GatewayError): pass
class MemoryTooLong(GatewayError): pass
class PilotUnavailable(GatewayError): pass
