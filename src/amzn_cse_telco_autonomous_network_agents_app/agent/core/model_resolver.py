# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Dynamic Bedrock model resolver — picks the best available model at runtime."""

import logging
import os

import boto3

from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import ModelTier

logger = logging.getLogger(__name__)

# Preference order: fastest first for agents, smartest for complex tasks
_PREFERRED_FAST = [
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    "us.anthropic.claude-3-haiku-20240307-v1:0",
]

_PREFERRED_SMART = [
    "us.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "us.anthropic.claude-3-sonnet-20240229-v1:0",
]

# Cache resolved models
_cache: dict = {}


def invalidate_cache() -> None:
    """Clear the resolved model caches. Called on config reload."""
    _cache.clear()
    _probe_cache.clear()


def get_model(tier: ModelTier = ModelTier.FAST) -> str:
    """Resolve the best available model for the given tier.

    Priority order:
        1. BEDROCK_MODEL_ID env var (explicit override)
        2. config_store bedrock_model_override (config-driven override)
        3. config_store bedrock_model_tier (config-driven tier)
        4. BEDROCK_MODEL_TIER env var (Helm values fallback)
        5. caller's tier argument

    Args:
        tier: ModelTier.FAST (haiku-class, for tools/agents) or ModelTier.SMART
            (sonnet-class, for complex reasoning). ModelTier is a StrEnum, so a
            plain "fast"/"smart" string from config or env is accepted too.

    Returns:
        Model ID string suitable for Agent(model=...).
    """
    # Allow env override (highest priority)
    env_override = os.getenv("BEDROCK_MODEL_ID")
    if env_override:
        return env_override

    # Config-driven tier/override (import lazily to avoid circular)
    # Config tier always wins over env BEDROCK_MODEL_TIER (by design).
    # Env is only a fallback for when config_store isn't initialized.
    _tier_from_config = False
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store import get_config

        cfg = get_config()
        if cfg:
            if cfg.bedrock_model_override:
                return cfg.bedrock_model_override
            if cfg.bedrock_model_tier in ModelTier.values():
                tier = ModelTier(cfg.bedrock_model_tier)
                _tier_from_config = True
    except ImportError:
        pass

    # BEDROCK_MODEL_TIER env var (from Helm values) as fallback — only if config didn't set tier
    if not _tier_from_config:
        env_tier = os.getenv("BEDROCK_MODEL_TIER", "").strip().lower()
        if env_tier in ModelTier.values():
            tier = ModelTier(env_tier)

    cached = _cache.get(tier)
    if cached:
        return cached

    preferred = _PREFERRED_FAST if tier == ModelTier.FAST else _PREFERRED_SMART
    active = _list_active_profiles()

    for model_id in preferred:
        if model_id in active:
            _cache[tier] = model_id
            logger.info("Resolved %s model: %s", tier, model_id)
            return model_id

    # Fallback: first active Claude model
    fallback = next((m for m in active if "claude" in m), preferred[0])
    _cache[tier] = fallback
    logger.warning("No preferred %s model found, using fallback: %s", tier, fallback)
    return fallback


def build_model(tier: ModelTier = ModelTier.FAST, profile: str = "", region: str = ""):
    """Build a BedrockModel for the given tier in one place.

    Single seam for "resolve a tier to a model and wrap it in a session-bound
    BedrockModel", so call sites do not each repeat the resolve + session +
    construct boilerplate. The model ID is resolved via get_model(tier) (honoring
    the env/config priority chain); the session uses the project's profile/region
    convention via aws_session.

    Args:
        tier: ModelTier.FAST (haiku-class) or ModelTier.SMART (sonnet-class).
            Passed to get_model.
        profile: AWS profile; defaults to the BEDROCK_PROFILE env var (empty =
            default credential chain).
        region: AWS region; defaults to the BEDROCK_REGION env var, then us-west-2.

    Returns:
        A strands BedrockModel bound to the resolved model ID and session.
    """
    # Lazy imports: strands pulls in heavy deps, and importing aws_session at
    # module top would widen this resolver's import surface. Keeps the module
    # import-light, matching its existing convention.
    from strands.models.bedrock import BedrockModel

    from amzn_cse_telco_autonomous_network_agents_app.agent.util.aws import aws_session

    session = aws_session(
        profile or os.getenv("BEDROCK_PROFILE", ""),
        region or os.getenv("BEDROCK_REGION", "us-west-2"),
    )
    return BedrockModel(model_id=get_model(tier), boto_session=session)


