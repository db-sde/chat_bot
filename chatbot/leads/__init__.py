"""Progressive lead capture and CRM delivery."""

from .funnel import LeadFunnel
from .webhook import CRMWebhook

__all__ = ["CRMWebhook", "LeadFunnel"]
