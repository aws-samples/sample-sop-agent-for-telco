# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for site descriptor validation and config generation (CSE-2997)."""

import sys
from pathlib import Path

import pytest
import yaml

# Add scripts directory to path so we can import the generation module
sys.path.insert(
    0, str(Path(__file__).parent.parent / "scripts")
)

# Import directly from the script module (without .py extension via importlib)
import importlib.util

_script_path = Path(__file__).parent.parent / "scripts" / "generate-site-config.py"
_spec = importlib.util.spec_from_file_location("generate_site_config", _script_path)
generate_site_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate_site_config)

validate_descriptor = generate_site_config.validate_descriptor
generate_agent_config = generate_site_config.generate_agent_config
generate_helm_values = generate_site_config.generate_helm_values

# --- Fixtures ---

CONFIGS_DIR = Path(__file__).parent.parent / "configs" / "site-descriptors"


@pytest.fixture
def sjc38_descriptor():
    with open(CONFIGS_DIR / "sjc38.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def docomo_descriptor():
    with open(CONFIGS_DIR / "docomo-site-002.yaml") as f:
        return yaml.safe_load(f)


# --- Tests ---


class TestValidDescriptorGeneratesConfig:
    """test_valid_descriptor_generates_config: valid descriptors produce valid output."""

    def test_sjc38_generates_agent_config(self, sjc38_descriptor):
        errors = validate_descriptor(sjc38_descriptor)
        assert errors == [], f"sjc38 descriptor should be valid but got: {errors}"
        config = generate_agent_config(sjc38_descriptor)
        assert config is not None
        assert "cluster" in config
        assert "version" in config

    def test_docomo_generates_agent_config(self, docomo_descriptor):
        errors = validate_descriptor(docomo_descriptor)
        assert errors == [], f"docomo descriptor should be valid but got: {errors}"
        config = generate_agent_config(docomo_descriptor)
        assert config is not None
        assert "cluster" in config
        assert "nodes" in config

    def test_docomo_generates_helm_values(self, docomo_descriptor):
        errors = validate_descriptor(docomo_descriptor)
        assert errors == []
        values = generate_helm_values(docomo_descriptor)
        assert values is not None
        assert "image" in values
        assert "config" in values


class TestMissingRequiredFieldFails:
    """test_missing_required_field_fails: missing site.name produces an error."""

    def test_missing_site_name(self, docomo_descriptor):
        del docomo_descriptor["site"]["name"]
        errors = validate_descriptor(docomo_descriptor)
        assert len(errors) > 0
        assert any("site.name" in e for e in errors)

    def test_missing_site_cluster(self, docomo_descriptor):
        del docomo_descriptor["site"]["cluster"]
        errors = validate_descriptor(docomo_descriptor)
        assert len(errors) > 0
        assert any("site.cluster" in e for e in errors)

    def test_missing_site_section_entirely(self):
        descriptor = {"images": {"registry": "example.com"}}
        errors = validate_descriptor(descriptor)
        assert len(errors) > 0
        assert any("site" in e for e in errors)

    def test_missing_images_registry(self, docomo_descriptor):
        del docomo_descriptor["images"]["registry"]
        errors = validate_descriptor(docomo_descriptor)
        assert len(errors) > 0
        assert any("images.registry" in e for e in errors)

    def test_missing_hardware_node_bmc_ip(self, docomo_descriptor):
        del docomo_descriptor["hardware"]["nodes"][0]["bmc_ip"]
        errors = validate_descriptor(docomo_descriptor)
        assert len(errors) > 0
        assert any("bmc_ip" in e for e in errors)


class TestGeneratedConfigHasClusterInfo:
    """test_generated_config_has_cluster_info: output has correct cluster.name/region."""

    def test_docomo_cluster_name(self, docomo_descriptor):
        config = generate_agent_config(docomo_descriptor)
        assert config["cluster"]["name"] == "site-002-workload"

    def test_docomo_cluster_region(self, docomo_descriptor):
        config = generate_agent_config(docomo_descriptor)
        assert config["cluster"]["region"] == "us-west-1"

    def test_sjc38_cluster_name(self, sjc38_descriptor):
        config = generate_agent_config(sjc38_descriptor)
        assert config["cluster"]["name"] == "eks-nec-sjc38-cluster-nec-eks-outposts"

    def test_sjc38_cluster_region(self, sjc38_descriptor):
        config = generate_agent_config(sjc38_descriptor)
        assert config["cluster"]["region"] == "us-east-1"


class TestGeneratedValuesHasImageRepo:
    """test_generated_values_has_image_repo: output has correct image.repository."""

    def test_docomo_image_repository(self, docomo_descriptor):
        values = generate_helm_values(docomo_descriptor)
        assert values["image"]["repository"] == "public.ecr.aws/ano-platform"

    def test_sjc38_image_repository(self, sjc38_descriptor):
        values = generate_helm_values(sjc38_descriptor)
        assert (
            values["image"]["repository"]
            == "833185305196.dkr.ecr.us-east-1.amazonaws.com/outposts25-upf-ecr-repositry/interop"
        )

    def test_docomo_image_tag(self, docomo_descriptor):
        values = generate_helm_values(docomo_descriptor)
        assert values["image"]["tag"] == "24.10"


class TestNodesMappedToConfigNodes:
    """test_nodes_mapped_to_config_nodes: hardware.nodes map to config nodes with BMC."""

    def test_docomo_nodes_count(self, docomo_descriptor):
        config = generate_agent_config(docomo_descriptor)
        assert len(config["nodes"]) == 2

    def test_docomo_node_bmc_ips(self, docomo_descriptor):
        config = generate_agent_config(docomo_descriptor)
        bmc_ips = [n["bmc"]["ip"] for n in config["nodes"]]
        assert "192.168.30.10" in bmc_ips
        assert "192.168.30.11" in bmc_ips

    def test_docomo_node_names(self, docomo_descriptor):
        config = generate_agent_config(docomo_descriptor)
        names = [n["name"] for n in config["nodes"]]
        assert "dell-worker-1" in names
        assert "dell-worker-2" in names

    def test_docomo_node_roles(self, docomo_descriptor):
        config = generate_agent_config(docomo_descriptor)
        for node in config["nodes"]:
            assert "worker" in node["roles"]
            assert "ran" in node["roles"]

    def test_docomo_node_oam_ip(self, docomo_descriptor):
        config = generate_agent_config(docomo_descriptor)
        oam_ips = [n["oam_ip"] for n in config["nodes"]]
        assert "192.168.31.10" in oam_ips
        assert "192.168.31.11" in oam_ips

    def test_docomo_node_bmc_type(self, docomo_descriptor):
        config = generate_agent_config(docomo_descriptor)
        for node in config["nodes"]:
            assert node["bmc"]["type"] == "idrac"

    def test_sjc38_no_nodes_when_absent(self, sjc38_descriptor):
        """sjc38 has no hardware.nodes section — generates empty nodes list."""
        config = generate_agent_config(sjc38_descriptor)
        assert config["nodes"] == []


class TestIrsaInGeneratedValues:
    """IRSA annotation is generated from aws.bedrockRoleArn in site descriptor."""

    def test_docomo_has_irsa_annotation(self, docomo_descriptor):
        values = generate_helm_values(docomo_descriptor)
        assert "serviceAccount" in values
        annotations = values["serviceAccount"]["annotations"]
        assert "eks.amazonaws.com/role-arn" in annotations
        assert annotations["eks.amazonaws.com/role-arn"] == "arn:aws:iam::833542146025:role/site-002-ano-bedrock"

    def test_irsa_annotation_absent_when_no_aws_section(self):
        """Descriptor without aws.bedrockRoleArn → no serviceAccount annotation."""
        descriptor = {
            "site": {"name": "test", "cluster": "c", "region": "us-west-1"},
            "images": {"registry": "test.ecr"},
            # No aws section
        }
        values = generate_helm_values(descriptor)
        if "serviceAccount" in values:
            annotations = values["serviceAccount"].get("annotations", {})
            assert "eks.amazonaws.com/role-arn" not in annotations

    def test_missing_bedrock_role_arn_fails_validation(self):
        """aws section without bedrockRoleArn fails validation."""
        descriptor = {
            "site": {"name": "test", "cluster": "c", "region": "us-west-1"},
            "images": {"registry": "test.ecr"},
            "aws": {"bedrockRoleArn": ""},  # empty bedrockRoleArn
        }
        errors = validate_descriptor(descriptor)
        assert any("aws" in e.lower() or "bedrockRoleArn" in e for e in errors)

    def test_missing_aws_section_entirely_fails_validation(self):
        """No aws section at all fails validation."""
        descriptor = {
            "site": {"name": "test", "cluster": "c", "region": "us-west-1"},
            "images": {"registry": "test.ecr"},
        }
        errors = validate_descriptor(descriptor)
        assert any("aws" in e.lower() for e in errors)

    def test_valid_aws_section_passes(self):
        """aws.bedrockRoleArn present → validation passes."""
        descriptor = {
            "site": {"name": "test", "cluster": "c", "region": "us-west-1"},
            "images": {"registry": "test.ecr"},
            "aws": {"bedrockRoleArn": "arn:aws:iam::123456789:role/test-role"},
        }
        errors = validate_descriptor(descriptor)
        assert errors == []

    def test_service_account_create_true(self, docomo_descriptor):
        values = generate_helm_values(docomo_descriptor)
        assert values["serviceAccount"]["create"] is True
