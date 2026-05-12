# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the workshop branch API."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import sys
sys.modules.setdefault("strands", MagicMock())
sys.modules.setdefault("strands.models", MagicMock())
sys.modules.setdefault("strands.models.bedrock", MagicMock())

from api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_alarms_endpoint_empty(client):
    resp = client.get("/api/alarms")
    assert resp.status_code == 200
    assert "alarms" in resp.json()


def test_trigger_alarm_valid_layer(client):
    resp = client.post("/api/alarms/trigger/core")
    assert resp.status_code == 200
    assert resp.json()["triggered"] is not None


def test_trigger_alarm_invalid_layer(client):
    resp = client.post("/api/alarms/trigger/invalid")
    assert resp.status_code == 200
    assert "error" in resp.json()
