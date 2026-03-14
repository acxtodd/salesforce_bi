"""
Pytest configuration and fixtures for Lambda function tests.

This module configures Hypothesis for property-based testing as specified
in the design documents for:
- Phase 3 Graph Enhancement
- Graph-Aware Zero-Config Retrieval
"""
import pytest

# Configure Hypothesis settings
# Design requirement: Minimum 100 iterations per property test
try:
    from hypothesis import settings, Verbosity, Phase
    
    # Register a profile for Phase 3 property-based tests
    settings.register_profile(
        "phase3",
        max_examples=100,  # Minimum 100 iterations per design.md
        deadline=None,  # No deadline for complex graph operations
        verbosity=Verbosity.normal,
        phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink],
    )
    
    # Register a profile for Graph-Aware Zero-Config Retrieval tests
    # As per design.md: "Minimum Iterations: 100 per property test"
    settings.register_profile(
        "graph_zero_config",
        max_examples=100,  # Minimum 100 iterations per design.md
        deadline=None,  # No deadline for complex planner/traversal operations
        verbosity=Verbosity.normal,
        phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink],
    )
    
    # Register a CI profile with more examples for thorough testing
    settings.register_profile(
        "ci",
        max_examples=200,
        deadline=None,
        verbosity=Verbosity.quiet,
    )
    
    # Register a dev profile for faster local iteration
    settings.register_profile(
        "dev",
        max_examples=50,
        deadline=None,
        verbosity=Verbosity.verbose,
    )
    
    # Load the graph_zero_config profile by default for new spec
    settings.load_profile("graph_zero_config")
    
    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "property: mark test as a property-based test using Hypothesis"
    )


@pytest.fixture
def hypothesis_available():
    """Fixture to check if Hypothesis is available."""
    return HYPOTHESIS_AVAILABLE
