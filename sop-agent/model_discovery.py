# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Dynamic Bedrock model discovery and selection.

Probes available Claude models at startup and selects the best available
for each capability tier (fast, balanced, powerful). No hardcoded model IDs.

Usage:
    from model_discovery import get_models, get_model_id

    models = get_models(boto_session)  # Probes once, caches result
    model_id = get_model_id("fast")    # Returns best available for tier
"""

import logging
import os
import time
from dataclasses import dataclass, field

import boto3

logger = logging.getLogger(__name__)

# Model tiers: ordered from most preferred to least within each tier
# Format: (inference_profile_id, display_name, tier)
# Tiers: "fast" (cheap/quick), "balanced" (default), "powerful" (complex tasks)
_CANDIDATE_MODELS = [
    # Powerful tier (for complex SOPs, correction, high-stakes)
    ("us.anthropic.claude-opus-4-7", "Claude Opus 4.7", "powerful"),
    ("us.anthropic.claude-opus-4-6-v1", "Claude Opus 4.6", "powerful"),
    ("us.anthropic.claude-opus-4-5-20251101-v1:0", "Claude Opus 4.5", "powerful"),
    ("us.anthropic.claude-opus-4-1-20250805-v1:0", "Claude Opus 4.1", "powerful"),
    ("us.anthropic.claude-opus-4-20250514-v1:0", "Claude Opus 4", "powerful"),
    # Balanced tier (default agent model)
    ("us.anthropic.claude-sonnet-4-6", "Claude Sonnet 4.6", "balanced"),
    ("us.anthropic.claude-sonnet-4-5-20250929-v1:0", "Claude Sonnet 4.5", "balanced"),
    ("us.anthropic.claude-sonnet-4-20250514-v1:0", "Claude Sonnet 4", "balanced"),
    ("us.anthropic.claude-3-5-sonnet-20241022-v2:0", "Claude 3.5 Sonnet", "balanced"),
    # Fast tier (simple validation, high-volume)
    ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "Claude Haiku 4.5", "fast"),
    ("us.anthropic.claude-3-5-haiku-20241022-v1:0", "Claude 3.5 Haiku", "fast"),
    ("us.anthropic.claude-3-haiku-20240307-v1:0", "Claude 3 Haiku", "fast"),
]


@dataclass
class DiscoveredModels:
    """Result of model discovery — the best available model per tier."""
    fast: str | None = None
    fast_name: str | None = None
    balanced: str | None = None
    balanced_name: str | None = None
    powerful: str | None = None
    powerful_name: str | None = None
    all_available: list = field(default_factory=list)
    discovery_time_ms: int = 0
    region: str = ""

    def get(self, tier: str) -> str | None:
        """Get model ID for a tier, with fallback chain: powerful→balanced→fast."""
        if tier == "powerful":
            return self.powerful or self.balanced or self.fast
        if tier == "balanced":
            return self.balanced or self.powerful or self.fast
        if tier == "fast":
            return self.fast or self.balanced
        return self.balanced  # default

    def summary(self) -> str:
        lines = [f"Model Discovery ({self.region}, {self.discovery_time_ms}ms):"]
        if self.fast:
            lines.append(f"  fast:     {self.fast_name} ({self.fast})")
        if self.balanced:
            lines.append(f"  balanced: {self.balanced_name} ({self.balanced})")
        if self.powerful:
            lines.append(f"  powerful: {self.powerful_name} ({self.powerful})")
        if not any([self.fast, self.balanced, self.powerful]):
            lines.append("  ⚠️  No models available! Check Bedrock access.")
        return "\n".join(lines)


# Module-level cache
_cache = {}  # type: Dict[str, DiscoveredModels]


def discover_models(
    boto_session: boto3.Session | None = None,
    region: str | None = None,
    force: bool = False,
) -> DiscoveredModels:
    """Probe Bedrock to find the best available model per tier.

    Sends a minimal 1-token request to each candidate model (most preferred first).
    Stops probing a tier once the first working model is found.

    Results are cached per region. Use force=True to re-probe.

    Args:
        boto_session: boto3 session (creates default if None)
        region: Override region (uses session region or BEDROCK_REGION env var)
        force: Re-probe even if cached

    Returns:
        DiscoveredModels with the best available model per tier
    """
    if boto_session is None:
        profile = os.getenv("BEDROCK_PROFILE") or None
        region = region or os.getenv("BEDROCK_REGION", "us-west-2")
        boto_session = boto3.Session(profile_name=profile, region_name=region)

    region = region or boto_session.region_name or "us-west-2"
    cache_key = region

    if not force and cache_key in _cache:
        return _cache[cache_key]

    logger.info(f"Discovering available Bedrock models in {region}...")
    start = time.time()

    client = boto_session.client("bedrock-runtime", region_name=region)
    result = DiscoveredModels(region=region)
    found_tiers = set()

    for model_id, display_name, tier in _CANDIDATE_MODELS:
        # Skip if we already found a model for this tier
        if tier in found_tiers:
            continue

        if _probe_model(client, model_id):
            result.all_available.append({"id": model_id, "name": display_name, "tier": tier})
            if tier == "fast" and not result.fast:
                result.fast = model_id
                result.fast_name = display_name
                found_tiers.add("fast")
            elif tier == "balanced" and not result.balanced:
                result.balanced = model_id
                result.balanced_name = display_name
                found_tiers.add("balanced")
            elif tier == "powerful" and not result.powerful:
                result.powerful = model_id
                result.powerful_name = display_name
                found_tiers.add("powerful")

        # Early exit if all tiers found
        if len(found_tiers) == 3:
            break

    result.discovery_time_ms = int((time.time() - start) * 1000)
    _cache[cache_key] = result

    logger.info(result.summary())
    return result


def _probe_model(client, model_id: str) -> bool:
    """Send a minimal invoke_model request to check if a model is accessible.

    Uses invoke_model (not converse) because some accounts have the Converse API
    blocked by the use case form while invoke_model works fine.

    Returns True if the model responds, False if unavailable.
    """
    import json as _json
    body = _json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    })
    try:
        client.invoke_model(
            modelId=model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        logger.debug(f"  ✓ {model_id}")
        return True
    except client.exceptions.ValidationException as e:
        # Model not supported for on-demand or needs inference profile
        logger.debug(f"  ✗ {model_id}: {e}")
        return False
    except client.exceptions.AccessDeniedException:
        logger.debug(f"  ✗ {model_id}: access denied")
        return False
    except Exception as e:
        err_str = str(e)
        if "ResourceNotFoundException" in type(e).__name__:
            logger.debug(f"  ✗ {model_id}: {err_str[:80]}")
            return False
        if "Legacy" in err_str or "use case" in err_str.lower():
            logger.debug(f"  ✗ {model_id}: {err_str[:80]}")
            return False
        if "ThrottlingException" in type(e).__name__:
            logger.debug(f"  ✓ {model_id} (throttled but available)")
            return True
        logger.warning(f"  ? {model_id}: unexpected error: {type(e).__name__}: {err_str[:100]}")
        return False


def get_models(boto_session: boto3.Session | None = None, region: str | None = None) -> DiscoveredModels:
    """Get discovered models (cached). Alias for discover_models()."""
    return discover_models(boto_session=boto_session, region=region)


def get_model_id(tier: str = "balanced", boto_session: boto3.Session | None = None, region: str | None = None) -> str:
    """Get the best available model ID for a tier.

    Args:
        tier: "fast", "balanced", or "powerful"
        boto_session: boto3 session
        region: AWS region

    Returns:
        Model ID string

    Raises:
        RuntimeError if no models are available
    """
    models = get_models(boto_session=boto_session, region=region)
    model_id = models.get(tier)
    if not model_id:
        raise RuntimeError(
            f"No Bedrock models available in {models.region}. "
            "Ensure your account has Anthropic model access enabled. "
            "Visit https://console.aws.amazon.com/bedrock/ to submit the use case form."
        )
    return model_id


# Legacy compatibility: map old model key names to tiers
_LEGACY_KEY_TO_TIER = {
    "haiku": "fast",
    "sonnet": "balanced",
    "sonnet3.5": "balanced",
    "sonnet4.5": "balanced",
    "opus": "powerful",
    "opus4.6": "powerful",
}


def resolve_model_key(key: str, boto_session: boto3.Session | None = None, region: str | None = None) -> str:
    """Resolve a legacy model key (haiku, sonnet, opus) to an actual model ID.

    Supports both legacy keys and direct model IDs (pass-through).

    Args:
        key: Legacy key like "haiku"/"sonnet"/"opus" or a direct model ID
        boto_session: boto3 session
        region: AWS region

    Returns:
        Resolved model ID
    """
    tier = _LEGACY_KEY_TO_TIER.get(key)
    if tier:
        return get_model_id(tier, boto_session=boto_session, region=region)
    # Assume it's a direct model ID
    return key


# CLI entry point for testing
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG if "--debug" in sys.argv else logging.INFO)

    profile = os.getenv("BEDROCK_PROFILE") or os.getenv("AWS_PROFILE")
    region = os.getenv("BEDROCK_REGION", "us-west-2")
    session = boto3.Session(profile_name=profile, region_name=region)

    print(f"Probing models in {region} (profile={profile or 'default'})...\n")
    models = discover_models(session, force=True)
    print(models.summary())
    print(f"\nTotal available: {len(models.all_available)}")
    for m in models.all_available:
        print(f"  [{m['tier']:>8}] {m['name']} — {m['id']}")