# Runtime down-shift chain: if a model is deprecated/legacy or unavailable in the
# account, probe the next one. Distinct from _PREFERRED_* (which picks the best
# available at resolve time) — this cascades on a live converse() failure so a
# model that vanishes mid-operation degrades instead of crashing.
_MODEL_FALLBACKS = {
    "us.anthropic.claude-3-5-haiku-20241022-v1:0": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "us.anthropic.claude-sonnet-4-20250514-v1:0": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": "us.anthropic.claude-opus-4-20250514-v1:0",
    "us.anthropic.claude-opus-4-20250514-v1:0": "us.anthropic.claude-opus-4-6-v1",
}

# (model_id, region) -> resolved model_id, so each model is probed at most once.
_probe_cache: dict[tuple[str, str], str] = {}


def build_probed_model(model_id: str, boto_session):
    """Build a BedrockModel, probing for legacy/unavailable models and cascading.

    Sends a 1-token converse() to verify the model responds; on a "Legacy" or
    ResourceNotFoundException it walks _MODEL_FALLBACKS to the next model and
    retries. Any other error is raised. Results are cached per (model_id, region)
    so each model is probed at most once.

    This is the runtime down-shift path (distinct from get_model's resolve-time
    "best available" pick) — kept here so all model construction lives in one
    module. Used by the SOP execution graph, which starts from an explicit
    model_id (e.g. a complexity-selected tier) rather than a logical tier name.
    """
    from strands.models.bedrock import BedrockModel

    region = boto_session.region_name
    cache_key = (model_id, region)
    if cache_key in _probe_cache:
        return BedrockModel(model_id=_probe_cache[cache_key], boto_session=boto_session)

    tried: set = set()
    current = model_id
    while current and current not in tried:
        tried.add(current)
        try:
            client = boto_session.client("bedrock-runtime", region_name=region)
            client.converse(
                modelId=current,
                messages=[{"role": "user", "content": [{"text": "hi"}]}],
                inferenceConfig={"maxTokens": 1},
            )
            logger.info("Model OK: %s", current)
            _probe_cache[cache_key] = current
            return BedrockModel(model_id=current, boto_session=boto_session)
        except Exception as e:
            if "Legacy" in str(e) or "ResourceNotFoundException" in type(e).__name__:
                fallback = _MODEL_FALLBACKS.get(current)
                logger.warning(
                    "Model %s unavailable (%s), falling back to %s",
                    current,
                    e.__class__.__name__,
                    fallback,
                )
                current = fallback
            else:
                raise
    msg = f"All model fallbacks exhausted starting from {model_id}: tried {tried}"
    raise RuntimeError(msg)


def _list_active_profiles() -> set:
    """Query Bedrock for active inference profiles. Cached after first call."""
    if "_profiles" in _cache:
        return _cache["_profiles"]

    try:
        region = os.getenv("BEDROCK_REGION", os.getenv("AWS_REGION", "us-west-2"))
        client = boto3.client("bedrock", region_name=region)
        profiles = client.list_inference_profiles()["inferenceProfileSummaries"]
        active = {p["inferenceProfileId"] for p in profiles if p["status"] == "ACTIVE"}
        _cache["_profiles"] = active
        return active
    except Exception as e:
        logger.warning("Failed to list inference profiles: %s. Using defaults.", e)
        _cache["_profiles"] = set()
        return set()
