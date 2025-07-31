"""
# Telemetry Module

## Description
This module initializes telemetry for the botframework application using Azure Application Insights.
It configures logging and tracing to monitor application performance and behavior.

## Usage
from utils.telemetry import logger, tracer
logger.info("Application started")
with tracer.span(name="example_span"):
    pass
"""

import os
import logging
from opencensus.ext.azure.trace_exporter import AzureExporter
from opencensus.trace.tracer import Tracer
from opencensus.trace.samplers import ProbabilitySampler

APPINSIGHTS_KEY = os.getenv("APPINSIGHTS_INSTRUMENTATION_KEY")

# Logger solo para consola (sin Application Insights handler)
logger = logging.getLogger("botframework")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(console_handler)

if APPINSIGHTS_KEY:
    tracer = Tracer(
        exporter=AzureExporter(connection_string=f'InstrumentationKey={APPINSIGHTS_KEY}'),
        sampler=ProbabilitySampler(1.0)
    )
    logger.info("✅ Application Insights tracer initialized")
else:
    tracer = Tracer()
    logger.warning("⚠️ APPINSIGHTS_INSTRUMENTATION_KEY is missing. Telemetry is not fully enabled.")
